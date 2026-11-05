"""«En todas las apps»: el micrófono virtual como micrófono predeterminado de Windows.

Mientras el modulador está encendido con la ruta del micrófono virtual, Windows
usa «CABLE Output» como micrófono predeterminado (consola, multimedia y
comunicaciones). Así lo reciben los juegos, los editores de vídeo y cualquier
programa que use «el micrófono predeterminado», sin configurar nada en cada uno.

Al parar el modulador, al desactivar la opción o al cerrar la app, se restaura el
micrófono que había. Lo anterior se guarda en un archivo: si la app se cerrase de
golpe, se restaura al volver a abrirla.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from .. import paths

log = logging.getLogger(__name__)


def _is_cable_capture(name: str) -> bool:
    low = name.lower()
    return ("cable" in low and "output" in low) or "vb-audio virtual cable" in low


def _common_prefix(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a.lower(), b.lower()):
        if x != y:
            break
        n += 1
    return n


class SystemMic:
    def __init__(self, backend=None, state_file: Path | None = None):
        if backend is None:
            from . import winmic as backend
        self.b = backend
        self.state_file = state_file or (paths.data_dir() / "microfono_predeterminado.json")
        self._lock = threading.Lock()
        self.engaged = False
        self.device: str | None = None
        self.error: str | None = None

    @property
    def supported(self) -> bool:
        return bool(self.b.available())

    def status(self) -> dict:
        return {"supported": self.supported, "engaged": self.engaged, "device": self.device, "error": self.error}

    def find_cable(self, playback_name: str | None = None) -> dict | None:
        """El lado «micrófono» del cable en el que escribe VoiceLab (p. ej. CABLE Input → CABLE Output)."""
        caps = [d for d in self.b.capture_devices() if _is_cable_capture(d["name"])]
        if not caps:
            return None
        if playback_name:
            want = playback_name.replace("Input", "Output").replace("input", "output")
            caps.sort(key=lambda d: _common_prefix(d["name"], want), reverse=True)
        return caps[0]

    def engage(self, playback_name: str | None = None) -> dict:
        """Pone el micrófono virtual como predeterminado (guardando el que había)."""
        with self._lock:
            if not self.supported:
                self.error = None
                return self.status()
            try:
                cable = self.find_cable(playback_name)
                if cable is None:
                    raise RuntimeError("No se encontró «CABLE Output» entre los micrófonos de Windows.")
                if not self.state_file.exists():               # lo original solo se guarda una vez
                    prev = {str(r): self.b.default_capture(r) for r in (0, 1, 2)}
                    if any(v == cable["id"] for v in prev.values()):
                        # Ya estaba puesto (p. ej. tras un cierre inesperado): no se guarda el cable como «original».
                        prev = {k: (None if v == cable["id"] else v) for k, v in prev.items()}
                    self.state_file.write_text(json.dumps({"previous": prev, "cable": cable["id"]}), encoding="utf-8")
                self.b.set_default_capture(cable["id"])
                self.engaged, self.device, self.error = True, cable["name"], None
                log.info("Micrófono predeterminado de Windows: %s (se restaura al parar)", cable["name"])
            except Exception as exc:  # noqa: BLE001
                self.error = f"No se pudo poner el micrófono virtual como predeterminado: {exc}"
                log.warning(self.error)
            return self.status()

    def release(self) -> dict:
        """Restaura el micrófono predeterminado que había antes."""
        with self._lock:
            self.engaged, self.device = False, None
            if not self.supported or not self.state_file.exists():
                return self.status()
            try:
                saved = json.loads(self.state_file.read_text(encoding="utf-8"))
                ids = {d["id"] for d in self.b.capture_devices()}
                prev = saved.get("previous") or {}
                for role in (0, 1, 2):
                    dev = prev.get(str(role))
                    if dev and dev in ids:
                        self.b.set_default_capture(dev, roles=(role,))
                log.info("Micrófono predeterminado de Windows restaurado")
                self.error = None
            except Exception as exc:  # noqa: BLE001
                self.error = f"No se pudo restaurar el micrófono predeterminado: {exc}"
                log.warning(self.error)
            finally:
                try:
                    self.state_file.unlink()
                except OSError:
                    pass
            return self.status()
