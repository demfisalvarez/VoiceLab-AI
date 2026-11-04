"""Fases 4 y 5: lógica de los motores de IA con sesiones ONNX simuladas.

Los modelos reales no se pueden descargar en el entorno de pruebas; aquí se
verifica todo lo que los rodea: flujo de tokens y caché KV, división de
textos, decodificación del tono RMVPE, formatos de entrada RVC, detección de
frecuencia y empalme sin cortes en tiempo real.
"""

import time
from types import SimpleNamespace

import numpy as np
import pytest

from voicelab.ai import rvc, tts

SR = 48000


class Sess:
    def __init__(self, fn, inputs=("x",)):
        self.fn, self._in = fn, inputs
        self.calls = 0

    def get_inputs(self):
        return [SimpleNamespace(name=n) for n in self._in]

    def run(self, _out, feed):
        self.calls += 1
        return self.fn(feed)


# ------------------------------------------------------------------- TTS
def fake_tts(n_tokens=30):
    state = {"step": 0}

    def lm(feed):
        state["step"] += 1
        seq = feed["inputs_embeds"].shape[1]
        logits = np.zeros((1, seq, 8194), np.float32)
        logits[0, -1, tts.STOP if state["step"] > n_tokens else 100 + state["step"]] = 10.0
        past = feed["past_key_values.0.key"].shape[2]
        kv = [np.zeros((1, 16, past + seq, 64), np.float32)] * 60
        return [logits, *kv]

    def embed(feed):
        assert feed["input_ids"].dtype == np.int64 and feed["exaggeration"].shape == (1,)
        return [np.zeros((1, feed["input_ids"].shape[1], 1024), np.float32)]

    sessions = {
        "encoder": Sess(lambda f: [np.zeros((1, 34, 1024), np.float32), np.ones((1, 5), np.int64),
                                   np.zeros((1, 192), np.float32), np.zeros((1, 20, 80), np.float32)]),
        "embed": Sess(embed),
        "lm": Sess(lm),
        "decoder": Sess(lambda f: [np.sin(np.arange(f["speech_tokens"].shape[1] * 960) / 10)[None].astype(np.float32)]),
    }
    tok = SimpleNamespace(encode=lambda text: SimpleNamespace(ids=[255] + [ord(c) % 200 for c in text] + [0, tts.START, tts.START]))
    return tts.ChatterboxTTS("chatterbox-v3", sessions, tok), state


def test_split_text_keeps_sentences_and_limits_length():
    text = "Hola. " * 3 + "Una frase muy larga, " * 30 + "¿Fin?"
    chunks = tts.split_text(text, 120)
    assert all(len(c) <= 120 for c in chunks) and chunks[0].startswith("Hola.")
    assert " ".join(chunks).replace("  ", " ").count("larga") == 30


def test_tts_generation_loop(tmp_path):
    from voicelab.audio import mediaio
    ref = mediaio.save_wav(tmp_path / "ref.wav", np.zeros(tts.SR * 3, np.float32), tts.SR)
    eng, state = fake_tts(30)
    progress = []
    wav = eng.synthesize("Hola, esto es una prueba.", ref, "es", 0.6, 1.0, 1.0, progress=progress.append)
    # 5 tokens de referencia + 30 generados, menos el último token (960 muestras)
    assert wav.shape[0] == (5 + 30) * 960 - 960
    assert state["step"] == 31 and np.max(np.abs(wav)) <= 0.9
    assert progress and 0 < progress[-1] <= 1
    assert eng.s["encoder"].calls == 1          # la referencia se cachea
    eng.synthesize("Otra frase.", ref, "es")
    assert eng.s["encoder"].calls == 1


def test_tts_sampling_cancel_and_language(tmp_path):
    from voicelab.audio import mediaio
    ref = mediaio.save_wav(tmp_path / "ref.wav", np.zeros(tts.SR * 3, np.float32), tts.SR)
    eng, _ = fake_tts(10)
    assert eng.synthesize("Prueba con muestreo.", ref, "es", stability=0.3, seed=1).size > 0
    with pytest.raises(tts.TTSError):
        eng.synthesize("x", ref, "xx")
    eng2, _ = fake_tts(10_000)
    eng2.cancelled.set()
    orig = eng2.cancelled.clear
    eng2.cancelled.clear = lambda: None    # simula cancelar durante la generación
    with pytest.raises(tts.TTSError, match="cancelada"):
        eng2.synthesize("Texto", ref, "es")
    eng2.cancelled.clear = orig
    assert tts.korean_normalize("한") != "한"


