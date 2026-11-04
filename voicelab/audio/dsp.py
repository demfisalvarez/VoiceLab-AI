"""Bloques de procesamiento de señal usados por el motor en tiempo real.

Todos trabajan sobre bloques mono ``float32`` y están pensados para ejecutarse
en el hilo de audio: sin bloqueos, sin E/S y con poca memoria nueva por bloque.
"""

from __future__ import annotations

import math
import threading

import numpy as np

SILENCE_DB = -120.0


def db_to_lin(db: float) -> float:
    return 10.0 ** (db / 20.0)


def lin_to_db(x: float, floor: float = SILENCE_DB) -> float:
    if x <= 0.0:
        return floor
    return max(floor, 20.0 * math.log10(x))


class SmoothedGain:
    """Ganancia con rampa lineal entre bloques (evita chasquidos al mover un
    deslizador)."""

    def __init__(self, db: float = 0.0, muted: bool = False):
        self._target = 0.0 if muted else db_to_lin(db)
        self._current = self._target
        self._db = db
        self._muted = muted

    def set_db(self, db: float) -> None:
        self._db = float(db)
        if not self._muted:
            self._target = db_to_lin(self._db)

    def set_muted(self, muted: bool) -> None:
        self._muted = bool(muted)
        self._target = 0.0 if self._muted else db_to_lin(self._db)

    @property
    def db(self) -> float:
        return self._db

    def process(self, block: np.ndarray) -> np.ndarray:
        cur, tgt = self._current, self._target
        if cur == tgt:
            if tgt == 1.0:
                return block
            return block * np.float32(tgt)
        ramp = np.linspace(cur, tgt, block.shape[0], endpoint=False, dtype=np.float32)
        self._current = tgt
        return block * ramp


class NoiseGate:
    """Puerta de ruido con histéresis, ataque rápido y liberación suave.

    Se abre cuando el nivel RMS del bloque supera el umbral y se cierra cuando
    baja ``hysteresis_db`` por debajo durante más de ``hold_ms``.
    """

    def __init__(self, sample_rate: int, threshold_db: float = -50.0, enabled: bool = False,
                 attack_ms: float = 3.0, release_ms: float = 120.0, hold_ms: float = 80.0,
                 range_db: float = -80.0, hysteresis_db: float = 4.0):
        self.sample_rate = sample_rate
        self.enabled = enabled
        self.threshold_db = threshold_db
        self.attack_ms = attack_ms      # tiempo para abrirse del todo
        self.release_ms = release_ms    # tiempo para cerrarse del todo
        self.hold_ms = hold_ms
        self.range_db = range_db
        self.hysteresis_db = hysteresis_db
        self._gain_db = 0.0
        self._open = True
        self._hold_left = 0.0

    @property
    def is_open(self) -> bool:
        return self._open

    def _lin(self, db: float) -> float:
        return 0.0 if db <= self.range_db else db_to_lin(db)

    def process(self, block: np.ndarray) -> np.ndarray:
        if not self.enabled:
            self._gain_db, self._open = 0.0, True
            return block
        n = block.shape[0]
        if n == 0:
            return block
        rms = float(np.sqrt(np.mean(block * block)))
        level = lin_to_db(rms)
        block_ms = 1000.0 * n / self.sample_rate
        if level >= self.threshold_db:
            self._open = True
            self._hold_left = self.hold_ms
        elif level < self.threshold_db - self.hysteresis_db:
            if self._hold_left > 0:
                self._hold_left -= block_ms
            else:
                self._open = False
        # La ganancia se mueve en dB a velocidad constante: abrir tarda
        # attack_ms y cerrar release_ms, independientemente del bloque.
        target = 0.0 if self._open else self.range_db
        start = self._gain_db
        span = abs(self.range_db)
        if target > start:
            end = min(target, start + span * block_ms / max(self.attack_ms, 0.01))
        else:
            end = max(target, start - span * block_ms / max(self.release_ms, 0.01))
        self._gain_db = end
        if start == end == 0.0:
            return block
        g0, g1 = self._lin(start), self._lin(end)
        return block * np.linspace(g0, g1, n, endpoint=False, dtype=np.float32)


