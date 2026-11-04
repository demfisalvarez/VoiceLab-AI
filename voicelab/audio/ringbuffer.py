"""Búfer circular mono de un productor y un consumidor.

El hilo de entrada (micrófono) escribe y el hilo de cada salida lee. El
escritor solo modifica ``_w`` y el lector solo ``_r``, así que no hacen falta
bloqueos: los contadores son enteros de Python que crecen sin límite y las
asignaciones son atómicas bajo el GIL. Primero se copian los datos y después
se publica el nuevo índice.
"""

from __future__ import annotations

import numpy as np


class RingBuffer:
    def __init__(self, capacity: int):
        if capacity <= 0:
            raise ValueError("capacity debe ser > 0")
        self._cap = int(capacity)
        self._buf = np.zeros(self._cap, dtype=np.float32)
        self._w = 0  # muestras escritas en total
        self._r = 0  # muestras leídas en total

    @property
    def capacity(self) -> int:
        return self._cap

    def available(self) -> int:
        """Muestras listas para leer."""
        return self._w - self._r

    def free(self) -> int:
        return self._cap - (self._w - self._r)

    # -------------------------------------------------------------- escritor
    def write(self, data: np.ndarray) -> int:
        """Escribe ``data``. Devuelve cuántas muestras se descartaron por falta
        de espacio (solo ocurre si el lector se ha detenido)."""
        n = int(data.shape[0])
        free = self._cap - (self._w - self._r)
        dropped = 0
        if n > free:
            dropped = n - free
            n = free
        if n <= 0:
            return dropped
        start = self._w % self._cap
        first = min(n, self._cap - start)
        self._buf[start:start + first] = data[:first]
        if n > first:
            self._buf[: n - first] = data[first:n]
        self._w += n
        return dropped

    # ---------------------------------------------------------------- lector
    def read_into(self, out: np.ndarray, n: int) -> int:
        """Copia hasta ``n`` muestras en ``out[:k]`` y devuelve ``k``."""
        avail = self._w - self._r
        k = min(n, avail)
        if k <= 0:
            return 0
        start = self._r % self._cap
        first = min(k, self._cap - start)
        out[:first] = self._buf[start:start + first]
        if k > first:
            out[first:k] = self._buf[: k - first]
        self._r += k
        return k

    def peek_into(self, out: np.ndarray, n: int) -> int:
        """Como ``read_into`` pero sin consumir las muestras. Solo el lector."""
        avail = self._w - self._r
        k = min(n, avail)
        if k <= 0:
            return 0
        start = self._r % self._cap
        first = min(k, self._cap - start)
        out[:first] = self._buf[start:start + first]
        if k > first:
            out[first:k] = self._buf[: k - first]
        return k

    def skip(self, n: int) -> int:
        """Descarta hasta ``n`` muestras (las más antiguas). Solo el lector."""
        k = max(0, min(n, self._w - self._r))
        self._r += k
        return k
