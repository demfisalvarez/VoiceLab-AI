import numpy as np
import pytest

from voicelab.audio.dsp import (LevelMeter, NoiseGate, SafetyLimiter, SmoothedGain, db_to_lin, downmix,
                                lin_to_db, make_test_tone)

SR = 48000


def sine(amp, n, f=440.0, sr=SR):
    return (amp * np.sin(2 * np.pi * f * np.arange(n) / sr)).astype(np.float32)


def test_db_conversions():
    assert db_to_lin(0) == pytest.approx(1.0)
    assert db_to_lin(-6) == pytest.approx(0.501, abs=1e-3)
    assert lin_to_db(1.0) == pytest.approx(0.0)
    assert lin_to_db(0.0) == -120.0


def test_smoothed_gain_ramps_without_jumps():
    g = SmoothedGain(0.0)
    x = np.ones(256, np.float32)
    assert g.process(x) is x  # ganancia unidad: sin copia
    g.set_db(-6.0)
    y = g.process(x)
    assert y[0] == pytest.approx(1.0)
    assert np.all(np.diff(y) <= 0)  # rampa monótona
    assert np.max(np.abs(np.diff(y))) < 0.01
    z = g.process(x)
    assert np.allclose(z, db_to_lin(-6.0))
    g.set_muted(True)
    g.process(x)
    assert np.allclose(g.process(x), 0.0)


def test_noise_gate_closes_on_noise_and_opens_on_voice():
    gate = NoiseGate(SR, threshold_db=-40.0, enabled=True, hold_ms=20, release_ms=30)
    noise = (np.random.default_rng(0).standard_normal(256) * 0.001).astype(np.float32)  # ~ -60 dB
    for _ in range(60):
        out = gate.process(noise)
    assert not gate.is_open
    assert np.max(np.abs(out)) < 1e-4  # atenuado más de 20 dB
    voice = sine(0.3, 256)
    gate.process(voice)
    assert gate.is_open
    out = gate.process(voice)
    assert np.max(np.abs(out)) > 0.25


def test_noise_gate_disabled_is_transparent():
    gate = NoiseGate(SR, enabled=False)
    x = sine(0.001, 256)
    assert gate.process(x) is x


@pytest.mark.parametrize("amp", [0.5, 1.5, 4.0, 20.0])
def test_limiter_never_exceeds_ceiling(amp):
    lim = SafetyLimiter(SR, ceiling_db=-1.0)
    ceiling = db_to_lin(-1.0)
    rng = np.random.default_rng(1)
    worst = 0.0
    for _ in range(200):
        out = lim.process((rng.standard_normal(256) * amp).astype(np.float32))
        worst = max(worst, float(np.max(np.abs(out))))
    assert worst <= ceiling + 1e-6


def test_limiter_transparent_for_quiet_signal():
    lim = SafetyLimiter(SR)
    x = sine(0.3, 256)
    assert np.allclose(lim.process(x), x)
    assert not lim.active


def test_level_meter_reports_peak_rms_and_clip():
    m = LevelMeter()
    m.update(sine(0.5, 4800))
    r = m.read()
    assert r["peak_db"] == pytest.approx(-6.0, abs=0.1)
    assert r["rms_db"] == pytest.approx(-9.0, abs=0.1)
    assert r["clip"] is False
    m.update(np.ones(10, np.float32))
    assert m.read()["clip"] is True
    assert m.read()["peak_db"] == -120.0  # sin datos nuevos


def test_downmix_modes():
    x = np.stack([np.ones(4, np.float32), np.zeros(4, np.float32)], axis=1)
    assert np.allclose(downmix(x, "mix"), 0.5)
    assert np.allclose(downmix(x, "left"), 1.0)
    assert np.allclose(downmix(x, "right"), 0.0)
    mono = np.ones((4, 1), np.float32)
    assert np.allclose(downmix(mono, "right"), 1.0)


def test_test_tone():
    tone = make_test_tone(SR, level_db=-14.0)
    assert 0.5 < tone.shape[0] / SR < 0.7
    assert np.max(np.abs(tone)) <= db_to_lin(-14.0) + 1e-6
    assert tone.dtype == np.float32