class SafetyLimiter:
    """Limitador de picos para proteger oídos y equipos.

    Ataque instantáneo por bloque, liberación exponencial y recorte final
    estricto al techo: la salida nunca supera ``ceiling_db``.
    """

    def __init__(self, sample_rate: int, ceiling_db: float = -1.0, release_ms: float = 150.0):
        self.sample_rate = sample_rate
        self.ceiling = db_to_lin(ceiling_db)
        self.release_ms = release_ms
        self._gain = 1.0
        self.active = False  # True si está reduciendo ganancia ahora mismo

    def process(self, block: np.ndarray) -> np.ndarray:
        n = block.shape[0]
        if n == 0:
            return block
        peak = float(np.max(np.abs(block)))
        needed = self.ceiling / peak if peak > self.ceiling else 1.0
        start = self._gain
        if needed < start:
            end = needed
        else:
            coef = 1.0 - math.exp(-n / (self.sample_rate * self.release_ms / 1000.0))
            end = start + (min(1.0, needed) - start) * coef
        self._gain = end
        self.active = end < 0.999
        if start == end == 1.0:
            out = block
        else:
            out = block * np.linspace(start, end, n, endpoint=False, dtype=np.float32)
        return np.clip(out, -self.ceiling, self.ceiling)


class LevelMeter:
    """Acumula pico y RMS entre lecturas de la interfaz.

    El hilo de audio llama a ``update`` en cada bloque; la interfaz llama a
    ``read`` unas 20 veces por segundo y recibe el máximo desde la última
    lectura, de modo que no se pierde ningún pico.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._peak = 0.0
        self._energy = 0.0
        self._count = 0
        self._clip = False
        self._last = (SILENCE_DB, SILENCE_DB, False)

    def update(self, block: np.ndarray) -> None:
        if block.shape[0] == 0:
            return
        peak = float(np.max(np.abs(block)))
        energy = float(np.dot(block, block))
        with self._lock:
            if peak > self._peak:
                self._peak = peak
            self._energy += energy
            self._count += block.shape[0]
            if peak >= 0.999:
                self._clip = True

    def read(self) -> dict:
        with self._lock:
            if self._count:
                rms = math.sqrt(self._energy / self._count)
                self._last = (lin_to_db(self._peak), lin_to_db(rms), self._clip)
            else:
                self._last = (SILENCE_DB, SILENCE_DB, False)
            self._peak = self._energy = 0.0
            self._count = 0
            self._clip = False
            peak_db, rms_db, clip = self._last
        return {"peak_db": round(peak_db, 1), "rms_db": round(rms_db, 1), "clip": clip}


def downmix(indata: np.ndarray, mode: str) -> np.ndarray:
    """Convierte la entrada (frames × canales) a mono según el modo elegido."""
    channels = indata.shape[1]
    if channels == 1:
        return indata[:, 0].copy()
    if mode == "left":
        return indata[:, 0].copy()
    if mode == "right":
        return indata[:, 1].copy()
    return indata.mean(axis=1, dtype=np.float32)


def make_test_tone(sample_rate: int, level_db: float = -14.0) -> np.ndarray:
    """Dos notas cortas (Mi5 → La5) con envolvente suave, ~0,6 s."""
    amp = db_to_lin(level_db)
    parts = []
    for freq, dur in ((659.25, 0.18), (880.0, 0.32)):
        n = int(sample_rate * dur)
        t = np.arange(n, dtype=np.float32) / sample_rate
        env = np.minimum(1.0, t / 0.01) * np.exp(-3.0 * t / dur)
        parts.append((amp * env * np.sin(2 * np.pi * freq * t)).astype(np.float32))
        parts.append(np.zeros(int(sample_rate * 0.03), dtype=np.float32))
    return np.concatenate(parts)
