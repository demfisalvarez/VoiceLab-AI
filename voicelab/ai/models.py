"""Catálogo de modelos de IA y descargas verificadas desde Hugging Face.

Los modelos se descargan una sola vez a %APPDATA%\\VoiceLabAI\\models y
después funcionan sin Internet. Antes de descargar, la app muestra el tamaño
y la licencia de cada modelo.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import ssl
import sys
import threading
import urllib.request
from pathlib import Path
from typing import Callable

from .. import paths

log = logging.getLogger(__name__)
HF = "https://huggingface.co"
UA = "VoiceLabAI/1.0"

CATALOG: dict[str, dict] = {
    "chatterbox-v2": {
        "name": "Chatterbox Multilingual (texto a voz y clonación instantánea)",
        "task": "tts", "license": "MIT (Resemble AI)",
        "repo": "onnx-community/chatterbox-multilingual-ONNX",
        "files": ["tokenizer.json", "onnx/speech_encoder.onnx", "onnx/speech_encoder.onnx_data",
                  "onnx/embed_tokens.onnx", "onnx/embed_tokens.onnx_data",
                  "onnx/language_model.onnx", "onnx/language_model.onnx_data",
                  "onnx/conditional_decoder.onnx", "onnx/conditional_decoder.onnx_data"],
        "lm": "onnx/language_model.onnx", "approx_gb": 3.2,
    },
    # Exportación comunitaria «V3»: probada en Windows con Whisper, no lee el texto (dice frases
    # inventadas). Solo se muestra si estaba descargada, para poder borrarla.
    "chatterbox-v3": {
        "name": "Chatterbox «V3» (exportación comunitaria defectuosa: elimínala)",
        "task": "tts", "license": "MIT (Resemble AI); exportación ONNX comunitaria", "deprecated": True,
        "repo": "Masterx/chatterbox-multilingual-v3-ONNX",
        "files": ["tokenizer.json", "onnx/speech_encoder.onnx", "onnx/speech_encoder.onnx_data",
                  "onnx/embed_tokens.onnx", "onnx/embed_tokens.onnx_data",
                  "onnx/language_model_q4.onnx", "onnx/language_model_q4.onnx_data",
                  "onnx/conditional_decoder.onnx", "onnx/conditional_decoder.onnx_data"],
        "lm": "onnx/language_model_q4.onnx", "approx_gb": 1.55,
    },
    "rvc-base": {
        "name": "Base para conversión RVC (ContentVec + RMVPE)",
        "task": "rvc", "license": "MIT (RVC-Project)",
        "repo": "lj1995/VoiceConversionWebUI",
        "files": ["rmvpe.onnx"],
        "extra": [("NaruseMioShirakana/MoeSS-SUBModel", "vec-768-layer-12.onnx")],
        "approx_gb": 0.55,
    },
    "rvc-train": {
        "name": "Base para entrenar voces fieles (RVC v2, 40 kHz)",
        "task": "rvc_train", "license": "MIT (RVC-Project)",
        "repo": "lj1995/VoiceConversionWebUI",
        "files": ["pretrained_v2/f0G40k.pth", "pretrained_v2/f0D40k.pth"],
        "approx_gb": 0.21,
    },
    "apbwe": {
        "name": "AP-BWE: alta definición 48 kHz para la voz en directo",
        "task": "vc_hd", "license": "MIT (Ye-Xin Lu, USTC)",
        "repo": "yxlu-0102/AP-BWE (pesos del autor en Google Drive)",
        "files": [], "approx_gb": 0.12,
        "direct": [{"file": "apbwe_16kto48k.pt", "size": 119097961,
                    "sha256": "305a05dcab7dc29ffba09d32692d7a34550fc8fbdf338013641ff5d39a3cb285",
                    "url": "https://drive.usercontent.google.com/download?id=1HYkD_5ha9GMrjzbTiSFiO1uQQwxXET15"
                           "&export=download&confirm=t"}],
    },
    "meanvc2": {
        "name": "MeanVC2: voz instantánea en directo (experimental)",
        "task": "vc_live", "license": "Apache 2.0 (ASLP-lab); codificador de hablante WavLM/ECAPA de Microsoft UniSpeech (MIT)",
        "repo": "ASLP-lab/MeanVC2", "flat": True,
        "files": ["fastu2pp_160ms.pt", "fastu2pp_80ms.pt", "meanvc2_120ms_40ms.safetensors",
                  "meanvc2_40ms_40ms.safetensors", "vocos.pt"],
        # Publicado por Microsoft en Google Drive; se usan réplicas en Hugging Face (SHA-256 verificado).
        "extra": [(["Dongchao/UniAudio", "subatomicseer/wavlm-large-sv-ckpts", "lmzjms/wavlm-large"],
                   "wavlm_large_finetune.pth")],
        "approx_gb": 1.6,
    },
}


def model_dir(key: str) -> Path:
    return paths.models_dir() / key


def installed(key: str) -> bool:
    d = model_dir(key)
    return (d / ".complete").exists()


def status() -> list[dict]:
    out = []
    for key, m in CATALOG.items():
        if m.get("deprecated") and not model_dir(key).exists():
            continue
        out.append({"id": key, "name": m["name"], "task": m["task"], "license": m["license"],
                    "repo": m["repo"], "approx_gb": m["approx_gb"], "installed": installed(key),
                    "deprecated": bool(m.get("deprecated"))})
    return out


def _ctx():
    return ssl.create_default_context()


def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30, context=_ctx()) as r:  # noqa: S310
        link = r.headers.get("Link", "") if getattr(r, "headers", None) else ""
        return json.loads(r.read().decode()), link


def _next_link(link: str) -> str | None:
    for part in (link or "").split(","):
        if 'rel="next"' in part and "<" in part:
            return part[part.index("<") + 1: part.index(">")]
    return None


def _remote_sizes(repo: str, folders=("",)) -> dict[str, dict]:
    """Tamaño y SHA-256 (LFS) de los archivos de ``folders`` según la API de Hugging Face.

    Se consulta carpeta por carpeta (sin recursión) y se siguen las páginas,
    así funciona también en repositorios con miles de archivos.
    """
    info: dict[str, dict] = {}
    for folder in sorted(set(folders)):
        url = f"{HF}/api/models/{repo}/tree/main" + (f"/{folder}" if folder else "")
        pages = 0
        while url and pages < 50:
            items, link = _get_json(url)
            for it in items:
                if it.get("type") == "file":
                    lfs = it.get("lfs") or {}
                    info[it["path"]] = {"size": it.get("size"), "sha256": lfs.get("oid")}
            url, pages = _next_link(link), pages + 1
    return info


def download_file(repo: str, path: str, dest: Path, expect: dict | None,
                  progress: Callable[[int], None], url: str | None = None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and expect and expect.get("size") == dest.stat().st_size:
        progress(dest.stat().st_size)
        return
    part = dest.with_suffix(dest.suffix + ".part")
    done = part.stat().st_size if part.exists() else 0
    headers = {"User-Agent": UA}
    if done:
        headers["Range"] = f"bytes={done}-"
    req = urllib.request.Request(url or f"{HF}/{repo}/resolve/main/{path}", headers=headers)
    with urllib.request.urlopen(req, timeout=60, context=_ctx()) as r:  # noqa: S310
        ctype = (r.headers.get("Content-Type", "") if getattr(r, "headers", None) else "") or ""
        if url and "text/html" in ctype:  # Google Drive devuelve una página si hay límite de descargas
            raise RuntimeError("El servidor de descarga (Google Drive) no entrega el archivo ahora mismo; "
                               "suele ser un límite temporal. Vuelve a intentarlo más tarde.")
        if done and r.status != 206:      # el servidor no admite reanudar
            done = 0
            part.unlink(missing_ok=True)
        with open(part, "ab" if done else "wb") as f:
            progress(done)
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                progress(done)
    if expect and expect.get("size") and part.stat().st_size != expect["size"]:
        raise RuntimeError(f"Descarga incompleta de {path}. Vuelve a intentarlo.")
    if expect and expect.get("sha256"):
        h = hashlib.sha256()
        with open(part, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 22), b""):
                h.update(chunk)
        if h.hexdigest() != expect["sha256"]:
            part.unlink(missing_ok=True)
            raise RuntimeError(f"El archivo {path} no supera la comprobación de integridad (SHA-256).")
    os.replace(part, dest)


def _folder(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def install(key: str, progress: Callable[[float], None]) -> dict:
    """Descarga los archivos del modelo ``key`` (reanudable y verificado).

    Cada entrada de ``extra`` es ``(repo, archivo)`` o ``([repo1, repo2…], archivo)``:
    con varias réplicas se usa la primera que tenga el archivo.
    """
    m = CATALOG[key]
    d = model_dir(key)
    d.mkdir(parents=True, exist_ok=True)
    if m.get("direct"):                   # archivos con dirección fija (fuera de Hugging Face)
        total = sum(f["size"] for f in m["direct"]) or 1
        base = 0
        for f in m["direct"]:
            download_file("", f["file"], d / f["file"], {"size": f["size"], "sha256": f["sha256"]},
                          lambda n, b=base: progress((b + n) / total * 0.98), url=f["url"])
            base += f["size"]
        (d / ".complete").write_text(json.dumps({"files": [f["file"] for f in m["direct"]]}), encoding="utf-8")
        progress(1.0)
        return {"id": key, "installed": True}
    wanted: list[tuple[list[str], str]] = [([m["repo"]], f) for f in m["files"]]
    wanted += [([r] if isinstance(r, str) else list(r), f) for r, f in m.get("extra", [])]
    cache: dict[tuple[str, str], dict] = {}

    def lookup(repo: str, folder: str) -> dict:
        if (repo, folder) not in cache:
            cache[(repo, folder)] = _remote_sizes(repo, (folder,))
        return cache[(repo, folder)]

    plan, missing, errors = [], [], []
    for repos, f in wanted:
        chosen = None
        for repo in repos:
            try:
                files = lookup(repo, _folder(f))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{repo}: {exc}")
                continue
            if f in files:
                chosen = (repo, f, d / Path(f).name if m.get("flat") else d / f, files[f])
                break
        if chosen is None:
            missing.append(f)
        else:
            plan.append(chosen)
    if missing:
        if errors and len(errors) >= len(missing):
            raise RuntimeError(f"No se pudo contactar con Hugging Face ({errors[0]}). Comprueba la conexión.")
        raise RuntimeError("El repositorio del modelo ha cambiado y faltan archivos: " + ", ".join(missing))
    total = sum((exp["size"] or 0) for *_, exp in plan) or 1
    free = shutil.disk_usage(d).free
    pending = sum((exp["size"] or 0) for _, _, dest, exp in plan
                  if not (dest.exists() and dest.stat().st_size == exp.get("size")))
    if free < pending * 1.1:
        raise RuntimeError(f"No hay espacio suficiente: hacen falta {pending / 1e9:.1f} GB libres.")
    base = 0
    for repo, f, dest, exp in plan:
        download_file(repo, f, dest, exp, lambda n, b=base: progress((b + n) / total * 0.98))
        base += exp["size"] or 0
    (d / ".complete").write_text(json.dumps({"repo": m["repo"], "files": [f"{r}/{f}" for r, f, *_ in plan]}),
                                 encoding="utf-8")
    progress(1.0)
    return {"id": key, "installed": True}


def remove(key: str) -> None:
    d = model_dir(key)
    if d.exists():
        shutil.rmtree(d)
