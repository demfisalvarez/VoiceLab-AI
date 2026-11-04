"""Remuestreo polifásico en streaming (por bloques, sin chasquidos en los bordes).

``resample_poly`` de SciPy trata cada bloque como una señal aislada y deja
transitorios en los extremos. Este remuestreador conserva el historial entre
llamadas, así que procesar una señal troceada da exactamente el mismo
resultado que procesarla entera (salvo un retardo fijo y pequeño).
"""

from __future__ import annotations

from math import gcd

import numpy as np


class StreamResampler:
    def __init__(self, src: int, dst: int, half_len: int = 10, beta: float = 5.0):
        if src <= 0 or dst <= 0:
            raise ValueError("frecuencias no válidas")
        g = gcd(int(src), int(dst))
        self.src, self.dst = int(src), int(dst)
        self.up, self.down = self.dst // g, self.src // g
        self.passthrough = self.up == self.down
        if self.passthrough:
            self.delay_s = 0.0
            return
        from scipy.signal import firwin
        m = max(self.up, self.down)
        k = 2 * half_len * m + 1                      # mismo diseño que resample_poly
        h = firwin(k, 1.0 / m, window=("kaiser", beta)) * self.up
        t = -(-k // self.up)                          # tomas por fase
        hp = np.zeros(t * self.up)
        hp[:k] = h
        # poly[p, j] = h[p + (t-1-j)*up]: invertido para multiplicar ventanas en orden natural
        self._poly = hp.reshape(t, self.up).T[:, ::-1].astype(np.float64).copy()
        self._taps = t
        self.delay_s = (k - 1) / 2 / (self.src * self.up)
        self.reset()

    def reset(self) -> None:
        if self.passthrough:
            return
        self._buf = np.zeros(self._taps - 1, np.float64)   # historial (ceros antes del inicio)
        self._base = -(self._taps - 1)                       # índice absoluto de _buf[0]
        self._m = 0                                          # siguiente muestra de salida

    def process(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, np.float64).reshape(-1)
        if self.passthrough:
            return x.astype(np.float32)
        buf = np.concatenate([self._buf, x])
        total = self._base + buf.shape[0]                   # índice absoluto tras la última muestra
        m_end = (total * self.up + self.down - 1) // self.down
        if m_end <= self._m:
            self._buf = buf
            return np.zeros(0, np.float32)
        ms = np.arange(self._m, m_end, dtype=np.int64)
        n = ms * self.down
        phase = n % self.up
        start = n // self.up - self._base - (self._taps - 1)
        win = np.lib.stride_tricks.sliding_window_view(buf, self._taps)[start]
        y = np.einsum("ij,ij->i", win, self._poly[phase])
        self._m = m_end
        keep_from = (m_end * self.down) // self.up - (self._taps - 1)
        cut = max(0, min(buf.shape[0], keep_from - self._base))
        self._buf = buf[cut:]
        self._base += cut
        return y.astype(np.float32)
