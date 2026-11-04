"""Prueba de integración con PortAudio real.

Solo se ejecuta si existen los dispositivos ALSA de prueba descritos en
tests/asoundrc.example (VOICELAB_ALSA_TEST=1). Verifica que el motor abre y
alimenta flujos de PortAudio auténticos, no simulados.
"""

import os
import time

import numpy as np
import pytest

pytestmark = pytest.mark.skipif(os.environ.get("VOICELAB_ALSA_TEST") != "1",
                                reason="requiere los dispositivos ALSA de prueba")


def test_engine_with_real_portaudio(tmp_path):
    from voicelab.audio.devices import DeviceManager
    from voicelab.audio.engine import AudioEngine, EngineConfig, RouteConfig

    for f in ("/tmp/vl_cable.raw", "/tmp/vl_mon.raw"):
        if os.path.exists(f):
            os.remove(f)
    dm = DeviceManager()
    assert dm.available and dm.portaudio_version()
    names = [d.name for d in dm.list(dm.preferred_hostapi())]
    assert "CABLE Input (VB-Audio Virtual Cable)" in names
    eng = AudioEngine(dm)
    eng.start(EngineConfig(
        input_device="Mic Realtek Prueba", input_gain_db=6.0,
        routes={"cable": RouteConfig(None, True, 0.0),
                "monitor": RouteConfig("Auriculares Prueba", True, -6.0),
                "aux": RouteConfig(None, False, 0.0)}))
    time.sleep(0.6)
    st = eng.status()
    eng.stop()
    assert st["running"] and st["routes"]["cable"]["active"] and st["routes"]["monitor"]["active"]
    assert st["routes"]["cable"]["device"] == "CABLE Input (VB-Audio Virtual Cable)"
    cable = np.fromfile("/tmp/vl_cable.raw", dtype="<f4").reshape(-1, 2)
    mon = np.fromfile("/tmp/vl_mon.raw", dtype="<f4").reshape(-1, 2)
    # Entrada: seno de 0,25 → +6 dB en el cable, −6 dB en el monitor
    assert np.max(np.abs(cable)) == pytest.approx(0.5, rel=0.02)
    assert np.max(np.abs(mon)) == pytest.approx(0.25, rel=0.02)
    assert np.allclose(cable[:, 0], cable[:, 1])  # mono duplicado en ambos canales
