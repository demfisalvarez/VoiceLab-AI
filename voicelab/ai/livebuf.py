"""Cola de salida adaptativa para la voz de IA en directo (voz instantánea y RVC).

La conversión trabaja por bloques en otro hilo y entrega el audio a ráfagas; el
hilo de audio lo reproduce de forma continua. Esta cola:

* arranca justo en el retraso necesario (lo que pide el modelo + un margen),
  poniendo delante el silencio que falte, así no hay cortes ni retraso de más;
* si la conversión se retrasa, el hueco se rellena con silencio y fundidos, y se
  sube el margen; si sobra margen, se recorta en los silencios entre palabras
  (no se nota) y, si falta, se alarga un silencio;
* mide el retraso real: lo que ha entrado y aún no ha salido.
"""

from __future__ import annotations

from typing import Callable

import numpy as np

from ..audio.ringbuffer import RingBuffer

FADE = 64                                                   # muestras de fundido en los huecos


class LiveOutput:
    MARGIN_S = 0.03
    MARGIN_MIN_S = 0.015
    MARGIN_MAX_S = 0.25

    def __init__(self, sr: int, need: Callable[[], float], block: int, margin_s: float | None = None,
                 window_s: float = 3.0):
        """``need()``: retraso que pide la conversión (muestras), sin el margen. ``block``: tamaño
        de las ráfagas (para el tope de seguridad)."""
        self.sr, self.need, self.block, self.window_s = int(sr), need, int(block), window_s
        self._mmin = int(self.MARGIN_MIN_S * self.sr)
        self._mmax = int(self.MARGIN_MAX_S * self.sr)
        self.margin = max(self._mmin, int((self.MARGIN_S if margin_s is None else margin_s) * self.sr))
        self.q = RingBuffer(self.sr * 10)
        self.underruns = 0
        self.dropped = 0                                    # entrada descartada (la CPU iba por detrás)
        self.trimmed = 0                                    # salida sobrante quitada en silencios
        self.skipped = 0                                    # entrada que no se convierte a propósito
        self.lost = 0                                       # lo que se tiró al reiniciar la conversión
        self.in_total = 0
        self.out_real = 0
        self._priming = True
        self._lead = 0
        self._fade_in = False
        self._loud = 0.0
        self._trim = 0
        self._pad = 0
        self._was_quiet = True
        self._win_n = 0
        self._win_min: int | None = None
        self._win_under = 0
        self._calm = 0
        self._lat: float | None = None
        self._tmp = np.zeros(self.sr, np.float32)
        self._ramp = np.linspace(0.0, 1.0, FADE, dtype=np.float32)

    # -- información
    def target(self) -> float:
        return float(self.need()) + self.margin

    @property
    def latency_samples(self) -> int:
        return int(self._lat if self._lat is not None else self.target())

    def in_flight(self) -> int:
        return int(self.in_total - self.dropped - self.skipped - self.trimmed - self.lost - self.out_real)

    def forget(self, pending_input: int) -> None:
        """La conversión se reinició: lo que tenía dentro no saldrá (no es retraso)."""
        self.lost += max(0, self.in_flight() - self.q.available() - int(pending_input))

    # -- hilo de conversión
    def write(self, y: np.ndarray) -> None:
        if y.shape[0]:
            self.q.write(y)

    # -- hilo de audio
    def read(self, n: int) -> np.ndarray:
        """Llamar una vez por bloque del motor, después de anotar la entrada en ``in_total``."""
        if self._tmp.shape[0] < 4 * n:
            self._tmp = np.zeros(8 * n, np.float32)
        out = np.zeros(n, np.float32)
        avail = self.q.available()
        if self._priming:
            if avail == 0:
                return out
            self._priming = False
            self._lead = max(0, int(self.target()) - self.in_flight())
        pos = 0
        if self._lead:
            pos = min(self._lead, n)
            self._lead -= pos
        want = n - pos
        if avail > self.margin + 2 * self.block + n:        # tope: un atasco largo no deja el retraso alto
            self.trimmed += self.q.skip(avail - (self.margin + self.block + n))
        elif self._trim and want:
            self._trim_quiet(want)
        elif self._pad and want and self._quiet_ahead(want):
            k = min(self._pad, want)                        # falta margen: se alarga un silencio
            self._pad -= k
            pos += k
            want -= k
        got = self.q.read_into(self._tmp, want) if want else 0
        if got:
            seg = self._tmp[:got]
            if self._fade_in:
                k = min(got, FADE)
                seg[:k] *= self._ramp[:k]
                self._fade_in = False
            out[pos:pos + got] = seg
            self.out_real += got
            peak = float(np.max(np.abs(seg)))
            self._loud = max(peak, self._loud * 0.999)
            self._was_quiet = peak < max(0.003, 0.05 * self._loud)
        if got < want:                                      # la conversión no llegó: hueco con fundidos
            if got:
                k = min(got, FADE)
                out[pos + got - k:pos + got] *= self._ramp[:k][::-1]
            if not self._fade_in:                           # un hueco cuenta una vez, dure lo que dure
                self.underruns += 1
                self._win_under += 1
            self._fade_in = True
        self._lat = float(self.in_flight())
        level = self.q.available()
        self._win_min = level if self._win_min is None else min(self._win_min, level)
        self._win_n += n
        if self._win_n >= self.window_s * self.sr:
            self._adapt()
        return out

    def _quiet_ahead(self, n: int) -> bool:
        """¿Lo próximo que va a sonar (y lo último que sonó) es silencio?"""
        if not self._was_quiet:
            return False
        got = self.q.peek_into(self._tmp, n)
        return got == n and float(np.max(np.abs(self._tmp[:got]))) < max(0.003, 0.05 * self._loud)

    def _trim_quiet(self, want: int) -> None:
        k = min(self._trim, want, self.q.available() - want)
        if k > 0 and self._quiet_ahead(k + want):
            self.trimmed += self.q.skip(k)
            self._trim -= k

    def _adapt(self) -> None:
        if self._win_under:                                 # hubo huecos: más margen
            self.margin = min(self._mmax, self.margin + int(0.02 * self.sr))
            self._calm = 0
            self._trim = self._pad = 0
        else:
            self._calm += 1
            if self._calm * self.window_s >= 30:            # 30 s sin huecos: probar con algo menos
                self.margin = max(self._mmin, self.margin - int(0.005 * self.sr))
                self._calm = 0
            level = self._win_min or 0
            self._trim = level - self.margin if level - self.margin > int(0.01 * self.sr) else 0
            self._pad = self.margin - level if self.margin - level > int(0.005 * self.sr) else 0
        self._win_n, self._win_min, self._win_under = 0, None, 0
