"""Fase 2: cadena de efectos, preajustes, perfiles y escucha del original."""

import time
import zipfile

import numpy as np
import pytest

from fake_sd import FakeSD
from voicelab.api import Api
from voicelab.audio import devices as devmod
from voicelab.audio.devices import DeviceManager
from voicelab.audio.effects import (PRESETS, Reverb, Spectral, VoiceChain, change_speed, default_params,
                                    process_offline, sanitize, time_stretch)
from voicelab.audio.engine import AudioEngine
from voicelab.config import Settings
from voicelab.profiles import ProfileError, ProfileStore

SR = 48000


def tone(f, secs=1.0, amp=0.3):
    t = np.arange(int(SR * secs)) / SR
    return (amp * np.sin(2 * np.pi * f * t)).astype(np.float32)


def peak_freq(x):
    x = x[len(x) // 4:]
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return np.fft.rfftfreq(len(x), 1 / SR)[np.argmax(spec)]


def run(chain, x, block=256):
    return np.concatenate([chain.process(x[i:i + block]) for i in range(0, len(x), block)])


def test_neutral_chain_is_bit_exact_and_zero_latency():
    x = tone(300)
    ch = VoiceChain(SR)
    assert ch.latency_samples == 0
    assert np.array_equal(run(ch, x), x)


@pytest.mark.parametrize("semis,expected", [(12, 440), (-12, 110), (7, 329.6)])
def test_pitch_shift_accuracy(semis, expected):
    out = run(VoiceChain(SR, {"pitch": semis}), tone(220))
    assert peak_freq(out) == pytest.approx(expected, rel=0.02)


def test_spectral_latency_matches_declared_for_any_block_size():
    for block in (64, 100, 256, 1000):
        sp = Spectral(SR)
        sp.pitch_ratio = 1.0001
        x = np.zeros(SR // 2, np.float32)
        x[2000] = 1.0
        y = np.concatenate([sp.process(x[i:i + block]) for i in range(0, len(x), block)])
        assert len(y) == len(x)
        assert int(np.argmax(np.abs(y))) - 2000 == sp.latency


def test_formant_shift_moves_spectral_envelope_up():
    rng = np.random.default_rng(0)
    # Pulso glotal + resonancia a 700 Hz (vocal sintética)
    from scipy.signal import lfilter
    src = np.zeros(SR, np.float32)
    src[:: SR // 120] = 1.0
    r, w = 0.98, 2 * np.pi * 700 / SR
    vowel = lfilter([1], [1, -2 * r * np.cos(w), r * r], src).astype(np.float32) * 0.05
    def centroid(x):
        s = np.abs(np.fft.rfft(x[SR // 4:])) ** 2
        f = np.fft.rfftfreq(len(x[SR // 4:]), 1 / SR)
        return float((s * f).sum() / s.sum())
    base = centroid(run(VoiceChain(SR, {"pitch": 0.01}), vowel))
    up = centroid(run(VoiceChain(SR, {"formant": 6}), vowel))
    assert up > base * 1.2


def test_highpass_and_lowpass_attenuate():
    low, high = tone(50), tone(9000)
    hp = run(VoiceChain(SR, {"hpf_enabled": True, "hpf_hz": 300}), low)
    lp = run(VoiceChain(SR, {"lpf_enabled": True, "lpf_hz": 1500}), high)
    assert np.max(np.abs(hp[SR // 2:])) < 0.3 * 0.05
    assert np.max(np.abs(lp[SR // 2:])) < 0.3 * 0.05


def test_eq_band_boosts_its_frequency():
    out = run(VoiceChain(SR, {"eq5": 12}), tone(1000, amp=0.1))  # banda de 1 kHz
    assert np.max(np.abs(out[SR // 2:])) == pytest.approx(0.1 * 10 ** (12 / 20), rel=0.05)


def test_compressor_reduces_loud_signal():
    loud = tone(500, amp=0.9)
    out = run(VoiceChain(SR, {"comp_enabled": True, "comp_threshold": -30, "comp_ratio": 10}), loud)
    assert np.max(np.abs(out[SR // 2:])) < 0.2


def test_echo_repeats_after_delay():
    x = np.zeros(SR, np.float32)
    x[100] = 1.0
    out = run(VoiceChain(SR, {"echo_mix": 100, "echo_delay": 200, "echo_feedback": 50}), x, 64)
    d = int(0.2 * SR)
    assert out[100 + d] == pytest.approx(1.0, abs=1e-3)
    assert out[100 + 2 * d] == pytest.approx(0.5, abs=1e-3)


def test_reverb_matches_direct_convolution():
    from scipy.signal import fftconvolve
    rv = Reverb(SR)
    rv.configure(30, 40)
    rv.mix = 100.0
    x = np.random.default_rng(1).standard_normal(SR // 2).astype(np.float32)
    y = np.concatenate([rv.process(x[i:i + 300]) for i in range(0, len(x), 300)])
    g = rv.G2[: rv.G2.shape[0] // 2][::-1]
    ir = np.fft.irfft(g, axis=1)[:, :256].reshape(-1)
    ref = fftconvolve(x, ir)[: len(x)]
    wet = (y - 0.6 * x)[256:]
    assert np.max(np.abs(wet - ref[: len(wet)])) < 1e-4 * np.max(np.abs(ref))


def test_limiter_and_distortion_stay_bounded():
    out = run(VoiceChain(SR, {"gain": 24, "distortion": 100, "limiter_enabled": True, "limiter_ceiling": -6}), tone(200))
    assert np.max(np.abs(out)) <= 10 ** (-6 / 20) + 1e-6


@pytest.mark.parametrize("pid", list(PRESETS))
def test_every_preset_runs_and_changes_the_voice(pid):
    x = tone(180, 0.6)
    out = run(VoiceChain(SR, PRESETS[pid]["params"]), x)
    assert out.shape == x.shape and np.isfinite(out).all()
    assert np.max(np.abs(out - x)) > 0.01


def test_params_change_live_without_errors():
    ch = VoiceChain(SR)
    x = tone(200)
    outs = []
    for i, p in enumerate([{}, {"pitch": 4}, {"reverb_mix": 30}, {"robot": True}, {}]):
        ch.set_params(p)
        outs.append(run(ch, x[: SR // 5]))
    assert all(np.isfinite(o).all() for o in outs)


def test_sanitize_clamps_and_ignores_unknown():
    p = sanitize({"pitch": 99, "nope": 1, "robot": 1, "eq0": "x"})
    assert p["pitch"] == 12 and p["robot"] is True and "nope" not in p and p["eq0"] == 0


def test_offline_tools():
    x = tone(220, 1.0)
    assert len(time_stretch(x, 0.5)) / SR == pytest.approx(2.0, rel=0.05)
    assert peak_freq(time_stretch(x, 0.5)) == pytest.approx(220, rel=0.02)
    assert len(change_speed(x, 2.0)) == SR // 2
    out = process_offline(x, SR, {"pitch": 12})
    assert peak_freq(out[: SR]) == pytest.approx(440, rel=0.02)


# ------------------------------------------------------------------ perfiles
def test_profile_store_crud_export_import(tmp_path):
    store = ProfileStore(tmp_path / "p")
    a = store.create("Mi radio", effects=PRESETS["radio"]["params"], folder="Streaming")
    assert a["type"] == "effects" and a["effects"]["hpf_enabled"]
    b = store.duplicate(a["id"])
    assert b["name"] == "Mi radio (copia)"
    store.update(b["id"], {"name": "Otra", "favorite": True})
    assert store.list()[0]["name"] == "Otra"  # favoritos primero
    png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    assert store.set_avatar(a["id"], png)["avatar"].startswith("data:image/png")
    out = store.export(a["id"], tmp_path / "exp")
    imp = store.import_file(out)
    assert imp["name"] == "Mi radio" and imp["id"] != a["id"] and imp["avatar"]
    assert store.folders() == ["Streaming"]
    bk = store.backup(tmp_path / "bk")
    assert len(zipfile.ZipFile(bk).namelist()) >= 4
    store.delete(b["id"])
    with pytest.raises(ProfileError):
        store.get(b["id"])
    with pytest.raises(ProfileError):
        store.create("   ")


def test_import_rejects_path_traversal(tmp_path):
    bad = tmp_path / "bad.vlprofile"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("profile.json", "{}")
        z.writestr("../evil.txt", "x")
    with pytest.raises(ProfileError):
        ProfileStore(tmp_path / "p").import_file(bad)


# ------------------------------------------------------------ motor + API
@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr(devmod, "PLATFORM", "win32")
    sd = FakeSD()
    dm = DeviceManager(sd)
    eng = AudioEngine(dm)
    a = Api(Settings(tmp_path / "s.json"), dm, eng, sysinfo_fn=lambda: {}, profiles=ProfileStore(tmp_path / "p"))
    a.sd = sd
    yield a
    eng.stop()


def test_preset_applies_live_and_monitor_can_hear_original(api):
    api.update_settings({"audio": {"monitor_enabled": True, "monitor_device": "Auriculares (USB Headset)",
                                   "monitor_source": "original"}})
    assert api.start_engine()["ok"]
    r = api.apply_preset("aguda")
    assert r["ok"] and r["settings"]["voice"]["preset"] == "aguda"
    time.sleep(0.8)
    st = api.get_status()
    assert st["routes"]["monitor"]["source"] == "original"
    assert st["voice_latency_ms"] == pytest.approx(1024 / 48, abs=0.1)
    api.stop_engine()
    cable = api.sd.outputs_for("CABLE Input (VB-Audio Virtual Cable)")[0].output()[SR // 2:]
    mon = api.sd.outputs_for("Auriculares (USB Headset)")[0].output()[SR // 2:]
    assert peak_freq(mon) == pytest.approx(220, rel=0.02)              # original
    assert peak_freq(cable) == pytest.approx(220 * 2 ** (5 / 12), rel=0.03)  # +5 semitonos


def test_voice_params_merge_and_profiles_via_api(api):
    api.set_voice_params({"pitch": -3})
    r = api.set_voice_params({"reverb_mix": 20})
    p = r["settings"]["voice"]["params"]
    assert p["pitch"] == -3 and p["reverb_mix"] == 20
    c = api.create_profile({"name": "Narrador", "folder": "Vídeos"})
    pid = c["result"]["id"]
    assert c["ok"] and c["result"]["effects"]["pitch"] == -3
    api.reset_voice()
    act = api.activate_profile(pid)
    assert act["settings"]["voice"]["params"]["pitch"] == -3 and act["settings"]["voice"]["profile_id"] == pid
    assert api.delete_profile(pid)["ok"]
    assert api.list_profiles()["profiles"] == []
    assert not api.apply_preset("no-existe")["ok"]
    assert len(api.get_effects_schema()["presets"]) == 11
