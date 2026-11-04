"""Perfiles de voz guardados localmente.

Cada perfil es una carpeta en %APPDATA%\\VoiceLabAI\\profiles\\<id>\\ con:
  profile.json   metadatos, ajustes de efectos y de clonación
  avatar.png|jpg imagen opcional
  reference.wav  audio original de referencia (perfiles de IA)
  model/         archivos de modelo (perfiles RVC)
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import threading
import time
import uuid
import zipfile
from pathlib import Path

from . import paths
from .audio.effects import sanitize

TYPES = {"effects": "Efectos", "instant": "IA instantánea", "rvc": "IA entrenada (RVC)"}
AVATAR_MAX = 3 * 1024 * 1024
EXT = ".vlprofile"


class ProfileError(ValueError):
    pass


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _safe_name(name: str) -> str:
    name = re.sub(r"\s+", " ", str(name or "")).strip()
    if not name:
        raise ProfileError("El perfil necesita un nombre.")
    return name[:80]


class ProfileStore:
    def __init__(self, root: Path | None = None):
        self.root = root or (paths.data_dir() / "profiles")
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    # ------------------------------------------------------------- internos
    def _dir(self, pid: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", str(pid)):
            raise ProfileError("Identificador de perfil no válido.")
        d = self.root / pid
        if not (d / "profile.json").exists():
            raise ProfileError("Ese perfil ya no existe.")
        return d

    def _read(self, pid: str) -> dict:
        return json.loads((self._dir(pid) / "profile.json").read_text(encoding="utf-8"))

    def _write(self, d: Path, data: dict) -> None:
        tmp = d / "profile.json.tmp"
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, d / "profile.json")

    def _summary(self, d: Path, data: dict) -> dict:
        out = dict(data)
        out["type_label"] = TYPES.get(data.get("type"), data.get("type"))
        out["has_reference"] = (d / "reference.wav").exists()
        avatar = next((p for p in d.glob("avatar.*")), None)
        if avatar:
            mime = "image/png" if avatar.suffix == ".png" else "image/jpeg" if avatar.suffix in (".jpg", ".jpeg") else "image/webp"
            out["avatar"] = f"data:{mime};base64," + base64.b64encode(avatar.read_bytes()).decode()
        else:
            out["avatar"] = None
        return out

    # ------------------------------------------------------------- consultas
    def list(self) -> list[dict]:
        items = []
        with self._lock:
            for d in self.root.iterdir():
                f = d / "profile.json"
                if f.exists():
                    try:
                        items.append(self._summary(d, json.loads(f.read_text(encoding="utf-8"))))
                    except (OSError, ValueError):
                        continue
        items.sort(key=lambda p: (not p.get("favorite"), p.get("name", "").lower()))
        return items

    def get(self, pid: str) -> dict:
        with self._lock:
            return self._summary(self._dir(pid), self._read(pid))

    def path(self, pid: str) -> Path:
        return self._dir(pid)

    def folders(self) -> list[str]:
        return sorted({p.get("folder") for p in self.list() if p.get("folder")}, key=str.lower)

    # ------------------------------------------------------------ escritura
    def create(self, name: str, type_: str = "effects", description: str = "", folder: str = "",
               effects: dict | None = None, cloning: dict | None = None) -> dict:
        if type_ not in TYPES:
            raise ProfileError("Tipo de perfil desconocido.")
        pid = uuid.uuid4().hex
        d = self.root / pid
        with self._lock:
            d.mkdir(parents=True)
            data = {
                "id": pid, "name": _safe_name(name), "description": str(description or "")[:1000],
                "type": type_, "folder": str(folder or "")[:60], "favorite": False,
                "created": _now(), "updated": _now(),
                "effects": sanitize(effects or {}), "cloning": cloning or {}, "model": {},
            }
            self._write(d, data)
        return self.get(pid)

    def update(self, pid: str, patch: dict) -> dict:
        with self._lock:
            d = self._dir(pid)
            data = self._read(pid)
            for key, value in (patch or {}).items():
                if key == "name":
                    data["name"] = _safe_name(value)
                elif key == "description":
                    data["description"] = str(value or "")[:1000]
                elif key == "folder":
                    data["folder"] = str(value or "")[:60]
                elif key == "favorite":
                    data["favorite"] = bool(value)
                elif key == "effects":
                    data["effects"] = sanitize(value)
                elif key in ("cloning", "model"):
                    if not isinstance(value, dict):
                        raise ProfileError(f"Formato no válido para {key}.")
                    data[key] = value
                else:
                    raise ProfileError(f"Campo no editable: {key}")
            data["updated"] = _now()
            self._write(d, data)
        return self.get(pid)

    def duplicate(self, pid: str) -> dict:
        with self._lock:
            src = self._dir(pid)
            new = uuid.uuid4().hex
            shutil.copytree(src, self.root / new)
            data = json.loads((self.root / new / "profile.json").read_text(encoding="utf-8"))
            data.update({"id": new, "name": _safe_name(data["name"] + " (copia)"), "favorite": False,
                         "created": _now(), "updated": _now()})
            self._write(self.root / new, data)
        return self.get(new)

    def delete(self, pid: str) -> None:
        with self._lock:
            shutil.rmtree(self._dir(pid))

    def set_avatar(self, pid: str, data_url: str | None) -> dict:
        with self._lock:
            d = self._dir(pid)
            for old in d.glob("avatar.*"):
                old.unlink()
            if data_url:
                m = re.fullmatch(r"data:image/(png|jpeg|jpg|webp);base64,([A-Za-z0-9+/=\s]+)", data_url or "")
                if not m:
                    raise ProfileError("La imagen debe ser PNG, JPG o WEBP.")
                raw = base64.b64decode(m.group(2))
                if len(raw) > AVATAR_MAX:
                    raise ProfileError("La imagen supera 3 MB.")
                ext = {"jpeg": "jpg"}.get(m.group(1), m.group(1))
                (d / f"avatar.{ext}").write_bytes(raw)
            data = self._read(pid)
            data["updated"] = _now()
            self._write(d, data)
        return self.get(pid)

    # ---------------------------------------------- exportar / importar / copias
    def export(self, pid: str, dest: Path) -> Path:
        d = self._dir(pid)
        dest = Path(dest)
        if dest.suffix.lower() != EXT:
            dest.mkdir(parents=True, exist_ok=True)
        if dest.is_dir():
            name = re.sub(r'[<>:"/\\|?*]+', "_", self._read(pid)["name"])
            dest = dest / f"{name}{EXT}"
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            for f in d.rglob("*"):
                if f.is_file():
                    z.write(f, f.relative_to(d).as_posix())
        return dest

    def import_file(self, src: Path) -> dict:
        try:
            z = zipfile.ZipFile(src)
        except (OSError, zipfile.BadZipFile) as exc:
            raise ProfileError("El archivo no es un perfil de VoiceLab AI válido.") from exc
        with z:
            names = z.namelist()
            if "profile.json" not in names:
                raise ProfileError("El archivo no contiene un perfil de VoiceLab AI.")
            for n in names:
                if n.startswith("/") or ".." in Path(n).parts or ":" in n:
                    raise ProfileError("El archivo contiene rutas no permitidas.")
            meta = json.loads(z.read("profile.json").decode("utf-8"))
            pid = uuid.uuid4().hex
            d = self.root / pid
            with self._lock:
                d.mkdir()
                z.extractall(d)
                meta.update({"id": pid, "name": _safe_name(meta.get("name", "Perfil importado")),
                             "type": meta.get("type") if meta.get("type") in TYPES else "effects",
                             "effects": sanitize(meta.get("effects")), "updated": _now()})
                meta.setdefault("created", _now())
                self._write(d, meta)
        return self.get(pid)

    def backup(self, dest_dir: Path) -> Path:
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        out = dest_dir / time.strftime("VoiceLabAI-copia-%Y%m%d-%H%M%S.zip")
        with self._lock, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for f in self.root.rglob("*"):
                if f.is_file():
                    z.write(f, ("profiles/" + f.relative_to(self.root).as_posix()))
            settings = paths.settings_file()
            if settings.exists():
                z.write(settings, "settings.json")
        return out
