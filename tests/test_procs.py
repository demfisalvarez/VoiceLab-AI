"""Modelos en proceso aparte: la ventana no puede congelarse ni caerse por ellos."""
import time

import numpy as np
import pytest

from voicelab.ai import procs, rvc, tts
from voicelab.ai.procs import Remote, RemoteError


def remote(mode, **kw):
    return Remote("fake_remote_obj:make", (mode,), name="motor de prueba", log_name="prueba", **kw)


def test_remote_loads_calls_and_reports_progress():
    stages = []
    r = remote("cpu", on_stage=stages.append)
    try:
        assert stages == ["cargando 1/2", "cargando 2/2"] and r.info["device"] == "cpu" and r.alive
        prog = []
        out = r.call("work", 20, progress=prog.append)
        assert out.tolist() == list(range(20)) and len(prog) == 20
        with pytest.raises(RemoteError, match="algo ha ido mal"):
            r.call("boom")
        assert r.alive                                     # un error no tumba el proceso
        assert r.call("work", 3).tolist() == [0, 1, 2]
    finally:
        r.close()
    assert not r.alive


def test_remote_load_failures_become_messages():
    with pytest.raises(RemoteError, match="GPU \\(DirectML\\) ha fallado"):
        remote("fail_load")
    with pytest.raises(RemoteError, match="cerrado inesperadamente") as e:
        remote("crash_load")
    assert e.value.kind == "crash"
    t0 = time.time()
    with pytest.raises(RemoteError, match="no responde") as e:
        remote("hang_load", load_timeout=1.5)
    assert e.value.kind == "timeout" and time.time() - t0 < 15


def test_remote_crash_timeout_and_cancel_during_call():
    r = remote("cpu")
    with pytest.raises(RemoteError) as e:
        r.call("crash")
    assert e.value.kind == "crash" and not r.alive

    r = remote("cpu")
    with pytest.raises(RemoteError) as e:
        r.call("stubborn", timeout=1.0)                    # sin noticias: se corta
    assert e.value.kind == "timeout" and not r.alive

    r = remote("cpu")
    t = __import__("threading").Timer(0.2, r.cancel)
    t.start()
    with pytest.raises(RemoteError) as e:
        r.call("work", 10_000)                             # obedece la cancelación
    assert e.value.kind == "cancelled" and r.alive
    r.call("work", 2)                                      # y sigue sirviendo
    r.close()

    r = remote("cpu")
    threading = __import__("threading")
    threading.Timer(0.2, lambda: r.cancel(grace=0.5)).start()
    with pytest.raises(RemoteError) as e:
        r.call("stubborn", timeout=None)                   # no obedece: se termina el proceso
    assert e.value.kind == "cancelled" and not r.alive


def test_tts_service_falls_back_to_cpu_when_gpu_crashes():
    made = []

    def factory(model_key, gpu, on_stage):
        made.append(gpu)
        return Remote("fake_remote_obj:make", ("gpu_crash" if gpu else "cpu",), name="motor de texto a voz",
                      log_name="prueba", on_stage=on_stage)
    svc = tts.TTSService(remote_factory=factory)
    stages = []
    wav, info = svc.synthesize("m", True, ("hola",), lambda p: None, stages.append)
    assert wav.shape == (10,) and info["device"] == "cpu" and "cerrado inesperadamente" in info["fallback"]
    assert made == [True, False] and any("CPU" in s for s in stages)
    wav, info = svc.synthesize("m", False, ("otra",), None, stages.append)   # reutiliza el proceso de CPU
    assert made == [True, False] and info["fallback"] is None
    svc.unload()


def test_remote_rvc_proxy_and_gpu_fallback(monkeypatch):
    def cls(factory, args, **kw):
        return Remote("fake_remote_obj:make_rvc", args, **kw)
    m = rvc.RemoteRVC("perfil", "profile", True, remote_cls=cls)
    assert m.fallback is None and m.sr == 40000 and m.device == "gpu"
    np.testing.assert_allclose(m.convert16(np.ones(4, np.float32)), 2.0)
    m.close()
    m = rvc.RemoteRVC("perfil-gpu_fail", "profile", True, remote_cls=cls)
    assert m.fallback and m.device == "cpu"
    m.close()


def test_tts_service_preload_then_synthesize_reuses_process():
    made = []

    def factory(model_key, gpu, on_stage):
        made.append(gpu)
        return Remote("fake_remote_obj:make", ("cpu",), name="motor de texto a voz", log_name="prueba",
                      on_stage=on_stage)
    svc = tts.TTSService(remote_factory=factory)
    assert svc.status()["state"] == "idle"
    svc.preload("m", False)
    for _ in range(100):
        if svc.status()["state"] == "ready":
            break
        time.sleep(0.05)
    assert svc.status()["state"] == "ready" and svc.status()["device"] == "cpu"
    svc.preload("m", False)                                  # ya cargado: no hace nada
    wav, info = svc.synthesize("m", False, ("hola",), None, lambda s: None)
    assert made == [False] and wav.shape == (10,)
    svc.unload()
