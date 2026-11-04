"""Acabado de estudio para las voces de IA."""
import numpy as np

from voicelab.audio.dsp import lin_to_db
from voicelab.audio.polish import AutoLevel, DeEsser, Polish, PolishedAI

SR = 48000


def voiced(seconds, f0=150.0, amp=0.1, seed=0):
    t = np.arange(int(seconds * SR)) / SR
    x = sum((amp / k) * np.sin(2 * np.pi * f0 * k * t) for k in range(1, 20))
    env = 0.6 + 0.4 * np.sin(2 * np.pi * 3 * t)
    return (x * env).astype(np.float32)


def sibilant(seconds, amp=0.1, seed=0):
    rng = np.random.default_rng(seed)
    from scipy.signal import butter, sosfilt
    return (amp * sosfilt(butter(4, [5500, 9500], "bandpass", fs=SR, output="sos"),
                          rng.standard_normal(int(seconds * SR)))).astype(np.float32)


def run(proc, x, block=256):
    return np.concatenate([proc.process(x[i:i + block]) for i in range(0, x.shape[0], block)])


def rms_db(x):
    return lin_to_db(float(np.sqrt(np.mean(x ** 2))))


def test_autolevel_brings_quiet_and_loud_voices_to_target():
    for amp in (0.05, 0.4):
        y = run(AutoLevel(SR), voiced(6, amp=amp))
        assert abs(rms_db(y[-SR:]) - (-20.0)) < 3.0, (amp, rms_db(y[-SR:]))
    quiet = run(AutoLevel(SR), np.full(SR * 3, 1e-4, np.float32))    # silencio: no lo sube
    assert rms_db(quiet) < -70


def test_deesser_cuts_sibilants_but_not_vowels():
    v = voiced(2)
    s = sibilant(2, amp=0.2)
    dv = rms_db(run(DeEsser(SR), v)[SR // 2:]) - rms_db(v[SR // 2:])
    ds = rms_db(run(DeEsser(SR), s)[SR // 2:]) - rms_db(s[SR // 2:])
    assert abs(dv) < 0.5 and ds < -3.0


def test_polish_is_safe_and_wrapper_keeps_interface():
    x = np.concatenate([voiced(2, amp=0.9), sibilant(0.5, amp=0.9), voiced(2, amp=0.02)])
    y = run(Polish(SR, air=True), x)
    assert np.all(np.isfinite(y)) and np.max(np.abs(y)) <= 10 ** (-1 / 20) + 1e-6

    class Inner:
        kind, variant, infer_ms, latency_samples, closed = "instant", "120ms", 5.0, 100, False

        def process(self, b):
            return b * 0.5

        def close(self):
            Inner.closed = True
    w = PolishedAI(Inner(), SR)
    assert w.kind == "instant" and w.variant == "120ms" and w.infer_ms == 5.0
    assert w.latency_samples > 100
    out = run(w, voiced(1))
    assert out.shape[0] == SR and np.all(np.isfinite(out))
    w.close()
    assert Inner.closed
