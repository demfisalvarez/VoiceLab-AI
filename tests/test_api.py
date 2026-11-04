import json
import time
import urllib.error
import urllib.request

import pytest

from fake_sd import FakeSD
from voicelab.api import Api
from voicelab.audio import devices as devmod
from voicelab.audio.devices import DeviceManager
from voicelab.audio.engine import AudioEngine
from voicelab.config import Settings
from voicelab.devserver import DevServer


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr(devmod, "PLATFORM", "win32")
    sd = FakeSD()
    dm = DeviceManager(sd)
    eng = AudioEngine(dm)
    a = Api(Settings(tmp_path / "s.json"), dm, eng, sysinfo_fn=lambda: {"os": "Windows 11", "ai": {"summary": "x"}})
    a.sd = sd  # acceso para las pruebas
    yield a
    eng.stop()


def test_initial_state(api):
    st = api.get_initial_state()
    assert st["ok"]
    assert st["app"]["phase"] >= 1
    d = st["devices"]
    assert d["hostapi"] == "Windows WASAPI"
    assert d["virtual"]["cable_output"] == "CABLE Input (VB-Audio Virtual Cable)"
    assert d["virtual"]["renamed"] is False
    assert d["defaults"]["input"] == "Micrófono (Realtek(R) Audio)"
    assert st["status"]["state"] == "stopped"
    json.dumps(st)  # todo serializable para JavaScript


def test_start_stop_and_live_update(api):
    assert api.start_engine()["ok"]
    time.sleep(0.4)
    s = api.get_status()
    assert s["running"] and s["routes"]["cable"]["active"]
    r = api.update_settings({"audio": {"input_gain_db": -6}})
    assert r["ok"] and r["changed"] == {"audio": {"input_gain_db": -6.0}}
    time.sleep(0.1)
    api.get_status()  # el medidor guarda el máximo desde la última lectura: se vacía
    time.sleep(0.2)
    assert api.get_status()["input"]["peak_db"] == pytest.approx(-18.0, abs=0.5)
    r = api.update_settings({"audio": {"monitor_enabled": True, "monitor_device": "Auriculares (USB Headset)"}})
    time.sleep(0.4)
    assert api.get_status()["routes"]["monitor"]["active"]
    assert api.toggle_engine()["status"]["state"] == "stopped"


def test_invalid_setting_is_reported_in_spanish(api):
    r = api.update_settings({"audio": {"block_size": 300}})
    assert not r["ok"] and "no válido" in r["error"]


def test_changing_hostapi_resets_devices_missing_there(api):
    api.update_settings({"audio": {"monitor_device": "Auriculares (USB Headset)",
                                   "input_device": "Micrófono (Realtek(R) Audio)"}})
    r = api.update_settings({"audio": {"hostapi": "MME"}})
    assert r["ok"]
    a = r["settings"]["audio"]
    assert a["monitor_device"] is None  # no existe en MME
    assert a["input_device"] == "Micrófono (Realtek(R) Audio)"  # sí existe
    assert r["devices"]["hostapi"] == "MME"


def test_start_failure_returns_message(api):
    api.update_settings({"audio": {"input_device": "CABLE Output (VB-Audio Virtual Cable)"}})
    r = api.start_engine()
    assert not r["ok"] and "bucle" in r["error"]


def test_refresh_devices_restarts_running_engine(api):
    api.start_engine()
    time.sleep(0.2)
    r = api.refresh_devices()
    assert r["ok"] and r["status"]["running"]
    assert api.sd.reinit_count == 1


def test_test_tone_hints(api):
    r = api.play_test_tone("cable")
    assert r["ok"] and "CABLE Output" in r["hint"]
    assert not api.play_test_tone("nada")["ok"]


def test_external_links_are_allowlisted(api, monkeypatch):
    opened = []
    monkeypatch.setattr("voicelab.api.webbrowser.open", opened.append)
    assert api.open_external("vbcable")["ok"]
    assert not api.open_external("https://malicioso.example")["ok"]
    assert opened == ["https://vb-audio.com/Cable/"]


# --------------------------------------------------------------- modo navegador
def _post(url, body, token=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **({"X-VoiceLab-Token": token} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_devserver_requires_token_and_serves_ui(api):
    srv = DevServer(api)
    srv.start()
    try:
        base = f"http://127.0.0.1:{srv.port}"
        code, body = _post(base + "/api/get_status", {"args": []})
        assert code == 403
        code, body = _post(base + "/api/get_status", {"args": []}, srv.token)
        assert code == 200 and body["ok"] and body["state"] == "stopped"
        code, body = _post(base + "/api/_devices_payload", {"args": []}, srv.token)
        assert code == 404  # métodos privados no expuestos
        code, body = _post(base + "/api/update_settings", {"args": [{"audio": {"input_gain_db": 3}}]}, srv.token)
        assert body["ok"]
        with urllib.request.urlopen(base + "/", timeout=5) as r:
            assert b"VoiceLab AI" in r.read()
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(base + "/../config.py", timeout=5)
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(base + "/%2e%2e/config.py", timeout=5)
    finally:
        srv.stop()
