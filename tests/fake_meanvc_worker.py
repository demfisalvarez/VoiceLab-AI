"""Proceso de MeanVC2 simulado para las pruebas (mismo protocolo, sin PyTorch).

Devuelve el audio de entrada tal cual pero con el mismo patrón de ráfagas que
el modelo real «120ms»: por cada bloque de 160 ms entrega 120, 120 o 240 ms.
Variables de entorno:
    FAKE_MVC_STEADY=1     como el modelo «40ms»: bloques de 80 ms, salida regular con 95 ms retenidos
    FAKE_MVC_STALL=k:ms   en el bloque k tarda «ms» milisegundos (la CPU se atasca una vez)
    FAKE_MVC_WORK_MS=ms   cada bloque tarda «ms» milisegundos (como el cálculo real)
    FAKE_MVC_FAIL_START   falla al arrancar (como si faltara PyTorch)
    FAKE_MVC_DIE_AFTER=n  se cierra de golpe tras n bloques
    FAKE_MVC_LOG=ruta     apunta las peticiones recibidas (una letra por línea)
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # raíz del proyecto (admite -I)

import numpy as np  # noqa: E402

from voicelab.ai import meanvc_worker as P  # noqa: E402


def main() -> int:
    out, inp = sys.stdout.buffer, sys.stdin.buffer
    if os.environ.get("FAKE_MVC_FAIL_START"):
        print("Traceback: ModuleNotFoundError: No module named 'torch'", file=sys.stderr)
        P.send_json(out, {"ok": False, "error": "ModuleNotFoundError: No module named 'torch'"})
        return 2
    steady = bool(os.environ.get("FAKE_MVC_STEADY"))
    model, chunk = ("40ms", 1280) if steady else ("120ms", P.CHUNK)
    hold_ms, burst_ms = P.hold(model, chunk)
    P.send_json(out, {"ok": True, "model": model, "chunk": chunk, "align": 0, "hold_ms": hold_ms,
                      "burst_ms": burst_ms, "sr": P.SR, "torch": "simulado"})
    stall_at, stall_ms = (int(v) for v in (os.environ.get("FAKE_MVC_STALL") or "0:0").split(":"))
    work_s = float(os.environ.get("FAKE_MVC_WORK_MS") or 0) / 1000     # tiempo de cálculo simulado
    keep = int(hold_ms * P.SR / 1000)
    die_after = int(os.environ.get("FAKE_MVC_DIE_AFTER", "0") or 0)
    log = os.environ.get("FAKE_MVC_LOG")
    emb, fifo, frames, calls = None, np.zeros(0, np.float32), 0, 0
    while True:
        try:
            kind, data = P.recv(inp)
        except EOFError:
            return 0
        if log:
            with open(log, "a", encoding="utf-8") as f:
                f.write(kind.decode() + "\n")
        if kind == b"R":
            a = np.frombuffer(data, np.float32)
            P.send(out, b"E", np.full(P.EMB_DIM, float(np.sqrt(np.mean(a ** 2))), np.float32).tobytes())
        elif kind == b"E":
            emb = np.frombuffer(data, np.float32)
            P.send_json(out, {"ok": True})
        elif kind == b"A":
            if emb is None:
                P.send_json(out, {"ok": False, "error": "No se ha fijado la voz de destino"})
                continue
            calls += 1
            if die_after and calls > die_after:
                os._exit(3)
            if work_s:
                import time
                time.sleep(work_s)
            if stall_at and calls == stall_at:
                import time
                time.sleep(stall_ms / 1000)
            fifo = np.concatenate([fifo, np.frombuffer(data, np.float32)])
            if steady:                                   # salida regular, con «keep» muestras retenidas
                n = max(0, fifo.shape[0] - keep)
                y, fifo = fifo[:n], fifo[n:]
                P.send(out, b"A", y.astype(np.float32).tobytes())
                continue
            frames += 16
            steps = 0
            while frames >= 16:
                frames -= 12
                steps += 1
            n = min(fifo.shape[0], steps * 1920)
            y, fifo = fifo[:n], fifo[n:]
            P.send(out, b"A", y.astype(np.float32).tobytes())
        elif kind == b"Z":
            fifo, frames = np.zeros(0, np.float32), 0
            P.send_json(out, {"ok": True})
        elif kind == b"Q":
            return 0


if __name__ == "__main__":
    sys.exit(main())
