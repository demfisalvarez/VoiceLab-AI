"""Voz instantánea en directo (MeanVC2): todo lo que rodea al modelo.

PyTorch y los pesos no se pueden descargar en el entorno de pruebas, así que
se usa un proceso simulado con el mismo protocolo. Se comprueba: remuestreo
en streaming, protocolo, gestión del proceso y sus errores, el colchón de
tiempo real con el patrón de ráfagas del modelo, la caché de la huella de
voz, las descargas con réplicas y la integración con la API y el motor.
"""

import hashlib
import io
import json
import py_compile
import re
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from voicelab.ai import meanvc, models
from voicelab.ai import meanvc_worker as proto
from voicelab.audio import mediaio
from voicelab.audio.resampler import StreamResampler

ROOT = Path(__file__).resolve().parents[1]
FAKE = Path(__file__).with_name("fake_meanvc_worker.py")
SR = 48000


def fake_cmd(*_a, **_k):
    return [sys.executable, "-I", str(FAKE)]


def sine(freq, seconds, sr, amp=0.3):
    t = np.arange(int(seconds * sr)) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def sine_fit_error(y, freq, sr):
    """Error relativo de ajustar ``y`` a una senoide pura de ``freq``."""
    t = np.arange(y.shape[0]) / sr
    a = np.stack([np.sin(2 * np.pi * freq * t), np.cos(2 * np.pi * freq * t), np.ones_like(t)], 1)
    coef, *_ = np.linalg.lstsq(a, y, rcond=None)
    amp = float(np.hypot(coef[0], coef[1]))
    return float(np.sqrt(np.mean((y - a @ coef) ** 2)) / max(amp, 1e-9)), amp


