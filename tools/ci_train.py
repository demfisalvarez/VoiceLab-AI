"""Entrenamiento real de una voz RVC en Windows (CI): de principio a fin.

Voz destino: Zira (SAPI), ~3 minutos. Comprueba que:
* se descargan y verifican los preentrenados; se preparan los datos (ContentVec + RMVPE);
* el entrenador arranca, avanza, guarda, se puede parar con STOP y continuar;
* exporta un ONNX que la app carga (con «skip_head»), suena a 40 kHz, se entiende
  (Whisper) y sigue el tono destino;
* en directo con ese modelo: retraso y huecos (CPU del servidor, sin GPU).

Uso: python tools/ci_train.py salida/ [pasos]
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ci_live_quality as Q  # noqa: E402
import ci_real_models as R  # noqa: E402

from voicelab.ai import meanvc, models, rvc, rvc_train  # noqa: E402
from voicelab.audio import mediaio  # noqa: E402

OUT = R.OUT
SR = 48000
STEPS = int(sys.argv[2]) if len(sys.argv) > 2 else 40
REPORT: dict = {"cpu": os.cpu_count()}
PARAGRAPHS = [
    "The old lighthouse stood at the edge of the cliff for more than a hundred years.",
    "Every evening the keeper climbed the stairs, cleaned the glass and lit the lamp for the ships at sea.",
    "In winter the wind was so strong that the windows rattled all night long.",
    "Some sailors said that the light could be seen from forty miles away on a clear night.",
    "Today the lighthouse is a small museum, and children come to learn about the history of the coast.",
    "Please remember to bring a warm jacket, because the weather near the water changes very quickly.",
    "We walked along the beach, collected shells and watched the boats return to the harbour.",
    "My favourite part of the trip was the fresh bread from the bakery near the station.",
    "Numbers are easy to say: one, two, three, four, five, six, seven, eight, nine and ten.",
    "Science helps us understand the world, from tiny cells to distant galaxies far away.",
]


def zira_material(path: Path) -> np.ndarray:
    parts = []
    for k in range(3):
        text = " ".join(PARAGRAPHS[k:] + PARAGRAPHS[:k])
        parts.append(mediaio.load_audio(R.sapi(text, "Zira", OUT / f"zira_{k}.wav"), SR))
        parts.append(np.zeros(int(0.6 * SR), np.float32))
    x = np.concatenate(parts)
    mediaio.save_wav(path, x, SR)
    return x


def main() -> int:
    t0 = time.perf_counter()
    if not meanvc.runtime_ready():
        meanvc.install_runtime(lambda p: None)
    for key in ("rvc-base", rvc_train.PRETRAIN_KEY):
        models.install(key, lambda p: None)
    REPORT["instalacion_s"] = round(time.perf_counter() - t0, 1)

    pdir = OUT / "perfil"
    pdir.mkdir(parents=True, exist_ok=True)
    mat = zira_material(pdir / "material.wav")
    REPORT["material_s"] = round(mat.shape[0] / SR, 1)
    a, _ = R.voices()

    # ---- datos
    t0 = time.perf_counter()
    prep = rvc_train.Preparer(prefer_gpu=False)
    wd = OUT / "entreno"
    wd.mkdir(exist_ok=True)
    REPORT["datos"] = prep.run(str(pdir / "material.wav"), str(wd / "dataset.npz"))
    REPORT["datos"]["s"] = round(time.perf_counter() - t0, 1)
    print(REPORT["datos"], flush=True)

    # ---- entrenar: primera mitad, STOP, y continuar
    events = []

    def run(steps, stop_after=None):
        cmd = rvc_train.trainer_command(wd / "dataset.npz", wd, 0, steps=steps, threads=max(1, (os.cpu_count() or 2)))
        p = rvc_train.TrainerProcess(cmd, wd, events.append)
        if stop_after:
            def stopper():
                while p.proc.poll() is None:
                    if any(e.get("type") == "progress" and e["step"] >= stop_after for e in events):
                        p.stop()
                        return
                    time.sleep(0.5)
            threading.Thread(target=stopper, daemon=True).start()
        return p.wait()

    t0 = time.perf_counter()
    rc1 = run(STEPS, stop_after=max(5, STEPS // 3))
    first = [e for e in events if e.get("type") == "exported"]
    rc2 = run(STEPS)
    exported = [e for e in events if e.get("type") == "exported"]
    prog = [e for e in events if e.get("type") == "progress"]
    REPORT["entreno"] = {"rc": [rc1, rc2], "s": round(time.perf_counter() - t0, 1),
                         "parada_en_paso": first[0]["step"] if first else None,
                         "pasos": exported[-1]["step"] if exported else None,
                         "s_por_paso": prog[-1]["s_per_step"] if prog else None,
                         "loss_mel_inicio": prog[0]["loss_mel"] if prog else None,
                         "loss_mel_final": exported[-1].get("loss_mel") if exported else None,
                         "errores": [e for e in events if e.get("type") == "error"]}
    print(REPORT["entreno"], flush=True)
    assert rc1 == 0 and rc2 == 0 and exported and exported[-1]["step"] == STEPS, REPORT["entreno"]

    # ---- el modelo exportado en la app
    onnx = Path(exported[-1]["path"])
    m = rvc.RVCModel(onnx, prefer_gpu=False)
    x16 = mediaio.resample(a, SR, 16000)
    t0 = time.perf_counter()
    y = m.convert16(x16)
    conv_s = time.perf_counter() - t0
    heard = R.oir(y, m.sr, "en")
    f0_out = R.f0_median(y, m.sr)
    REPORT["modelo"] = {"sr": m.sr, "skip_head": m.can_skip, "rtf": round(conv_s / (x16.shape[0] / 16000), 3),
                        "oido": heard, "inteligible": R.parecido(heard, R.TEXT_A), "f0_salida": f0_out,
                        "f0_destino": REPORT["datos"]["f0_median"]}
    mediaio.save_wav(OUT / "entrenada_convertida.wav", y, m.sr)
    yk = m.convert16(x16, keep=100)
    REPORT["modelo"]["skip_head_ok"] = abs(yk.shape[0] - 100 * m.sr // 100) <= m.sr // 100
    print(REPORT["modelo"], flush=True)

    # ---- en directo (CPU del servidor)
    proc = rvc.RealtimeRVC(m, SR)
    yl = Q.run_realtime(proc, a[: SR * 15])
    proc.close()
    lag = Q.envelope_lag(x16[: 16000 * 15], mediaio.resample(yl, SR, 16000))
    REPORT["directo_cpu"] = {"retraso_medido_ms": round(lag * 1000), "retraso_app_ms": round(proc.latency_samples / SR * 1000),
                             "bloque_ms": proc.block * 1000 // SR, "calculo_ms": round(proc.infer_ms, 1),
                             "huecos": proc.underruns}
    print(REPORT["directo_cpu"], flush=True)

    txt = json.dumps(REPORT, indent=2, ensure_ascii=False)
    (OUT / "entreno.json").write_text(txt, encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("## Entrenamiento RVC\n\n```json\n" + txt + "\n```\n")
    print("\nINFORME:\n" + txt)
    ok = REPORT["modelo"]["skip_head"] and REPORT["modelo"]["skip_head_ok"] and REPORT["modelo"]["inteligible"] > 0.5
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
