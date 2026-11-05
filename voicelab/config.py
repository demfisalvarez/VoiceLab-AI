"""Ajustes persistentes con validación.

Los ajustes se guardan en JSON en la carpeta de datos del usuario. Cada valor
se valida y se limita a su rango, de modo que un archivo dañado o editado a
mano nunca pueda dejar el motor de audio en un estado imposible.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable

from . import paths
from .audio import effects

log = logging.getLogger(__name__)

SAMPLE_RATES = (44100, 48000)
BLOCK_SIZES = (64, 128, 256, 512, 1024)
CHANNEL_MODES = ("mix", "left", "right")
ROUTES = ("cable", "monitor", "aux")
PAGES = ("home", "modulator", "library", "clone", "create", "tts", "editor", "settings")


def _bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "si", "sí", "on")
    raise ValueError("no es booleano")


def _float_range(lo: float, hi: float) -> Callable[[Any], float]:
    def conv(v: Any) -> float:
        f = float(v)
        if f != f:  # NaN
            raise ValueError("NaN")
        return max(lo, min(hi, f))
    return conv


def _int_range(lo: int, hi: int) -> Callable[[Any], int]:
    def conv(v: Any) -> int:
        return max(lo, min(hi, int(round(float(v)))))
    return conv


def _choice(options: tuple) -> Callable[[Any], Any]:
    def conv(v: Any) -> Any:
        if isinstance(options[0], int):
            v = int(v)
        if v not in options:
            raise ValueError(f"valor no permitido: {v!r}")
        return v
    return conv


def _opt_str(v: Any) -> str | None:
    if v is None or v == "":
        return None
    if not isinstance(v, str):
        raise ValueError("no es texto")
    return v[:300]


# Esquema: sección -> clave -> (valor por defecto, conversor/validador)
SCHEMA: dict[str, dict[str, tuple[Any, Callable[[Any], Any]]]] = {
    "audio": {
        "hostapi": (None, _opt_str),
        "input_device": (None, _opt_str),
        "input_channel_mode": ("mix", _choice(CHANNEL_MODES)),
        "input_gain_db": (0.0, _float_range(-24.0, 24.0)),
        "gate_enabled": (False, _bool),
        "gate_threshold_db": (-50.0, _float_range(-80.0, 0.0)),
        "cable_device": (None, _opt_str),
        "cable_enabled": (True, _bool),
        "system_mic": (True, _bool),      # el cable como micrófono predeterminado de Windows mientras se modula
        "cable_volume_db": (0.0, _float_range(-60.0, 12.0)),
        "monitor_device": (None, _opt_str),
        "monitor_enabled": (False, _bool),
        "monitor_volume_db": (-6.0, _float_range(-60.0, 12.0)),
        "aux_device": (None, _opt_str),
        "aux_enabled": (False, _bool),
        "aux_volume_db": (0.0, _float_range(-60.0, 12.0)),
        "sample_rate": (48000, _choice(SAMPLE_RATES)),
        "block_size": (256, _choice(BLOCK_SIZES)),
        "buffer_blocks": (2, _int_range(1, 6)),
        "monitor_source": ("processed", _choice(("processed", "original"))),
    },
    "voice": {
        "params": (effects.default_params(), effects.sanitize),
        "profile_id": (None, _opt_str),
        "preset": (None, _opt_str),
        "rvc_pitch": (0.0, _float_range(-24.0, 24.0)),
        "rvc_block": (0.3, _float_range(0.1, 1.0)),
        "instant_live": (True, _bool),          # voz instantánea en directo (MeanVC2)
        "ai_polish": (True, _bool),             # acabado de estudio a la salida de la IA
        "ai_clean_input": (True, _bool),        # limpieza de la voz antes de la IA
    },
    "ai": {
        "tts_model": ("chatterbox-v2", _choice(("chatterbox-v2",))),
        "tts_language": ("es", _opt_str),
        "meanvc_variant": ("120ms", _choice(("120ms", "40ms"))),
        "meanvc_hd": (False, _bool),                          # salida a 48 kHz con AP-BWE (si está descargado)
        "tts_device": ("cpu", _choice(("cpu", "gpu"))),     # la CPU es lo fiable; la GPU, opcional
        "rvc_device": ("gpu", _choice(("cpu", "gpu"))),
    },
    "ui": {
        "last_page": ("home", _choice(PAGES)),
        "monitor_warning_ack": (False, _bool),
        "updates_url": ("", lambda v: "" if not v else (str(v)[:300] if str(v).startswith("https://") else (_ for _ in ()).throw(ValueError("https")))),
    },
}


def defaults() -> dict[str, dict[str, Any]]:
    return {sec: {k: copy.deepcopy(d) for k, (d, _) in keys.items()} for sec, keys in SCHEMA.items()}


class SettingsError(ValueError):
    pass


class Settings:
    """Ajustes en memoria + persistencia atómica en disco."""

    def __init__(self, path: Path | None = None):
        self.path = path or paths.settings_file()
        self._lock = threading.RLock()
        self._data = defaults()
        self.load()

    # ------------------------------------------------------------------ disco
    def load(self) -> None:
        with self._lock:
            self._data = defaults()
            if not self.path.exists():
                return
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception as exc:  # archivo dañado: se conserva una copia
                log.warning("Ajustes ilegibles (%s); se usan los valores por defecto", exc)
                try:
                    self.path.replace(self.path.with_suffix(".json.bak"))
                except OSError:
                    pass
                return
            # Se aplican uno a uno ignorando valores no válidos.
            for sec, keys in SCHEMA.items():
                for key, (_, conv) in keys.items():
                    if isinstance(raw.get(sec), dict) and key in raw[sec]:
                        try:
                            self._data[sec][key] = conv(raw[sec][key])
                        except Exception:
                            log.warning("Ajuste no válido ignorado: %s.%s", sec, key)

    def save(self) -> None:
        with self._lock:
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)

    # ---------------------------------------------------------------- acceso
    def snapshot(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self._data)

    def get(self, section: str, key: str) -> Any:
        with self._lock:
            return self._data[section][key]

    def audio(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._data["audio"])

    def update(self, patch: dict[str, Any], save: bool = True) -> dict[str, dict[str, Any]]:
        """Aplica un parche {sección: {clave: valor}}.

        Devuelve solo los valores que han cambiado realmente. Si algún valor
        no es válido se lanza SettingsError y no se aplica nada.
        """
        if not isinstance(patch, dict):
            raise SettingsError("Formato de ajustes no válido")
        validated: dict[str, dict[str, Any]] = {}
        for sec, values in patch.items():
            if sec not in SCHEMA or not isinstance(values, dict):
                raise SettingsError(f"Sección de ajustes desconocida: {sec}")
            for key, value in values.items():
                if key not in SCHEMA[sec]:
                    raise SettingsError(f"Ajuste desconocido: {sec}.{key}")
                try:
                    validated.setdefault(sec, {})[key] = SCHEMA[sec][key][1](value)
                except Exception as exc:
                    raise SettingsError(f"Valor no válido para {sec}.{key}: {value!r}") from exc
        changed: dict[str, dict[str, Any]] = {}
        with self._lock:
            for sec, values in validated.items():
                for key, value in values.items():
                    if self._data[sec][key] != value:
                        self._data[sec][key] = value
                        changed.setdefault(sec, {})[key] = value
            if changed and save:
                self.save()
        return changed
