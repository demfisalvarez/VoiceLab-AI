"""Prueba con los modelos REALES (se ejecuta en la compilación de Windows).

Descarga los modelos igual que la app, genera voces de referencia con las
voces de Windows (SAPI) y comprueba de forma objetiva:

* Texto a voz (Chatterbox, CPU, proceso aparte): genera audio, con duración
  razonable, y el tono se parece al de la voz de referencia (clonación).
* RVC: el detector de tono RMVPE y el extractor ContentVec funcionan con la
  implementación de VoiceLab (tono de una voz grave ≈ 100–150 Hz).
* Voz instantánea en directo (MeanVC2, PyTorch CPU): instalación completa,
  prueba de velocidad y conversión de la voz A hacia la voz B por bloques de
  160 ms, como en directo; el tono resultante debe acercarse al de B.

Uso: python tools/ci_real_models.py salida/   (en Windows con PowerShell)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(ROOT))

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "ci-out").resolve()
OUT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("VOICELAB_DATA_DIR", str(OUT / "datos"))

from voicelab.audio import analysis, mediaio  # noqa: E402

SR = 48000
REPORT: dict = {}
ONLY = set(os.environ.get("VL_CI_ONLY", "tts,rvc,live").split(","))

TEXT_A = ("This is a short recording to test voice conversion. The weather was nice today, "
          "so we walked to the market, bought some fresh bread and came back home before noon. ") * 2
TEXT_B = ("Hello, my name is Zira. I am reading this text so that the computer can learn the sound of my voice. "
          "Thank you very much for listening to this message. ") * 2


def step(name):
    def deco(fn):
        def run():
            if name not in ONLY:
                return
            t0 = time.perf_counter()
            print(f"\n=== {name} ===", flush=True)
            try:
                REPORT[name] = {"ok": True, **(fn() or {})}
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                REPORT[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            REPORT[name]["s"] = round(time.perf_counter() - t0, 1)
            print(json.dumps(REPORT[name], indent=2, ensure_ascii=False), flush=True)
        return run
    return deco


def sapi(text: str, voice_hint: str, path: Path) -> Path:
    """Voz sintetizada por Windows (System.Speech) a un WAV."""
    ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          f"$v = $s.GetInstalledVoices() | ForEach-Object {{ $_.VoiceInfo.Name }} | Where-Object {{ $_ -like '*{voice_hint}*' }} | Select-Object -First 1; "
          "if ($v) { $s.SelectVoice($v) }; "
          f"$s.SetOutputToWaveFile('{path}'); $s.Speak('{text}'); $s.SetOutputToNull(); $s.Dispose(); "
          "Write-Output $v")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    if r.returncode != 0 or not path.exists():
        raise RuntimeError("SAPI falló: " + r.stderr[-500:])
    return path


def f0_median(x: np.ndarray, sr: int) -> float:
    mask = analysis.speech_mask(x, sr)
    if not mask.any():
        mask = np.ones_like(mask)
    f0 = analysis.estimate_f0(x, sr, mask)
    f0 = np.asarray(f0, float)
    f0 = f0[f0 > 0]
    return float(np.median(f0)) if f0.size else 0.0


_ASR = None


def oir(wav: np.ndarray, sr: int, lang: str) -> str:
    """Transcribe con Whisper (solo para comprobar que se entiende)."""
    global _ASR
    if _ASR is None:
        from faster_whisper import WhisperModel
        _ASR = WhisperModel("small", device="cpu", compute_type="int8")
    segs, _ = _ASR.transcribe(mediaio.resample(wav, sr, 16000), language=lang, beam_size=5)
    return " ".join(x.text.strip() for x in segs)


def parecido(a: str, b: str) -> float:
    import difflib
    import re
    norm = lambda t: re.sub(r"[^a-záéíóúñü ]", "", t.lower())  # noqa: E731
    return round(difflib.SequenceMatcher(None, norm(a), norm(b)).ratio(), 2)


def voices():
    a = mediaio.load_audio(sapi(TEXT_A, "David", OUT / "voz_A_david.wav"), SR)
    b = mediaio.load_audio(sapi(TEXT_B, "Zira", OUT / "voz_B_zira.wav"), SR)
    return a, b


@step("tts")
def test_tts():
    from voicelab.ai import models, tts
    if not models.installed("chatterbox-v2"):
        t0 = time.perf_counter()
        models.install("chatterbox-v2", lambda p: None)
        print(f"descarga {time.perf_counter() - t0:.0f} s")
    a, b = voices()
    ref = OUT / "referencia_zira.wav"
    mediaio.save_wav(ref, b, SR)
    svc = tts.TTSService()
    res = {}
    for lang, text in (("es", "Hola, esto es una prueba de texto a voz hecha en tu ordenador, sin internet."),
                       ("en", "The quick brown fox jumps over the lazy dog.")):
        stages = []
        t0 = time.perf_counter()
        wav, info = svc.synthesize("chatterbox-v2", False, (text, ref, lang, 0.5, 1.0, 1.0),
                                   lambda p: None, stages.append)
        dt = time.perf_counter() - t0
        dur = wav.shape[0] / tts.SR
        mediaio.save_wav(OUT / f"tts_{lang}.wav", wav, tts.SR)
        res[lang] = {"segundos_audio": round(dur, 2), "segundos_calculo": round(dt, 1), "dispositivo": info["device"],
                     "rms": round(float(np.sqrt(np.mean(wav ** 2))), 4),
                     "f0_salida": round(f0_median(wav, tts.SR), 1), "etapas": stages[-3:]}
        res[lang]["oido"] = oir(wav, tts.SR, lang)
        res[lang]["parecido"] = parecido(res[lang]["oido"], text)
        assert 1.0 < dur < 20.0, f"duración rara: {dur:.1f} s"
        assert res[lang]["rms"] > 0.01, "audio casi en silencio"
        assert res[lang]["parecido"] >= 0.75, f"no dice el texto: «{res[lang]['oido']}»"
    res["f0_referencia"] = round(f0_median(b, SR), 1)
    # La segunda llamada reutiliza el proceso (modelo ya cargado): debe ser mucho más rápida que la primera.
    t0 = time.perf_counter()
    svc.synthesize("chatterbox-v2", False, ("Segunda frase.", ref, "es", 0.5, 1.0, 1.0), None, lambda s: None)
    res["segunda_llamada_s"] = round(time.perf_counter() - t0, 1)
    # GPU (en la máquina de compilación no hay GPU: comprueba que el fallo vuelve a la CPU sin colgarse)
    try:
        wav, info = svc.synthesize("chatterbox-v2", True, ("Prueba con la GPU.", ref, "es", 0.5, 1.0, 1.0),
                                   None, lambda s: None)
        res["gpu"] = {"dispositivo": info["device"], "fallback": info.get("fallback")}
    except Exception as exc:  # noqa: BLE001
        res["gpu"] = {"error": str(exc)}
    svc.unload()
    return res


@step("rvc")
def test_rvc():
    from voicelab.ai import models, runtime
    from voicelab.ai.rvc import RMVPE
    if not models.installed("rvc-base"):
        models.install("rvc-base", lambda p: None)
    a, _ = voices()
    x16 = mediaio.resample(a, SR, 16000)[: 16000 * 8]
    d = models.model_dir("rvc-base")
    rm = RMVPE(runtime.session(d / "rmvpe.onnx", prefer_gpu=False))
    f0 = rm.f0(x16)
    voiced = f0[f0 > 0]
    vec = runtime.session(d / "vec-768-layer-12.onnx", prefer_gpu=False)
    feats = vec.run(None, {vec.get_inputs()[0].name: x16[None, None, :].astype(np.float32)})[0]
    res = {"rmvpe_f0_mediana": round(float(np.median(voiced)), 1) if voiced.size else 0.0,
           "tramos_con_voz": round(float(voiced.size / max(1, f0.size)), 2),
           "f0_referencia_simple": round(f0_median(a, SR), 1), "contentvec_forma": list(feats.shape)}
    assert 70 < res["rmvpe_f0_mediana"] < 220, "RMVPE da un tono fuera de lo esperable para una voz grave"
    assert 768 in feats.shape
    return res


@step("live")
def test_live():
    from voicelab.ai import meanvc
    from voicelab.audio.resampler import StreamResampler
    t0 = time.perf_counter()
    res = {"instalacion": meanvc.install(lambda p: None)}
    res["instalacion_s"] = round(time.perf_counter() - t0, 1)
    a, b = voices()
    w = meanvc.MeanVCWorker(meanvc.worker_command("120ms"))
    try:
        t1 = time.perf_counter()
        emb = w.compute_embedding(mediaio.resample(b, SR, 16000))
        res["huella_s"] = round(time.perf_counter() - t1, 1)
        w.set_embedding(emb)
        x16 = StreamResampler(SR, 16000).process(a)
        outs, times = [], []
        for i in range(0, x16.shape[0] - meanvc.CHUNK16, meanvc.CHUNK16):     # como en directo
            t1 = time.perf_counter()
            outs.append(w.process(x16[i:i + meanvc.CHUNK16]))
            times.append(time.perf_counter() - t1)
        y = np.concatenate(outs)
    finally:
        w.close()
    mediaio.save_wav(OUT / "directo_A_a_B.wav", y, 16000)
    res["oido_original"] = oir(a[: SR * 12], SR, "en")
    res["oido_convertida"] = oir(y[: 16000 * 12], 16000, "en")
    res["parecido_convertida"] = parecido(res["oido_convertida"], res["oido_original"])
    res.update({"ms_por_bloque_mediana": round(float(np.median(times)) * 1000, 1),
                "ms_por_bloque_p95": round(float(np.percentile(times, 95)) * 1000, 1),
                "segundos_entrada": round(x16.shape[0] / 16000, 1), "segundos_salida": round(y.shape[0] / 16000, 1),
                "f0_A": round(f0_median(a, SR), 1), "f0_B": round(f0_median(b, SR), 1),
                "f0_convertida": round(f0_median(y, 16000), 1),
                "rms_salida": round(float(np.sqrt(np.mean(y ** 2))), 4)})
    # Alta definición (AP-BWE 16→48 kHz): descarga real desde Google Drive, velocidad y agudos.
    t0 = time.perf_counter()
    res["hd_instalacion"] = meanvc.install_hd(lambda p: None)
    res["hd_instalacion_s"] = round(time.perf_counter() - t0, 1)
    w = meanvc.MeanVCWorker(meanvc.worker_command("120ms", threads=2, hd=True))
    try:
        assert w.hello.get("out_sr") == 48000
        w.set_embedding(emb)
        outs, times = [], []
        for i in range(0, x16.shape[0] - meanvc.CHUNK16, meanvc.CHUNK16):
            t1 = time.perf_counter()
            outs.append(w.process(x16[i:i + meanvc.CHUNK16]))
            times.append(time.perf_counter() - t1)
        y48 = np.concatenate(outs)
    finally:
        w.close()
    mediaio.save_wav(OUT / "directo_A_a_B_hd.wav", y48, 48000)

    def hf_db(z, sr):
        Z = np.abs(np.fft.rfft(z)) ** 2
        f = np.fft.rfftfreq(z.shape[0], 1 / sr)
        return round(float(10 * np.log10(Z[f > 8500].sum() / Z.sum() + 1e-20)), 1)
    res.update({"hd_ms_por_bloque_mediana": round(float(np.median(times)) * 1000, 1),
                "hd_ms_por_bloque_p95": round(float(np.percentile(times, 95)) * 1000, 1),
                "hd_agudos_sobre_8k_dB": hf_db(y48, 48000), "sin_hd_agudos_sobre_8k_dB": hf_db(y, 16000),
                "hd_oido": oir(y48[: 48000 * 12], 48000, "en")})
    res["hd_parecido"] = parecido(res["hd_oido"], res["oido_original"])
    assert res["hd_parecido"] >= 0.85, "la alta definición estropea la voz"
    assert abs(res["segundos_salida"] - res["segundos_entrada"]) < 1.0, "la salida no dura lo mismo que la entrada"
    assert res["rms_salida"] > 0.005, "salida casi en silencio"
    assert res["ms_por_bloque_mediana"] < 160, "no llega a tiempo real en esta CPU"
    # La conversión debe acercar el tono al de la voz B.
    assert abs(res["f0_convertida"] - res["f0_B"]) < abs(res["f0_A"] - res["f0_B"]), "el tono no se acerca a la voz B"
    return res


if __name__ == "__main__":
    test_tts()
    test_rvc()
    test_live()
    (OUT / "informe.json").write_text(json.dumps(REPORT, indent=2, ensure_ascii=False), encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("## Modelos reales\n\n```json\n" + json.dumps(REPORT, indent=2, ensure_ascii=False) + "\n```\n")
    logs = Path(os.environ["VOICELAB_DATA_DIR"]) / "logs"
    for f in sorted(logs.glob("*.log")) if logs.exists() else []:
        print(f"\n----- {f.name} (final)")
        print("\n".join(f.read_text("utf-8", "replace").splitlines()[-60:]))
    bad = [k for k, v in REPORT.items() if not v.get("ok")]
    print("\nRESULTADO:", "todo bien" if not bad else "fallos en " + ", ".join(bad))
    sys.exit(1 if bad else 0)
