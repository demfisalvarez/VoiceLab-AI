"""Espacio de trabajo de audio: archivos importados, grabaciones y ediciones.

Cada elemento se guarda como float32 mono a 48 kHz (``.npy``) con sus
metadatos y hasta 8 versiones anteriores para deshacer. Las operaciones
largas se ejecutan como tareas en segundo plano con progreso.
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Callable

import numpy as np

from . import paths
from .audio import analysis, effects, mediaio

log = logging.getLogger(__name__)
SR = 48000
UNDO_LEVELS = 8


class WorkspaceError(ValueError):
    pass


# =================================================================== tareas
class Jobs:
    def __init__(self):
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def run(self, label: str, fn: Callable[[Callable[[float], None]], object]) -> str:
        jid = uuid.uuid4().hex[:12]
        job = {"id": jid, "label": label, "state": "running", "progress": 0.0, "result": None, "error": None,
               "started": time.time()}
        with self._lock:
            self._jobs[jid] = job

        class Progress:
            """``progress(0.5)`` fija el avance; ``progress.stage("…")`` el detalle que ve el usuario."""

            def __call__(self, p: float) -> None:
                job["progress"] = round(max(0.0, min(1.0, float(p))), 3)

            @staticmethod
            def stage(text: str) -> None:
                job["detail"] = str(text)[:160]

        def target():
            t0 = time.time()
            try:
                job["result"] = fn(Progress())
                job["progress"] = 1.0
                job["state"] = "done"
                log.info("Tarea «%s» terminada en %.1f s", label, time.time() - t0)
            except (WorkspaceError, mediaio.MediaError, ValueError) as exc:
                log.warning("Tarea «%s»: %s", label, exc)
                job["error"], job["state"] = str(exc), "error"
            except RuntimeError as exc:          # errores de la app, ya redactados para el usuario
                log.warning("Tarea «%s» fallida:\n%s", label, traceback.format_exc())
                job["error"], job["state"] = str(exc) or type(exc).__name__, "error"
                job["cancelled"] = bool(getattr(exc, "cancelled", False))
            except Exception as exc:  # pragma: no cover
                log.error("Tarea «%s» fallida:\n%s", label, traceback.format_exc())
                job["error"], job["state"] = f"Error inesperado: {exc}", "error"

        threading.Thread(target=target, name=f"tarea-{label}", daemon=True).start()
        return jid

    def get(self, jid: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(jid)
            return dict(job) if job else None


# ============================================================ elementos
class Workspace:
    def __init__(self, root: Path | None = None):
        self.root = root or (paths.data_dir() / "work")
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _meta_path(self, iid: str) -> Path:
        if not iid or not all(c in "0123456789abcdef" for c in iid) or len(iid) != 32:
            raise WorkspaceError("Elemento no válido.")
        return self.root / f"{iid}.json"

    def _audio_path(self, iid: str, version: int = 0) -> Path:
        return self.root / (f"{iid}.npy" if version == 0 else f"{iid}.v{version}.npy")

    def meta(self, iid: str) -> dict:
        p = self._meta_path(iid)
        if not p.exists():
            raise WorkspaceError("Ese audio ya no existe.")
        return json.loads(p.read_text(encoding="utf-8"))

    def _write_meta(self, meta: dict) -> None:
        self._meta_path(meta["id"]).write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    def list(self) -> list[dict]:
        items = []
        for f in self.root.glob("*.json"):
            try:
                items.append(json.loads(f.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return sorted(items, key=lambda m: m.get("created", ""), reverse=True)

    def create(self, audio: np.ndarray, name: str, kind: str, source: str | None = None) -> dict:
        iid = uuid.uuid4().hex
        with self._lock:
            np.save(self._audio_path(iid), audio.astype(np.float32))
            meta = {"id": iid, "name": (name or "Audio")[:120], "kind": kind, "source": source,
                    "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "sr": SR,
                    "duration": round(audio.shape[0] / SR, 3), "undo": 0}
            self._write_meta(meta)
        return meta

    def load(self, iid: str) -> np.ndarray:
        self.meta(iid)
        return np.load(self._audio_path(iid))

    def save(self, iid: str, audio: np.ndarray) -> dict:
        with self._lock:
            meta = self.meta(iid)
            for v in range(UNDO_LEVELS - 1, 0, -1):     # desplaza el historial
                src = self._audio_path(iid, v)
                if src.exists():
                    src.replace(self._audio_path(iid, v + 1))
            shutil.copyfile(self._audio_path(iid), self._audio_path(iid, 1))
            self._audio_path(iid, UNDO_LEVELS + 1).unlink(missing_ok=True)
            np.save(self._audio_path(iid), audio.astype(np.float32))
            meta["duration"] = round(audio.shape[0] / SR, 3)
            meta["undo"] = min(UNDO_LEVELS, meta.get("undo", 0) + 1)
            self._write_meta(meta)
        return meta

    def undo(self, iid: str) -> dict:
        with self._lock:
            meta = self.meta(iid)
            if not meta.get("undo") or not self._audio_path(iid, 1).exists():
                raise WorkspaceError("No hay nada que deshacer.")
            self._audio_path(iid, 1).replace(self._audio_path(iid))
            for v in range(2, UNDO_LEVELS + 1):
                if self._audio_path(iid, v).exists():
                    self._audio_path(iid, v).replace(self._audio_path(iid, v - 1))
            meta["undo"] -= 1
            meta["duration"] = round(np.load(self._audio_path(iid), mmap_mode="r").shape[0] / SR, 3)
            self._write_meta(meta)
        return meta

    def rename(self, iid: str, name: str) -> dict:
        with self._lock:
            meta = self.meta(iid)
            meta["name"] = (name or meta["name"]).strip()[:120]
            self._write_meta(meta)
        return meta

    def delete(self, iid: str) -> None:
        with self._lock:
            self._meta_path(iid).unlink(missing_ok=True)
            for f in self.root.glob(f"{iid}*.npy"):
                f.unlink()

    # ------------------------------------------------------------ edición
    @staticmethod
    def span(audio: np.ndarray, a: float | None, b: float | None) -> tuple[int, int]:
        n = audio.shape[0]
        i = 0 if a is None else int(max(0.0, float(a)) * SR)
        j = n if b is None else int(max(0.0, float(b)) * SR)
        i, j = min(i, n), min(j, n)
        if j < i:
            i, j = j, i
        return i, j

    def apply(self, iid: str, op: str, args: dict, progress: Callable[[float], None]) -> dict:
        x = self.load(iid)
        a, b = args.get("start"), args.get("end")
        i, j = self.span(x, a, b)
        sel = (i, j) if (a is not None and b is not None and j - i > 0) else (0, x.shape[0])
        i, j = sel
        progress(0.1)
        if op == "crop":
            y = x[i:j]
        elif op == "delete":
            y = np.concatenate([x[:i], x[j:]])
        elif op == "silence":
            y = x.copy(); y[i:j] = 0
        elif op == "gain":
            y = x.copy(); y[i:j] *= 10 ** (float(args.get("db", 0)) / 20)
        elif op == "normalize":
            y = x.copy(); y[i:j] = analysis.normalize(x[i:j], float(args.get("peak_db", -1)))
        elif op == "fade_in":
            y = x.copy(); y[i:j] *= np.linspace(0, 1, j - i, dtype=np.float32)
        elif op == "fade_out":
            y = x.copy(); y[i:j] *= np.linspace(1, 0, j - i, dtype=np.float32)
        elif op == "remove_silences":
            y = np.concatenate([x[:i], analysis.remove_silences(x[i:j], SR), x[j:]])
        elif op == "denoise":
            y = x.copy(); y[i:j] = analysis.denoise(x[i:j], SR, float(args.get("strength", 0.6)))
        elif op == "effects":
            part = effects.process_offline(x[i:j], SR, args.get("params") or {})
            y = np.concatenate([x[:i], part[: j - i] if not args.get("keep_tail") else part, x[j:]])
        elif op in ("speed", "tempo"):
            rate = float(args.get("rate", 1.0))
            if not 0.25 <= rate <= 4:
                raise WorkspaceError("Velocidad fuera de rango.")
            fn = effects.change_speed if op == "speed" else effects.time_stretch
            y = np.concatenate([x[:i], fn(x[i:j], rate), x[j:]])
        else:
            raise WorkspaceError(f"Operación desconocida: {op}")
        progress(0.9)
        if y.size == 0:
            raise WorkspaceError("La operación dejaría el audio vacío.")
        y = np.clip(y, -1.0, 1.0).astype(np.float32)
        return self.save(iid, y)

    def split(self, iid: str, at: float) -> dict:
        x = self.load(iid)
        k = int(float(at) * SR)
        if not 0 < k < x.shape[0]:
            raise WorkspaceError("Coloca el cursor dentro del audio para dividirlo.")
        meta = self.meta(iid)
        second = self.create(x[k:], meta["name"] + " (parte 2)", "edit", iid)
        self.save(iid, x[:k])
        self.rename(iid, meta["name"] + " (parte 1)")
        return second

    def join(self, ids: list[str], name: str | None = None) -> dict:
        if len(ids) < 2:
            raise WorkspaceError("Elige al menos dos audios para unirlos.")
        parts = [self.load(i) for i in ids]
        gap = np.zeros(int(0.15 * SR), np.float32)
        out = parts[0]
        for p in parts[1:]:
            out = np.concatenate([out, gap, p])
        return self.create(out, name or "Audio unido", "edit")


# =============================================================== reproductor
class Player:
    def __init__(self, sd):
        self.sd = sd
        self._stream = None
        self._audio = None
        self._pos = 0
        self._offset = 0.0
        self._lock = threading.Lock()

    def play(self, audio: np.ndarray, device_index: int | None, channels: int = 2, offset: float = 0.0) -> None:
        self.stop()
        if self.sd is None:
            raise WorkspaceError("El sistema de audio no está disponible.")
        self._audio, self._pos, self._offset = audio.astype(np.float32), 0, offset
        done = threading.Event()

        def cb(outdata, frames, t, status):
            chunk = self._audio[self._pos:self._pos + frames]
            n = chunk.shape[0]
            outdata[:n] = chunk[:, None]
            outdata[n:] = 0
            self._pos += n
            if n < frames:
                raise self.sd.CallbackStop

        with self._lock:
            self._stream = self.sd.OutputStream(device=device_index, samplerate=SR, channels=channels,
                                                dtype="float32", callback=cb, finished_callback=done.set)
            self._stream.start()

    def stop(self) -> None:
        with self._lock:
            s, self._stream = self._stream, None
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:
                pass

    def status(self) -> dict:
        s = self._stream
        playing = bool(s is not None and s.active)
        return {"playing": playing, "position": round(self._offset + self._pos / SR, 3) if self._audio is not None else 0.0}


# =================================================================== grabador
class Recorder:
    MAX_SECONDS = 2 * 3600

    def __init__(self, sd):
        self.sd = sd
        self._stream = None
        self._chunks: list[np.ndarray] = []
        self._count = 0
        self._peak = 0.0
        self.started = None

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def start(self, device_index: int | None, channels: int = 1, extra=None) -> None:
        if self.recording:
            return
        if self.sd is None:
            raise WorkspaceError("El sistema de audio no está disponible.")
        self._chunks, self._count, self._peak = [], 0, 0.0

        def cb(indata, frames, t, status):
            mono = indata.mean(axis=1) if indata.shape[1] > 1 else indata[:, 0].copy()
            if self._count < self.MAX_SECONDS * SR:
                self._chunks.append(mono.astype(np.float32))
                self._count += frames
            p = float(np.max(np.abs(mono))) if frames else 0.0
            self._peak = max(self._peak * 0.85, p)

        self._stream = self.sd.InputStream(device=device_index, samplerate=SR, channels=channels, dtype="float32",
                                           callback=cb, extra_settings=extra)
        self._stream.start()
        self.started = time.time()

    def stop(self) -> np.ndarray:
        s, self._stream = self._stream, None
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:
                pass
        audio = np.concatenate(self._chunks) if self._chunks else np.zeros(0, np.float32)
        self._chunks = []
        return audio

    def status(self) -> dict:
        from .audio.dsp import lin_to_db
        return {"recording": self.recording, "seconds": round(self._count / SR, 2),
                "peak_db": round(lin_to_db(self._peak), 1)}