# -------------------------------------------------------------------- RVC
def test_rmvpe_decoding_matches_cents_formula():
    def hidden(feed):
        frames = feed["mel"].shape[-1]
        h = np.zeros((1, frames, 360), np.float32)
        h[0, :, 120] = 0.9
        h[0, :, 119] = h[0, :, 121] = 0.3
        return [h]
    r = rvc.RMVPE(Sess(hidden, ("mel",)))
    x = np.random.default_rng(0).standard_normal(16000).astype(np.float32) * 0.1
    assert r.mel(x).shape == (128, 1 + 16000 // 160)
    f0 = r.f0(x)
    expected = 10 * 2 ** ((20 * 120 + 1997.3794084376191) / 1200)
    assert f0.shape[0] == 101 and np.allclose(f0, expected, rtol=1e-4)


def test_mel_basis_shape_and_coverage():
    b = rvc._mel_basis()
    assert b.shape == (128, 513) and (b.sum(axis=1) > 0).all()


def test_coarse_f0_range():
    c = rvc.coarse_f0(np.array([0, 50, 200, 1100, 3000], np.float32))
    assert c[0] == 1 and c[1] == 1 and 1 < c[2] < 255 and c[3] == 255 and c[4] == 255


def fake_rvc(style="webui", model_sr=40000):
    def vec(feed):
        n = feed[list(feed)[0]].shape[-1] // 320
        return [np.zeros((1, n, 768), np.float32)]

    def rm(feed):
        return [np.zeros((1, feed["mel"].shape[-1], 360), np.float32) + np.eye(360)[150] * 0.9]

    def synth(feed):
        f0 = feed["pitchf"][0]
        n = f0.shape[0] * model_sr // 100
        hz = float(np.mean(f0)) or 200.0
        return [(0.5 * np.sin(2 * np.pi * hz * np.arange(n) / model_sr))[None, None].astype(np.float32)]
    names = ("phone", "phone_lengths", "pitch", "pitchf", "ds", "rnd") if style == "webui" else ("feats", "p_len", "pitch", "pitchf", "sid")
    return rvc.RVCModel(None, sessions={"vec": Sess(vec), "rmvpe": Sess(rm, ("mel",)), "synth": Sess(synth, names)})


@pytest.mark.parametrize("style,sr", [("webui", 40000), ("okada", 48000), ("webui", 32000)])
def test_rvc_model_styles_and_sample_rate_detection(style, sr):
    m = fake_rvc(style, sr)
    assert m.style == style and m.sr == sr
    out = m.convert(np.zeros(SR * 3, np.float32), SR, semitones=2)
    assert out.shape[0] == pytest.approx(SR * 3, abs=SR * 0.02)


def test_rvc_rejects_non_rvc_onnx():
    with pytest.raises(rvc.RVCError):
        rvc.RVCModel(None, sessions={"vec": Sess(lambda f: []), "rmvpe": Sess(lambda f: [], ("mel",)),
                                     "synth": Sess(lambda f: [], ("input",))})


def test_realtime_rvc_streams_without_clicks():
    m = fake_rvc("webui", 40000)
    proc = rvc.RealtimeRVC(m, SR, block_s=0.2, context_s=0.4, fade_s=0.03)
    t = np.arange(SR * 4) / SR
    x = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    outs = []
    for i in range(0, x.shape[0], 480):         # bloques de 10 ms a ritmo real acelerado
        outs.append(proc.process(x[i:i + 480]))
        time.sleep(0.002)
    proc.close()
    y = np.concatenate(outs)
    voiced = y[int(SR * 1.0):]
    voiced = voiced[np.abs(voiced) > 0][: SR]
    assert voiced.size > SR * 0.5                          # sale voz convertida
    step = np.max(np.abs(np.diff(voiced)))
    max_slope = 0.5 * 2 * np.pi * 400 / SR                 # tono del modelo simulado (≈ 340–400 Hz)
    assert step < max_slope * 3, step                      # sin saltos bruscos en los empalmes
    assert proc.latency_samples >= int(0.23 * SR)


def test_update_check(tmp_path, monkeypatch):
    import io
    import json as _json
    from voicelab.api import Api
    from voicelab.config import Settings
    from voicelab.profiles import ProfileStore
    from fake_sd import FakeSD
    from voicelab.audio.devices import DeviceManager
    from voicelab.audio.engine import AudioEngine
    a = Api(Settings(tmp_path / "s.json"), DeviceManager(FakeSD()), AudioEngine(DeviceManager(FakeSD())),
            sysinfo_fn=lambda: {}, profiles=ProfileStore(tmp_path / "p"))
    assert not a.check_updates()["ok"]
    assert not a.update_settings({"ui": {"updates_url": "http://inseguro"}})["ok"]
    a.update_settings({"ui": {"updates_url": "https://ejemplo.invalid/version.json"}})

    class R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *e): pass
    monkeypatch.setattr("urllib.request.urlopen", lambda *x, **k: R(_json.dumps({"version": "99.0.0", "url": "https://x/y.exe"}).encode()))
    r = a.check_updates()
    assert r["ok"] and r["newer"] and r["url"] == "https://x/y.exe"
