"""Perfil del texto a voz con el modelo real (CI de Windows): dónde se va el tiempo.

1. Carga de cada sesión ONNX con distintos niveles de optimización.
2. Generación instrumentada: tiempo por sesión, tokens generados, si termina
   con el token de fin, y duración resultante (voraz frente a muestreo).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "ci-out").resolve()
OUT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("VOICELAB_DATA_DIR", str(OUT / "datos"))

import onnxruntime as ort  # noqa: E402

from voicelab.ai import models, tts  # noqa: E402
from voicelab.audio import mediaio  # noqa: E402

LEVELS = {"ninguna": ort.GraphOptimizationLevel.ORT_DISABLE_ALL, "basica": ort.GraphOptimizationLevel.ORT_ENABLE_BASIC,
          "extendida": ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED, "todas": ort.GraphOptimizationLevel.ORT_ENABLE_ALL}
R: dict = {}


def load(path: Path, level) -> tuple:
    so = ort.SessionOptions()
    so.graph_optimization_level = level
    t0 = time.perf_counter()
    s = ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])
    return s, round(time.perf_counter() - t0, 1)


class Timed:
    def __init__(self, s, name, stats):
        self.s, self.name, self.stats = s, name, stats

    def run(self, out, feed):
        t0 = time.perf_counter()
        r = self.s.run(out, feed)
        st = self.stats.setdefault(self.name, {"n": 0, "s": 0.0})
        st["n"] += 1
        st["s"] += time.perf_counter() - t0
        if self.name == "decoder":
            self.stats.setdefault("tokens_decoder", []).append(int(feed["speech_tokens"].shape[1]))
        if self.name == "lm":
            self.stats["ultimo_token_stop"] = bool(np.argmax(r[0][0, -1]) == tts.STOP)
        return r

    def __getattr__(self, k):
        return getattr(self.s, k)


def main():
    if not models.installed("chatterbox-v3"):
        models.install("chatterbox-v3", lambda p: None)
    d = models.model_dir("chatterbox-v3")
    spec = models.CATALOG["chatterbox-v3"]
    parts = {"encoder": "onnx/speech_encoder.onnx", "embed": "onnx/embed_tokens.onnx", "lm": spec["lm"],
             "decoder": "onnx/conditional_decoder.onnx"}
    print("CPU:", os.cpu_count(), "hilos; ORT", ort.__version__, flush=True)
    for name in ("encoder", "lm", "decoder"):
        for lv, level in LEVELS.items():
            s, t = load(d / parts[name], level)
            R[f"carga {name} {lv}"] = t
            print(f"carga {name:8s} {lv:9s} {t:7.1f} s", flush=True)
            del s

    ref = OUT / "ref.wav"
    ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          "$s.SelectVoice('Microsoft Zira Desktop'); "
          f"$s.SetOutputToWaveFile('{ref}'); $s.Speak('Hello, my name is Zira. I am reading this text so that "
          "the computer can learn the sound of my voice. Thank you very much for listening.'); $s.SetOutputToNull(); $s.Dispose()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)

    from tokenizers import Tokenizer
    tok = Tokenizer.from_file(str(d / "tokenizer.json"))
    for lv in ("basica", "todas"):
        sessions = {k: load(d / p, LEVELS[lv])[0] for k, p in parts.items()}
        for text, lang in (("Hola, esto es una prueba de texto a voz hecha en tu ordenador, sin internet.", "es"),
                           ("The quick brown fox jumps over the lazy dog.", "en")):
            for stab in (1.0, 0.5):
                stats: dict = {}
                eng = tts.ChatterboxTTS("chatterbox-v3", {k: Timed(s, k, stats) for k, s in sessions.items()}, tok)
                ids = eng.encode(text, lang)
                t0 = time.perf_counter()
                wav = eng.synthesize(text, ref, lang, 0.5, stab, 1.0, seed=0)
                dt = time.perf_counter() - t0
                key = f"{lv} {lang} estabilidad={stab}"
                R[key] = {"seg_audio": round(wav.shape[0] / tts.SR, 2), "seg_calculo": round(dt, 1),
                          "ids_texto": ids.shape[1], "primeros_ids": ids[0, :12].tolist(),
                          **{k: ({"n": v["n"], "s": round(v["s"], 2)} if isinstance(v, dict) else v)
                             for k, v in stats.items()}}
                print(key, json.dumps(R[key], ensure_ascii=False), flush=True)
                mediaio.save_wav(OUT / f"perfil_{lv}_{lang}_{stab}.wav", wav, tts.SR)
        del sessions
    (OUT / "perfil_tts.json").write_text(json.dumps(R, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
