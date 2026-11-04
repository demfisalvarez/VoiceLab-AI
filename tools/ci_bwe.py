"""Experimento (CI de Windows): AP-BWE 16→48 kHz en directo con la CPU.

Descarga los pesos oficiales (Google Drive del autor, licencia MIT), mide la velocidad con 1/2/4 hilos
y compara el procesado por bloques (como en directo) con una sola pasada.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(ROOT / "voicelab" / "ai" / "vendor" / "apbwe"))
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "ci-out").resolve()
OUT.mkdir(parents=True, exist_ok=True)

import torch  # noqa: E402
from scipy.signal import resample_poly  # noqa: E402

import bwe  # noqa: E402

FOLDER = "https://drive.google.com/drive/folders/1IIYTf2zbJWzelu4IftKD6ooHloJ8mnZF"
dst = OUT / "apbwe"
import gdown  # noqa: E402

files = gdown.download_folder(FOLDER, output=str(dst), quiet=True, skip_download=True)
for it in files:
    print("archivo:", getattr(it, "id", None), getattr(it, "path", None), flush=True)
want = [it for it in files if "16kto48k" in str(getattr(it, "path", ""))]
for it in want:
    target = dst / it.path
    target.parent.mkdir(parents=True, exist_ok=True)
    gdown.download(id=it.id, output=str(target), quiet=True)
    print("descargado", it.id, it.path, target.stat().st_size, hashlib.sha256(target.read_bytes()).hexdigest(),
          flush=True)
ck = sorted(p for p in dst.rglob("*") if p.is_file() and p.name.startswith("g_"))
cfgs = sorted(p for p in dst.rglob("config.json"))
print("checkpoint:", ck, "config:", cfgs, flush=True)
f = ck[0]
if cfgs:
    print("config del autor:", cfgs[0].read_text(), flush=True)

model, h = bwe.load(str(f))
ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
      "$s.SelectVoice('Microsoft Zira Desktop'); "
      f"$s.SetOutputToWaveFile('{OUT / 'voz.wav'}'); $s.Speak('Hello, this is a test of bandwidth extension for "
      "live voice conversion. She sells sea shells by the sea shore.'); $s.SetOutputToNull(); $s.Dispose()")
subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
import wave  # noqa: E402

with wave.open(str(OUT / "voz.wav")) as w:
    sr0 = w.getframerate()
    x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
x16 = resample_poly(x, 16000, sr0).astype(np.float32)
print("entrada", sr0, "Hz,", round(x16.shape[0] / 16000, 2), "s", flush=True)

res = {}
sb = bwe.StreamingBWE(model, h)
full = sb.run_full(bwe.Upsample3().process(x16))


def hf(y):
    Y = np.abs(np.fft.rfft(y)) ** 2
    fr = np.fft.rfftfreq(y.shape[0], 1 / 48000)
    return round(float(10 * np.log10(Y[fr > 8500].sum() / Y.sum())), 1)


res["energia_sobre_8k_dB"] = {"entrada": hf(bwe.Upsample3().process(x16)), "salida": hf(full)}
for threads in (1, 2, 4):
    torch.set_num_threads(threads)
    for rctx in (0.02, 0.03, 0.045):
        s = bwe.StreamingBWE(model, h, rctx_s=rctx)
        outs, times = [], []
        pattern = [1920, 1920, 3840]
        i = k = 0
        while i < x16.shape[0]:
            n = pattern[k % 3]
            t0 = time.perf_counter()
            outs.append(s.process(x16[i:i + n]))
            times.append((time.perf_counter() - t0) / (n / 16000))
            i += n
            k += 1
        y = np.concatenate(outs)
        lat = s.latency
        ref = full[: y.shape[0]]
        m = min(ref.shape[0], y.shape[0])
        err = y[:m] - ref[:m]
        snr = 10 * np.log10(np.sum(ref[:m] ** 2) / max(np.sum(err ** 2), 1e-12))
        res[f"hilos={threads} rctx={int(rctx * 1000)}ms"] = {"rtf": round(float(np.median(times)), 3),
                                                           "rtf_p95": round(float(np.percentile(times, 95)), 3),
                                                           "snr_vs_pasada_unica_dB": round(float(snr), 1),
                                                           "retraso_ms": round(lat / 48, 1)}
        print(threads, rctx, res[f"hilos={threads} rctx={int(rctx * 1000)}ms"], flush=True)
print(json.dumps(res, indent=1), flush=True)
