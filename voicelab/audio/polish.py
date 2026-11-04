"""Acabado «de estudio» para las voces de IA en directo.

Las voces de los servicios comerciales suenan pulidas porque, además del modelo, pasan por una cadena
de producción: voz limpia a la entrada y, a la salida, control de sibilantes, compresión suave,
ecualización de presencia y un nivel constante. Esta envoltura hace lo mismo alrededor del procesador
de IA (RVC o voz instantánea) sin cambiar su interfaz:

    entrada → [limpieza: paso alto + reducción de ruido suave] → IA → [de-esser → compresor →
    EQ de presencia y aire → nivel automático → limitador] → salida

Todo es DSP clásico, barato y sin latencia apreciable (salvo la reducción de ruido, ~21 ms).
"""

from __future__ import annotations

import math

import numpy as np

from .dsp import SafetyLimiter, db_to_lin, lin_to_db
from .effects import FilterBank, VoiceChain, _biquad


class DeEsser:
    """Atenúa las «eses» agudas: banda 5–10 kHz con ganancia dinámica (separación en dos bandas)."""

    def __init__(self, sr: int, threshold_db: float = -30.0, max_cut_db: float = 8.0, split_hz: float = 5000.0):
        self.sr = sr
        # Cruce Linkwitz-Riley de 4.º orden: graves + agudos suman plano (sin realces ni huecos).
        self.hp, self.lp = FilterBank(), FilterBank()
        self.hp.set([_biquad("hp", split_hz, sr, q=0.707), _biquad("hp", split_hz, sr, q=0.707)])
        self.lp.set([_biquad("lp", split_hz, sr, q=0.707), _biquad("lp", split_hz, sr, q=0.707)])
        self.threshold, self.max_cut = threshold_db, max_cut_db
        self.env = -120.0
        self.att = math.exp(-1.0 / (sr * 0.002 / 32))
        self.rel = math.exp(-1.0 / (sr * 0.060 / 32))
        self.gain = 1.0

    def process(self, x: np.ndarray) -> np.ndarray:
        hi = self.hp.process(x)
        lo = self.lp.process(x)
        n, sub = x.shape[0], 32
        g = np.empty((n + sub - 1) // sub, np.float32)
        for i in range(g.size):
            seg_h = hi[i * sub:(i + 1) * sub]
            seg_a = x[i * sub:(i + 1) * sub]
            lh = lin_to_db(float(np.sqrt(np.mean(seg_h ** 2))) if seg_h.size else 0.0)
            la = lin_to_db(float(np.sqrt(np.mean(seg_a ** 2))) if seg_a.size else 0.0)
            # Solo actúa si la banda alta domina (sibilante), no en voz normal brillante.
            lvl = lh if lh > la - 6.0 else -120.0
            c = self.att if lvl > self.env else self.rel
            self.env = c * self.env + (1 - c) * lvl
            cut = min(self.max_cut, max(0.0, self.env - self.threshold) * 0.6)
            g[i] = db_to_lin(-cut)
        gains = np.repeat(g, sub)[:n]
        return (lo + hi * gains).astype(np.float32)


class AutoLevel:
    """Nivel automático lento (AGC): lleva la voz a un nivel constante sin subir el silencio."""

    def __init__(self, sr: int, target_db: float = -20.0, max_gain_db: float = 12.0, min_gain_db: float = -12.0,
                 gate_db: float = -50.0):
        self.sr = sr
        self.target, self.max_gain, self.min_gain, self.gate = target_db, max_gain_db, min_gain_db, gate_db
        self.level = target_db
        self.gain_db = 0.0
        self._g = 1.0

    def process(self, x: np.ndarray) -> np.ndarray:
        n = x.shape[0]
        if n == 0:
            return x
        rms = lin_to_db(float(np.sqrt(np.mean(x ** 2))))
        if rms > self.gate:                                  # solo aprende con voz, no con silencio
            tau = 0.4 if rms > self.level else 2.0           # baja rápido, sube despacio
            a = 1.0 - math.exp(-n / (self.sr * tau))
            self.level += (rms - self.level) * a
        want = min(self.max_gain, max(self.min_gain, self.target - self.level))
        a = 1.0 - math.exp(-n / (self.sr * 0.25))
        self.gain_db += (want - self.gain_db) * a
        g1 = db_to_lin(self.gain_db)
        out = x * np.linspace(self._g, g1, n, endpoint=False, dtype=np.float32)
        self._g = g1
        return out


class Polish:
    """Cadena de salida: de-esser, compresor, presencia/aire, nivel automático y limitador."""

    def __init__(self, sr: int, air: bool = False):
        self.sr = sr
        self.deesser = DeEsser(sr)
        self.chain = VoiceChain(sr, {"comp_enabled": True, "comp_threshold": -22.0, "comp_ratio": 2.5,
                                     "comp_makeup": 2.0, "hpf_enabled": True, "hpf_hz": 70.0})
        sections = [_biquad("peak", 180.0, sr, -1.5, 0.9),             # menos «barro»
                    _biquad("peak", 3500.0, sr, 2.0, 0.8)]             # presencia
        if air and sr >= 32000:
            sections.append(_biquad("highshelf", 10000.0, sr, 2.0, 0.7))  # aire (con banda completa)
        self.eq = FilterBank()
        self.eq.set(sections)
        self.level = AutoLevel(sr)
        self.limiter = SafetyLimiter(sr, ceiling_db=-1.0, release_ms=80.0)

    @property
    def latency_samples(self) -> int:
        return self.chain.latency_samples

    def process(self, x: np.ndarray) -> np.ndarray:
        y = self.deesser.process(x)
        y = self.chain.process(y)
        y = self.eq.process(y)
        y = self.level.process(y)
        return self.limiter.process(y)


class InputCleaner:
    """Voz más limpia para el modelo: paso alto y reducción de ruido suave."""

    def __init__(self, sr: int, noise_reduction: float = 30.0):
        self.chain = VoiceChain(sr, {"hpf_enabled": True, "hpf_hz": 80.0, "noise_reduction": noise_reduction})

    @property
    def latency_samples(self) -> int:
        return self.chain.latency_samples

    def process(self, x: np.ndarray) -> np.ndarray:
        return self.chain.process(x)


class PolishedAI:
    """Envuelve un procesador de IA con limpieza de entrada y acabado de estudio.

    Mantiene la interfaz del procesador original (atributos y métodos se reenvían).
    """

    def __init__(self, inner, sr: int, clean_input: bool = True, polish: bool = True, air: bool = False):
        self.inner = inner
        self.sr = sr
        self.clean = InputCleaner(sr) if clean_input else None
        self.post = Polish(sr, air=air) if polish else None

    def __getattr__(self, name):
        return getattr(self.__dict__["inner"], name)

    @property
    def latency_samples(self) -> int:
        extra = (self.clean.latency_samples if self.clean else 0) + (self.post.latency_samples if self.post else 0)
        return int(self.inner.latency_samples) + extra

    def process(self, x: np.ndarray) -> np.ndarray:
        if self.clean is not None:
            x = self.clean.process(x)
        y = self.inner.process(x)
        if self.post is not None:
            y = self.post.process(y)
        return y

    def close(self) -> None:
        self.inner.close()
