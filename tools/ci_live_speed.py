"""Velocidad (hilos) y retraso real de la voz instantánea con los modelos reales.

Uso: python tools/ci_live_speed.py salida/
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ci_live_quality as Q  # noqa: E402
import ci_real_models as R  # noqa: E402

from voicelab.ai import meanvc  # noqa: E402
from voicelab.audio import mediaio  # noqa: E402

REPORT: dict = {"cpu": os.cpu_count()}


def main() -> int:
    meanvc.install(lambda p: None)
    a, b = R.voices()
    a = a[: Q.SR * 20]
    x16 = mediaio.resample(a, Q.SR, 16000)
    w0 = meanvc.MeanVCWorker(meanvc.worker_command("40ms"))
    emb = w0.compute_embedding(mediaio.resample(b, Q.SR, 16000))
    w0.close()
    for variant, threads in [("40ms", 1), ("40ms", 2), ("40ms", 3), ("40ms", 4), ("120ms", 1), ("120ms", 2)]:
        w = meanvc.MeanVCWorker(meanvc.worker_command(variant, threads=threads))
        try:
            w.set_embedding(emb)
            _, times = Q.run_offline(w, x16)
        finally:
            w.close()
        t = np.array(times[3:]) * 1000
        REPORT[f"{variant}_hilos{threads}"] = {"ms_mediana": round(float(np.median(t)), 1),
                                              "ms_p95": round(float(np.percentile(t, 95)), 1),
                                              "bloque_ms": int(w.hello["chunk"]) / 16}
        print(variant, threads, REPORT[f"{variant}_hilos{threads}"], flush=True)
    for variant, threads in [("40ms", 2), ("120ms", 1)]:
        w = meanvc.MeanVCWorker(meanvc.worker_command(variant, threads=threads), realtime=True)
        w.set_embedding(emb)
        proc = meanvc.RealtimeMeanVC(w, Q.SR, variant)
        try:
            y = Q.run_realtime(proc, a)
        finally:
            proc.close()
        lag = Q.envelope_lag(x16, Q.to16(y, Q.SR))
        REPORT[f"directo_{variant}_hilos{threads}"] = {
            "retraso_medido_ms": round(lag * 1000), "retraso_app_ms": round(proc.latency_samples / Q.SR * 1000),
            "huecos": proc.underruns, "descartado_ms": round(proc.dropped / Q.SR * 1000),
            "recortado_ms": round(proc.trimmed / Q.SR * 1000), "calculo_ms": round(proc.infer_ms, 1)}
        print(REPORT[f"directo_{variant}_hilos{threads}"], flush=True)
    txt = json.dumps(REPORT, indent=2, ensure_ascii=False)
    (R.OUT / "velocidad_directo.json").write_text(txt, encoding="utf-8")
    print("\nINFORME:\n" + txt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
