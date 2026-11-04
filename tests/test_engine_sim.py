"""Pruebas del motor con dispositivos simulados a ritmo real."""

import time

import numpy as np
import pytest

from fake_sd import FakeSD
from voicelab.audio import devices as devmod
from voicelab.audio.devices import DeviceManager
from voicelab.audio.dsp import db_to_lin
from voicelab.audio.engine import AudioEngine, EngineConfig, EngineError, RouteConfig, config_with

CABLE = "CABLE Input (VB-Audio Virtual Cable)"
HEADSET = "Auriculares (USB Headset)"
SPEAKERS = "Altavoces (Realtek(R) Audio)"


@pytest.fixture
def sd(monkeypatch):
    monkeypatch.setattr(devmod, "PLATFORM", "win32")
    return FakeSD()


@pytest.fixture
def engine(sd):
    eng = AudioEngine(DeviceManager(sd))
    yield eng
    eng.stop()


def cfg(**kw):
    routes = {
        "cable": RouteConfig(device=None, enabled=True, volume_db=0.0),
        "monitor": RouteConfig(device=HEADSET, enabled=False, volume_db=-6.0),
        "aux": RouteConfig(device=None, enabled=False),
    }
    routes.update(kw.pop("routes", {}))
    return EngineConfig(routes=routes, **kw)


def steady(sig: np.ndarray, skip_s=0.2, sr=48000) -> np.ndarray:
    return sig[int(skip_s * sr):]


def test_signal_flows_to_virtual_mic_and_monitor(sd, engine):
    engine.start(cfg(input_gain_db=6.0, routes={"monitor": RouteConfig(HEADSET, True, -6.0)}))
    time.sleep(1.2)
    st = engine.status()
    assert st["state"] == "running" and st["error"] is None
    assert st["input"]["device"] == "Micrófono (Realtek(R) Audio)"
    assert st["routes"]["cable"]["active"] and st["routes"]["monitor"]["active"]
    assert st["routes"]["cable"]["device"] == CABLE  # detectado automáticamente
    # 0,25 de amplitud + 6 dB ≈ 0,5 en el cable; −6 dB ≈ 0,25 en los auriculares
    assert st["input"]["peak_db"] == pytest.approx(-6.0, abs=0.3)
    assert 20 < st["latency_ms"] < 60
    engine.stop()
    cable = steady(sd.outputs_for(CABLE)[0].output())
    mon = steady(sd.outputs_for(HEADSET)[0].output())
    assert np.max(np.abs(cable)) == pytest.approx(0.25 * db_to_lin(6.0), rel=0.03)
    assert np.max(np.abs(mon)) == pytest.approx(0.25, rel=0.03)
    # Sin huecos de silencio una vez cebado
    assert np.mean(np.abs(cable) > 1e-4) > 0.97
    assert all(s.closed for s in sd.streams)


def test_wasapi_streams_request_auto_convert(sd, engine):
    engine.start(cfg())
    time.sleep(0.2)
    ins = [s for s in sd.streams if s.kind == "input"][0]
    assert ins.extra_settings is not None and ins.extra_settings.auto_convert


def test_clock_drift_keeps_latency_bounded(sd, engine):
    # Deriva exagerada (±2 %) para forzar recortes y cebados en 3 segundos.
    sd.clocks[CABLE] = 1.02
    sd.clocks[HEADSET] = 0.98
    engine.start(cfg(routes={"monitor": RouteConfig(HEADSET, True, 0.0)}))
    lat = []
    for _ in range(15):
        time.sleep(0.2)
        st = engine.status()
        lat += [st["routes"]["cable"]["latency_ms"], st["routes"]["monitor"]["latency_ms"]]
    st = engine.status()
    assert st["routes"]["monitor"]["trims"] >= 1  # la salida lenta se recorta
    assert st["routes"]["cable"]["underruns"] >= 1  # la rápida se queda sin datos y se re-ceba
    assert max(lat) < 80  # la latencia no crece sin límite
    engine.stop()
    for name in (CABLE, HEADSET):
        out = steady(sd.outputs_for(name)[0].output())
        assert np.mean(np.abs(out) > 1e-4) > 0.85


def test_routes_toggle_live_without_stopping_input(sd, engine):
    base = cfg()
    engine.start(base)
    time.sleep(0.3)
    input_stream = [s for s in sd.streams if s.kind == "input"][0]
    engine.apply(config_with(base, routes={**base.routes, "monitor": RouteConfig(HEADSET, True, 0.0)}))
    time.sleep(0.4)
    st = engine.status()
    assert st["routes"]["monitor"]["active"]
    on = engine.cfg
    engine.apply(config_with(on, routes={**on.routes, "monitor": RouteConfig(HEADSET, False, 0.0)}))
    time.sleep(0.1)
    assert not engine.status()["routes"]["monitor"]["active"]
    assert sd.outputs_for(HEADSET)[0].closed
    assert input_stream.active  # la entrada nunca se reabrió