# ------------------------------------------------------------ remuestreo
@pytest.mark.parametrize("src,dst", [(48000, 16000), (16000, 48000), (44100, 16000), (16000, 44100)])
def test_stream_resampler_chunked_equals_whole_and_keeps_tone(src, dst):
    rng = np.random.default_rng(3)
    x = sine(330, 1.5, src) + 0.01 * rng.standard_normal(int(1.5 * src)).astype(np.float32)
    whole = StreamResampler(src, dst).process(x)
    r, parts, i = StreamResampler(src, dst), [], 0
    while i < x.shape[0]:
        n = int(rng.integers(1, 4000))
        parts.append(r.process(x[i:i + n]))
        i += n
    chunked = np.concatenate(parts)
    assert chunked.shape == whole.shape
    assert abs(whole.shape[0] - x.shape[0] * dst / src) <= 1
    np.testing.assert_allclose(chunked, whole, atol=1e-6)
    err, amp = sine_fit_error(whole[dst // 4: -dst // 4], 330, dst)
    assert err < 0.05 and amp == pytest.approx(0.3, rel=0.02)
    assert r.delay_s < 0.002


# ------------------------------------------------------------- protocolo
def test_protocol_roundtrip():
    buf = io.BytesIO()
    proto.send(buf, b"A", np.arange(5, dtype=np.float32).tobytes())
    proto.send_json(buf, {"ok": True, "texto": "ñ"})
    proto.send(buf, b"Z")
    buf.seek(0)
    k, d = proto.recv(buf)
    assert k == b"A" and np.frombuffer(d, np.float32).tolist() == [0, 1, 2, 3, 4]
    k, d = proto.recv(buf)
    assert k == b"J" and json.loads(d) == {"ok": True, "texto": "ñ"}
    assert proto.recv(buf) == (b"Z", b"")
    with pytest.raises(EOFError):
        proto.recv(buf)


def test_vendored_code_compiles_and_matches_expected_files():
    code = meanvc.code_dir()
    for f in code.rglob("*.py"):
        py_compile.compile(str(f), doraise=True)
    src = (code / "runtime" / "run_rt.py").read_text(encoding="utf-8")
    for variant, files in proto.WEIGHT_FILES.items():
        for f in files[:2]:
            assert f in src, f
    for cfg in re.findall(r'src/config/(config_\w+\.json)', src):
        assert (code / "src" / "config" / cfg).exists()
    assert (code / "LICENSE-APACHE-2.0.txt").exists() and (code / "NOTICE.md").exists()
    assert set(models.CATALOG["meanvc2"]["files"]) >= {f for fs in proto.WEIGHT_FILES.values() for f in fs}


def test_real_worker_reports_missing_pytorch_cleanly(tmp_path):
    """El proceso real, sin PyTorch, avisa con un mensaje (y nada ensucia el canal)."""
    try:
        import torch  # noqa: F401
        pytest.skip("PyTorch está instalado aquí")
    except ImportError:
        pass
    cmd = [sys.executable, "-I", str(meanvc.worker_script()), "--code", str(meanvc.code_dir()),
           "--weights", str(tmp_path)]
    with pytest.raises(meanvc.WorkerError, match="torch|Faltan archivos"):
        meanvc.MeanVCWorker(cmd, start_timeout=60)


# -------------------------------------------------------------- el proceso
def test_worker_lifecycle_and_errors(monkeypatch):
    w = meanvc.MeanVCWorker(fake_cmd())
    assert w.alive and w.hello["torch"] == "simulado"
    with pytest.raises(meanvc.WorkerError, match="voz de destino"):
        w.process(np.zeros(meanvc.CHUNK16, np.float32))
    emb = w.compute_embedding(np.full(16000, 0.5, np.float32))
    assert emb.shape == (256,) and emb[0] == pytest.approx(0.5)
    w.set_embedding(emb)
    out = w.process(np.ones(meanvc.CHUNK16, np.float32))
    assert out.shape == (1920,) and np.all(out == 1.0)
    w.reset()
    w.close()
    assert not w.alive

    monkeypatch.setenv("FAKE_MVC_FAIL_START", "1")
    with pytest.raises(meanvc.WorkerError, match="torch"):
        meanvc.MeanVCWorker(fake_cmd())


def test_worker_crash_is_reported(monkeypatch):
    monkeypatch.setenv("FAKE_MVC_DIE_AFTER", "2")
    w = meanvc.MeanVCWorker(fake_cmd())
    w.set_embedding(np.zeros(256, np.float32))
    w.process(np.zeros(meanvc.CHUNK16, np.float32))
    w.process(np.zeros(meanvc.CHUNK16, np.float32))
    with pytest.raises(meanvc.WorkerError, match="se ha cerrado"):
        w.process(np.zeros(meanvc.CHUNK16, np.float32))
    w.close()


def test_worker_start_timeout(tmp_path):
    hang = tmp_path / "hang.py"
    hang.write_text("import time\ntime.sleep(30)\n")
    t0 = time.time()
    with pytest.raises(meanvc.WorkerError, match="a tiempo"):
        meanvc.MeanVCWorker([sys.executable, str(hang)], start_timeout=1.0)
    assert time.time() - t0 < 10


# --------------------------------------------------- tiempo real (motor)
def run_realtime(proc, x, block=480, sr=SR):
    """Alimenta el procesador a ritmo real, como el motor de audio."""
    outs, t0 = [], time.perf_counter()
    for k, i in enumerate(range(0, x.shape[0], block)):
        outs.append(proc.process(x[i:i + block]))
        wait = t0 + (k + 1) * block / sr - time.perf_counter()
        if wait > 0:
            time.sleep(wait)
    return np.concatenate(outs)


def test_realtime_meanvc_is_continuous_with_bursty_model():
    w = meanvc.MeanVCWorker(fake_cmd())
    w.set_embedding(np.zeros(256, np.float32))
    proc = meanvc.RealtimeMeanVC(w, SR, "120ms")
    x = sine(330, 3.0, SR)
    y = run_realtime(proc, x)
    first = int(np.argmax(np.abs(y) > 0.05))
    assert 0.15 * SR < first < 0.6 * SR                      # empieza tras el colchón, no antes
    tail = y[int(1.8 * SR):]
    assert np.max(np.abs(tail)) > 0.25
    silent = np.abs(tail) < 1e-6
    longest = max((len(r) for r in "".join("1" if v else "0" for v in silent).split("0")), default=0)
    assert longest < 3                                       # sin huecos en la parte estable
    err, amp = sine_fit_error(tail, 330, SR)
    assert err < 0.05 and amp == pytest.approx(0.3, rel=0.05)
    assert proc.underruns <= 3
    lat = proc.latency_samples / SR
    assert 0.25 < lat < 0.8
    assert proc.error is None and proc.infer_ms > 0
    proc.close()
    time.sleep(0.3)
    assert not w.alive


def test_realtime_meanvc_reports_worker_death(monkeypatch):
    monkeypatch.setenv("FAKE_MVC_DIE_AFTER", "3")
    w = meanvc.MeanVCWorker(fake_cmd())
    w.set_embedding(np.zeros(256, np.float32))
    proc = meanvc.RealtimeMeanVC(w, SR, "120ms")
    y = run_realtime(proc, sine(330, 1.5, SR))
    assert proc.error and "cerrado" in proc.error
    assert np.all(y[-SR // 4:] == 0)                          # silencio, nunca la voz original
    proc.close()


# ------------------------------------------------------- huella de voz
def test_profile_embedding_is_cached_and_invalidated(tmp_path):
    d = tmp_path / "perfil"
    d.mkdir()
    mediaio.save_wav(d / "reference.wav", sine(160, 5.0, SR, 0.4), SR)
    w = meanvc.MeanVCWorker(fake_cmd())
    try:
        e1 = meanvc.profile_embedding(w, d)
        assert (d / meanvc.EMB_FILE).exists()

        class NoCalls:
            def compute_embedding(self, _a):
                raise AssertionError("debería usar la huella guardada")
        np.testing.assert_allclose(meanvc.profile_embedding(NoCalls(), d), e1)
        time.sleep(1.1)
        mediaio.save_wav(d / "reference.wav", sine(160, 5.0, SR, 0.1), SR)   # otra referencia
        assert meanvc.cached_embedding(d) is None
        e2 = meanvc.profile_embedding(w, d)
        assert e2[0] < e1[0]
        short = tmp_path / "corto"
        short.mkdir()
        mediaio.save_wav(short / "reference.wav", sine(160, 1.0, SR), SR)
        with pytest.raises(meanvc.WorkerError, match="corta"):
            meanvc.profile_embedding(w, short)
    finally:
        w.close()


# ------------------------------------------------- descargas con réplicas
class _Resp(io.BytesIO):
    def __init__(self, data: bytes, status=200, headers=None):
        super().__init__(data)
        self.status, self.headers = status, headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *e):
        pass


def test_model_install_uses_mirrors_pagination_and_sha(monkeypatch):
    blobs = {f: (f * 3).encode() for f in models.CATALOG["meanvc2"]["files"]}
    spk = b"pesos-del-hablante" * 10
    trees = {
        "ASLP-lab/MeanVC2": [[{"type": "file", "path": f, "size": len(b),
                                "lfs": {"oid": hashlib.sha256(b).hexdigest()}} for f, b in list(blobs.items())[:3]],
                              [{"type": "file", "path": f, "size": len(b),
                                "lfs": {"oid": hashlib.sha256(b).hexdigest()}} for f, b in list(blobs.items())[3:]]],
        "Dongchao/UniAudio": [[{"type": "file", "path": "otro.bin", "size": 1}]],
        "subatomicseer/wavlm-large-sv-ckpts": [[{"type": "file", "path": "wavlm_large_finetune.pth", "size": len(spk),
                                                  "lfs": {"oid": hashlib.sha256(spk).hexdigest()}}]],
    }
    seen = []

    def urlopen(req, timeout=None, context=None):
        url = req.full_url
        seen.append(url)
        m = re.match(r"https://huggingface\.co/api/models/(.+?)/tree/main(\?page=(\d+))?$", url)
        if m:
            pages = trees.get(m.group(1))
            if pages is None:
                raise OSError("404")
            i = int(m.group(3) or 0)
            link = f'<https://huggingface.co/api/models/{m.group(1)}/tree/main?page={i + 1}>; rel="next"' if i + 1 < len(pages) else ""
            return _Resp(json.dumps(pages[i]).encode(), headers={"Link": link})
        m = re.match(r"https://huggingface\.co/(.+?)/resolve/main/(.+)$", url)
        name = m.group(2)
        return _Resp(spk if name == "wavlm_large_finetune.pth" else blobs[name])

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    prog = []
    assert models.install("meanvc2", prog.append)["installed"]
    d = models.model_dir("meanvc2")
    assert (d / "wavlm_large_finetune.pth").read_bytes() == spk
    assert all((d / f).read_bytes() == b for f, b in blobs.items())
    assert any("subatomicseer" in u and "resolve" in u for u in seen)
    assert prog[-1] == 1.0 and models.installed("meanvc2")

    # un archivo corrupto no se acepta
    models.remove("meanvc2")
    blobs["vocos.pt"] = b"manipulado"
    with pytest.raises(RuntimeError, match="SHA-256|incompleta"):
        models.install("meanvc2", lambda p: None)
    assert not models.installed("meanvc2")


# ------------------------------------------------------- API y motor
@pytest.fixture
def api(monkeypatch, tmp_path):
    from fake_sd import FakeSD
    from voicelab.api import Api
    from voicelab.audio import devices as devmod
    from voicelab.audio.devices import DeviceManager
    from voicelab.audio.engine import AudioEngine
    from voicelab.config import Settings
    monkeypatch.setattr(devmod, "PLATFORM", "win32")
    monkeypatch.setattr(meanvc, "installed", lambda: True)
    monkeypatch.setattr(meanvc, "worker_command", fake_cmd)
    dm = DeviceManager(FakeSD())
    eng = AudioEngine(dm)
    a = Api(Settings(tmp_path / "s.json"), dm, eng, sysinfo_fn=lambda: {})
    yield a
    eng.stop()
    if eng.ai is not None:
        eng.set_ai(None)


def wait_job(api, res):
    jid = res["job"]
    for _ in range(300):
        j = api.get_job(jid)["job"]
        if j["state"] != "running":
            return j
        time.sleep(0.02)
    raise AssertionError("la tarea no terminó")


def make_instant(api, name):
    prof = api._profiles.create(name, "instant", "", "", {})  # noqa: SLF001
    mediaio.save_wav(api._profiles.path(prof["id"]) / "reference.wav", sine(150, 6.0, SR, 0.3), SR)  # noqa: SLF001
    return prof["id"]


def test_api_live_instant_voice_flow(api):
    p1, p2 = make_instant(api, "Voz uno"), make_instant(api, "Voz dos")
    assert api.ai_status()["ai"]["live"]["installed"]
    r = api.activate_profile(p1)
    assert r["ok"] and "job" not in r                        # motor apagado: se carga al encender
    r = api.start_engine()
    assert r["ok"] and r["job"]
    j = wait_job(api, r)
    assert j["state"] == "done", j
    from voicelab.audio.polish import PolishedAI
    wrapped = api._engine.ai  # noqa: SLF001
    assert isinstance(wrapped, PolishedAI) and wrapped.clean is not None and wrapped.post is not None
    proc = wrapped.inner
    assert isinstance(proc, meanvc.RealtimeMeanVC) and proc.variant == "120ms"
    time.sleep(0.6)
    st = api.get_status()["ai"]
    assert st["kind"] == "instant" and st["error"] is None and st["latency_ms"] > 200
    assert (api._profiles.path(p1) / meanvc.EMB_FILE).exists()  # noqa: SLF001

    pid = proc.w.proc.pid                                     # otra voz instantánea: mismo proceso
    j = wait_job(api, api.activate_profile(p2))
    assert j["state"] == "done" and api._engine.ai.inner is proc and proc.w.proc.pid == pid  # noqa: SLF001
    assert proc.error is None and proc.w.alive

    wait_job(api, api.update_settings({"voice": {"ai_polish": False, "ai_clean_input": False}}))
    assert api._engine.ai is proc and proc.w.alive               # sin acabado: el mismo modelo, sin envoltura  # noqa: SLF001
    wait_job(api, api.update_settings({"voice": {"ai_polish": True}}))
    assert api._engine.ai.inner is proc and api._engine.ai.clean is None  # noqa: SLF001

    r = api.update_settings({"ai": {"meanvc_variant": "40ms"}})   # otro modo: proceso nuevo
    assert r["ok"] and r["job"]
    wait_job(api, r)
    assert api._engine.ai.inner is not proc and api._engine.ai.variant == "40ms"  # noqa: SLF001

    r = api.update_settings({"voice": {"instant_live": False}})
    assert r["ok"] and api._engine.ai is None                 # noqa: SLF001
    r = api.update_settings({"voice": {"instant_live": True}})
    wait_job(api, r)
    assert api._engine.ai is not None                         # noqa: SLF001

    api.apply_preset(next(iter(__import__("voicelab.audio.effects", fromlist=["x"]).PRESETS)))
    assert api._engine.ai is None                             # noqa: SLF001
    wait_job(api, api.activate_profile(p1))
    assert api._engine.ai is not None                         # noqa: SLF001
    api.stop_engine()
    assert api._engine.ai is None                             # noqa: SLF001


def test_api_stale_load_is_discarded(api):
    """Si el usuario cambia de voz mientras otra se carga, gana la última."""
    p1 = make_instant(api, "Lenta")
    api.activate_profile(p1)
    r = api.start_engine()
    api.reset_voice()                                         # antes de que termine la carga
    wait_job(api, r)
    assert api._engine.ai is None                             # noqa: SLF001


def test_live_disabled_when_not_installed(api, monkeypatch):
    monkeypatch.setattr(meanvc, "installed", lambda: False)
    p1 = make_instant(api, "Sin motor")
    api.start_engine()
    r = api.activate_profile(p1)
    assert r["ok"] and "job" not in r and api._engine.ai is None  # noqa: SLF001


# ------------------------------------------------------------ instalación
def test_install_runtime_uses_private_uv_and_cpu_torch(tmp_path, monkeypatch):
    root = tmp_path / "VoiceLab AI"
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "uv.exe").write_text("")
    monkeypatch.setattr(meanvc, "_app_root", lambda: root)
    monkeypatch.delenv("VOICELAB_VC_RUNTIME", raising=False)
    cmds = []

    def run(cmd, what, env=None):
        cmds.append(cmd)
        if "venv" in cmd:
            meanvc.runtime_python().parent.mkdir(parents=True, exist_ok=True)
            meanvc.runtime_python().write_text("")
    monkeypatch.setattr(meanvc, "_run", run)
    meanvc.install_runtime(lambda p: None)
    assert meanvc.runtime_dir() == root / "vc-runtime"           # se borra al desinstalar la app
    assert cmds[0][:3] == [str(root / "bin" / "uv.exe"), "venv", "--no-config"]
    assert cmds[1][1:4] == ["pip", "install", "--no-config"] and "--no-cache" in cmds[1]
    assert all(pkg in cmds[1] for pkg in meanvc.packages()) and "x-transformers==2.2.11" in cmds[1]
    assert "torch==2.5.1" in meanvc.packages((3, 12)) and "torch==2.6.0" in meanvc.packages((3, 13))
    assert meanvc.runtime_ready()


def test_install_downloads_then_benchmarks(monkeypatch):
    def fake_models_install(key, progress):
        d = models.model_dir(key)
        d.mkdir(parents=True, exist_ok=True)
        (d / ".complete").write_text("{}")
        progress(1.0)
    monkeypatch.setattr(meanvc, "runtime_ready", lambda: True)
    monkeypatch.setattr(models, "install", fake_models_install)
    monkeypatch.setattr(meanvc, "worker_command", fake_cmd)
    prog = []
    res = meanvc.install(prog.append)
    assert res["installed"] and res["bench"]["chunk_ms"] == 160.0 and res["bench"]["torch"] == "simulado"
    assert meanvc.bench() == res["bench"] and meanvc.installed()
    assert prog == sorted(prog) and prog[-1] == 1.0


def test_frozen_build_uses_bundled_uv_and_managed_python(tmp_path, monkeypatch):
    exe_dir = tmp_path / "VoiceLab AI"
    exe_dir.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "VoiceLab AI.exe"))
    monkeypatch.delenv("VOICELAB_VC_RUNTIME", raising=False)
    assert meanvc.status()["supported"] is False               # sin uv no se puede
    with pytest.raises(RuntimeError, match="uv"):
        meanvc.install(lambda p: None)
    (exe_dir / "bin").mkdir()
    (exe_dir / "bin" / "uv.exe").write_text("")
    assert not meanvc.supported()                               # ni sin su Python base
    (exe_dir / "pybase").mkdir()
    (exe_dir / "pybase" / "python.exe").write_text("")
    (exe_dir / "vc-python").mkdir()                             # resto de la v0.7.0: se borra
    assert meanvc.supported() and meanvc.runtime_dir() == exe_dir / "vc-runtime"
    calls = []

    def run(cmd, what, env=None):
        calls.append((cmd, env))
        if "venv" in cmd:
            meanvc.runtime_python().parent.mkdir(parents=True, exist_ok=True)
            meanvc.runtime_python().write_text("")
    monkeypatch.setattr(meanvc, "_run", run)
    meanvc.install_runtime(lambda p: None)
    venv_cmd, env = calls[0]
    assert venv_cmd[venv_cmd.index("--python") + 1] == str(exe_dir / "pybase" / "python.exe")
    assert env["UV_PYTHON_DOWNLOADS"] == "never" and "UV_PYTHON_INSTALL_DIR" not in env
    assert not (exe_dir / "vc-python").exists()
    assert "torch==2.5.1" in calls[1][0]                       # Python 3.12 → PyTorch 2.5.1
