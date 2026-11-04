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
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
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
    ref = OUT / "ref.wav"
    ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          "$s.SelectVoice('Microsoft Zira Desktop'); "
          f"$s.SetOutputToWaveFile('{ref}'); $s.Speak('Hello, my name is Zira. I am reading this text so that "
          "the computer can learn the sound of my voice. Thank you very much for listening.'); $s.SetOutputToNull(); $s.Dispose()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)

    from tokenizers import Tokenizer
    tok = Tokenizer.from_file(str(d / "tokenizer.json"))
    tj = json.loads((d / "tokenizer.json").read_text(encoding="utf-8"))
    vocab = tj.get("model", {}).get("vocab", {})
    R["tokenizador"] = {"normalizer": tj.get("normalizer"), "pre_tokenizer": (tj.get("pre_tokenizer") or {}).get("type"),
                        "post_processor": (tj.get("post_processor") or {}).get("type"), "tam_vocab": tok.get_vocab_size(),
                        "mayusculas_en_vocab": sum(1 for k in vocab if any(c.isupper() for c in k)),
                        "tiene_ñ": "ñ" in vocab, "tiene_n_tilde_nfkd": "\u0303" in vocab,
                        "unk": tj.get("model", {}).get("unk_token")}
    for t in ("[es]Hola, ¿qué tal? El niño come piña.", "[es]hola, ¿que tal? el nino come pina."):
        e = tok.encode(t)
        R["tokenizador"][t] = list(zip(e.tokens, e.ids))[:40]
    print(json.dumps(R["tokenizador"], ensure_ascii=False, indent=1), flush=True)

    sessions = {k: load(d / p, LEVELS["todas"])[0] for k, p in parts.items()}
    textos = {"es": "Hola, esto es una prueba de texto a voz hecha en tu ordenador, sin internet.",
              "es2": "Mañana por la tarde iremos al mercado a comprar fruta, pan y queso para la cena.",
              "en": "The quick brown fox jumps over the lazy dog."}
    casos = [("es", "raw", 1.0, 10), ("es", "lower", 1.0, 10), ("es", "raw", 0.5, 10), ("es", "lower", 0.5, 10),
             ("es2", "raw", 1.0, 10), ("es2", "lower", 1.0, 10), ("es2", "lower", 0.5, 10),
             ("en", "raw", 1.0, 10), ("en", "raw", 0.5, 10), ("es", "lower", 1.0, 6)]
    for key_t, mode, stab, refs in casos:
        stats: dict = {}
        eng = tts.ChatterboxTTS("chatterbox-v3", {k: Timed(s, k, stats) for k, s in sessions.items()}, tok)
        eng.text_mode, eng.ref_seconds = mode, refs
        lang = key_t[:2]
        text = textos[key_t]
        t0 = time.perf_counter()
        wav = eng.synthesize(text, ref, lang, 0.5, stab, 1.0, seed=0)
        dt = time.perf_counter() - t0
        key = f"{key_t} texto={mode} estabilidad={stab} ref={refs}s"
        R[key] = {"seg_audio": round(wav.shape[0] / tts.SR, 2), "seg_calculo": round(dt, 1),
                  "chars": len(text), **eng.last_stats,
                  **{k: ({"n": v["n"], "s": round(v["s"], 2)} if isinstance(v, dict) else v)
                     for k, v in stats.items() if k != "tokens_decoder"}}
        print(key, json.dumps(R[key], ensure_ascii=False), flush=True)
        mediaio.save_wav(OUT / f"perfil_{key_t}_{mode}_{stab}_{refs}.wav", wav, tts.SR)
    (OUT / "perfil_tts.json").write_text(json.dumps(R, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