def test_route_device_change_reopens_only_that_route(sd, engine):
    base = cfg(routes={"monitor": RouteConfig(HEADSET, True, 0.0)})
    engine.start(base)
    time.sleep(0.3)
    engine.apply(config_with(base, routes={**base.routes, "monitor": RouteConfig(SPEAKERS, True, 0.0)}))
    time.sleep(0.4)
    st = engine.status()
    assert st["routes"]["monitor"]["device"] == SPEAKERS and st["routes"]["monitor"]["active"]
    assert len([s for s in sd.streams if s.kind == "input"]) == 1


def test_gain_change_is_smooth(sd, engine):
    sd.signal = lambda t: np.full(t.shape, 0.2)
    base = cfg()
    engine.start(base)
    time.sleep(0.4)
    engine.apply(config_with(base, input_gain_db=-12.0))
    time.sleep(0.4)
    engine.stop()
    out = steady(sd.outputs_for(CABLE)[0].output())
    assert np.max(np.abs(np.diff(out))) < 0.01  # sin escalones (chasquidos)
    assert out[-1] == pytest.approx(0.2 * db_to_lin(-12.0), rel=0.02)


def test_structural_change_restarts_with_new_block_size(sd, engine):
    base = cfg()
    engine.start(base)
    time.sleep(0.2)
    engine.apply(config_with(base, block_size=512))
    time.sleep(0.3)
    st = engine.status()
    assert st["running"] and st["block_size"] == 512
    ins = [s for s in sd.streams if s.kind == "input"]
    assert len(ins) == 2 and ins[0].closed and ins[1].blocksize == 512


@pytest.mark.parametrize("gate", [True, False])
def test_noise_gate_silences_pauses(sd, engine, gate):
    # Ciclos de 0,8 s: 0,3 s de «voz» y 0,5 s de ruido de fondo a −66 dB.
    sd.signal = lambda t: np.where((t % 0.8) < 0.3, 0.3 * np.sin(2 * np.pi * 200 * t), 0.0005)
    engine.start(cfg(gate_enabled=gate, gate_threshold_db=-40.0))
    time.sleep(1.8)
    engine.stop()
    out = steady(sd.outputs_for(CABLE)[0].output(), skip_s=0.1)
    silent = np.mean(np.abs(out) < 1e-6)
    assert np.max(np.abs(out)) > 0.25  # la voz pasa siempre
    if gate:
        # retención 80 ms + cierre 120 ms ⇒ ~0,3 s de silencio real por ciclo
        assert silent > 0.25
    else:
        assert silent < 0.08  # solo huecos ocasionales por la planificación de hilos de la prueba


def test_virtual_mic_as_input_is_rejected(sd, engine):
    with pytest.raises(EngineError, match="bucle"):
        engine.start(cfg(input_device="CABLE Output (VB-Audio Virtual Cable)"))
    assert engine.status()["state"] == "stopped"


def test_missing_cable_reports_route_error_but_runs(monkeypatch):
    monkeypatch.setattr(devmod, "PLATFORM", "win32")
    sd = FakeSD()
    sd.devices = [d for d in sd.devices if "CABLE" not in d["name"]]
    sd.hostapis = [{"name": "Windows WASAPI", "devices": list(range(len(sd.devices))),
                    "default_input_device": 3, "default_output_device": 4}]
    for d in sd.devices:
        d["hostapi"] = 0
    eng = AudioEngine(DeviceManager(sd))
    try:
        eng.start(cfg(routes={"monitor": RouteConfig(HEADSET, True, 0.0)}))
        time.sleep(0.3)
        st = eng.status()
        assert st["running"]
        assert "VB-CABLE" in st["routes"]["cable"]["error"]
        assert st["routes"]["monitor"]["active"]
    finally:
        eng.stop()


def test_unsupported_sample_rate_has_clear_message(sd, engine):
    sd.supported_rates = {48000}
    with pytest.raises(EngineError, match="44100 Hz"):
        engine.start(cfg(sample_rate=44100))


def test_busy_device_message(sd, engine):
    sd.fail_open["Micrófono (Realtek(R) Audio)"] = "Unanticipated host error [PaErrorCode -9999]"
    with pytest.raises(EngineError, match="modo exclusivo"):
        engine.start(cfg())


def test_disconnected_microphone_sets_error(sd, engine):
    engine.start(cfg())
    time.sleep(0.2)
    sd.disconnect.set()
    time.sleep(0.2)
    st = engine.status()
    assert st["state"] == "error" and "desconectado" in st["error"]
    engine.stop()
    assert engine.status()["state"] == "stopped"


def test_monitor_cannot_target_virtual_cable(sd, engine):
    engine.start(cfg(routes={"monitor": RouteConfig(CABLE, True, 0.0)}))
    time.sleep(0.1)
    assert "micrófono virtual" in engine.status()["routes"]["monitor"]["error"]


def test_test_tone_plays_and_closes(sd, engine):
    dev = engine.devices.find("Windows WASAPI", HEADSET, "output")
    engine.play_test_tone(dev)
    time.sleep(1.0)
    stream = sd.outputs_for(HEADSET)[-1]
    assert stream.closed
    played = stream.output()
    assert 0.45 < np.count_nonzero(played) / 48000 < 0.6  # 0,18 s + 0,32 s de notas
