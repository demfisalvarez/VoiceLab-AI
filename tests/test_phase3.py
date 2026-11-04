"""Fase 3 (sin IA) y editor: medios, análisis, limpieza, espacio de trabajo y perfiles de voz."""

import shutil
import subprocess
import time

import numpy as np
import pytest

from fake_sd import FakeSD
from voicelab.api import Api
from voicelab.audio import analysis, devices as devmod, mediaio
from voicelab.audio.devices import DeviceManager
from voicelab.audio.engine import AudioEngine
from voicelab.config import Settings
from voicelab.profiles import ProfileStore
from voicelab.workspace import SR, Jobs, Workspace

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sin FFmpeg")


def speechlike(seconds=20.0, noise=0.003, seed=0):
    """Ráfagas armónicas tipo sílaba (120–220 Hz) separadas por pausas + ruido."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(SR * seconds)) / SR
    env = ((np.sin(2 * np.pi * 2.3 * t) > -0.2) & ((t % 3.0) < 2.4)).astype(np.float32)
    f0 = 160 + 50 * np.sin(2 * np.pi * 0.3 * t)
    ph = 2 * np.pi * np.cumsum(f0) / SR
    voice = sum(np.sin(k * ph) / k for k in range(1, 8)) * 0.15
    return (voice * env + rng.standard_normal(t.size) * noise).astype(np.float32)


@needs_ffmpeg
def test_video_audio_extraction_and_formats(tmp_path):
    mp4 = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:duration=3",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=3", "-shortest", "-c:v", "mpeg4", "-c:a", "aac", str(mp4)], check=True)
    info = mediaio.probe(mp4)
    assert info["video"] and info["audio"] and info["duration"] == pytest.approx(3, abs=0.2)
    x = mediaio.load_audio(mp4)
    assert x.shape[0] / SR == pytest.approx(3, abs=0.15)
    spec = np.abs(np.fft.rfft(x[SR // 2: SR // 2 + SR]))
    assert np.argmax(spec) == pytest.approx(440, abs=2)  # 1 Hz por bin
    for fmt in ("wav", "mp3", "flac", "ogg"):
        out = mediaio.export(tmp_path / "o", x, SR, fmt)
        back = mediaio.load_audio(out)
        assert back.shape[0] / SR == pytest.approx(3, abs=0.15), fmt


@needs_ffmpeg
def test_video_without_audio_is_reported(tmp_path):
    mp4 = tmp_path / "mudo.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=1", "-c:v", "mpeg4", str(mp4)], check=True)
    assert mediaio.probe(mp4)["audio"] is False
    with pytest.raises(mediaio.MediaError, match="audio"):
        mediaio.load_audio(mp4)


def test_wav_roundtrip_and_resample(tmp_path):
    x = speechlike(2)[: 2 * 44100]          # 2 s a 44,1 kHz
    p = mediaio.save_wav(tmp_path / "a.wav", x, 44100)
    y = mediaio.load_audio(p, SR)
    assert y.shape[0] == pytest.approx(2 * SR, abs=5)


def test_analysis_tiers_and_warnings():
    short = analysis.analyze(speechlike(6), SR)
    assert short["tier"] == "insufficient"
    ok = analysis.analyze(speechlike(25), SR)
    assert ok["tier"] == "instant" and ok["snr_db"] > 20
    assert ok["f0_median"] == pytest.approx(160, abs=30)
    noisy = analysis.analyze(speechlike(25, noise=0.05), SR)
    assert noisy["snr_db"] < ok["snr_db"] and any("ruido" in w for w in noisy["warnings"])


def test_denoise_improves_snr():
    x = speechlike(15, noise=0.02)
    before = analysis.analyze(x, SR)["snr_db"]
    after = analysis.analyze(analysis.denoise(x, SR, 0.8), SR)["snr_db"]
    assert after > before + 6


def test_remove_silences_shortens_pauses():
    x = np.concatenate([speechlike(2), np.zeros(SR * 3, np.float32), speechlike(2)])
    y = analysis.remove_silences(x, SR)
    assert y.shape[0] < x.shape[0] - 2 * SR


def test_workspace_edit_undo_split_join(tmp_path):
    ws = Workspace(tmp_path / "w")
    m = ws.create(speechlike(10), "voz", "import")
    noop = lambda p: None  # noqa: E731
    ws.apply(m["id"], "crop", {"start": 2, "end": 6}, noop)
    assert ws.meta(m["id"])["duration"] == pytest.approx(4)
    ws.apply(m["id"], "gain", {"db": -6}, noop)
    ws.apply(m["id"], "tempo", {"rate": 0.5}, noop)
    assert ws.meta(m["id"])["duration"] == pytest.approx(8, abs=0.3)
    ws.undo(m["id"])
    ws.undo(m["id"])
    assert ws.meta(m["id"])["duration"] == pytest.approx(4)
    second = ws.split(m["id"], 1.5)
    assert ws.meta(m["id"])["duration"] == pytest.approx(1.5) and second["duration"] == pytest.approx(2.5)
    joined = ws.join([m["id"], second["id"]])
    assert joined["duration"] == pytest.approx(4.15, abs=0.01)
    ws.apply(m["id"], "effects", {"params": {"pitch": 5}}, noop)
    assert len(ws.list()) == 3
    ws.delete(second["id"])
    assert len(ws.list()) == 2


def test_jobs_report_progress_and_errors():
    jobs = Jobs()
    ok = jobs.run("ok", lambda p: (p(0.5), 42)[1])
    bad = jobs.run("mal", lambda p: (_ for _ in ()).throw(ValueError("fallo claro")))
    time.sleep(0.2)
    assert jobs.get(ok)["state"] == "done" and jobs.get(ok)["result"] == 42
    assert jobs.get(bad)["state"] == "error" and jobs.get(bad)["error"] == "fallo claro"


# ----------------------------------------------------------------------- API
@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr(devmod, "PLATFORM", "win32")
    monkeypatch.setenv("VOICELAB_DATA_DIR", str(tmp_path / "data"))
    sd = FakeSD()
    sd.signal = lambda t: speechlike(len(t) / SR + 0.01)[: len(t)] * 2
    a = Api(Settings(tmp_path / "s.json"), DeviceManager(sd), AudioEngine(DeviceManager(sd)),
            sysinfo_fn=lambda: {}, profiles=ProfileStore(tmp_path / "p"))
    yield a
    a._engine.stop()


def wait(api, res, timeout=30):
    jid = res["job"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = api.get_job(jid)["job"]
        if j["state"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError("tarea sin terminar")


def test_record_play_analyze_and_create_instant_profile(api):
    assert api.start_recording()["ok"]
    time.sleep(1.2)
    assert api.playback_status()["recorder"]["recording"]
    rec = api.stop_recording("Mi grabación")
    assert rec["ok"] and rec["item"]["duration"] == pytest.approx(1.2, abs=0.3)
    # Material suficiente: un elemento de 25 s
    item = api._ws().create(speechlike(25), "entrevista", "import", "entrevista.mp4")
    an = wait(api, api.analyze_item(item["id"], 0, 25))
    assert an["state"] == "done" and an["result"]["tier"] == "instant"
    assert not api.create_voice_profile({"item_id": item["id"], "name": "Ana"})["ok"]  # sin consentimiento
    job = wait(api, api.create_voice_profile({"item_id": item["id"], "start": 0, "end": 25, "name": "Ana",
                                              "consent_authorized": True, "language": "es"}))
    assert job["state"] == "done", job["error"]
    prof = job["result"]
    assert prof["type"] == "instant" and prof["has_reference"] and prof["cloning"]["consent"] == "authorized"
    ref = mediaio.load_audio(api._profiles.path(prof["id"]) / "reference.wav")
    assert 8 < ref.shape[0] / SR <= 20.5
    # Fragmento demasiado corto
    j2 = wait(api, api.create_voice_profile({"item_id": item["id"], "start": 0, "end": 4, "name": "x", "consent_own": True}))
    assert j2["state"] == "error" and "10 s" in j2["error"]
    assert api.play_item(item["id"], 1, 2)["ok"]
    time.sleep(0.3)
    assert api.playback_status()["player"]["position"] > 1.0
    api.stop_playback()


@needs_ffmpeg
def test_export_job(api, tmp_path, monkeypatch):
    monkeypatch.setattr("voicelab.paths.documents_dir", lambda: tmp_path / "docs")
    item = api._ws().create(speechlike(3), "clip", "import")
    j = wait(api, api.export_item(item["id"], "mp3", 0, 2))
    assert j["state"] == "done" and j["result"]["path"].endswith(".mp3")
    assert mediaio.load_audio(j["result"]["path"]).shape[0] / SR == pytest.approx(2, abs=0.1)
