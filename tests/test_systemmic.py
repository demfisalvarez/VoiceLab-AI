"""«En todas las apps»: el cable como micrófono predeterminado de Windows y su restauración."""

import json

from voicelab.audio.systemmic import SystemMic


class FakeWin:
    def __init__(self):
        self.devs = [{"id": "mic", "name": "Micrófono (G435 Wireless Gaming Headset)"},
                     {"id": "cam", "name": "Micrófono (Webcam)"},
                     {"id": "cab", "name": "CABLE Output (VB-Audio Virtual Cable)"}]
        self.default = {0: "mic", 1: "mic", 2: "cam"}
        self.calls = []

    def available(self):
        return True

    def capture_devices(self):
        return list(self.devs)

    def default_capture(self, role=0):
        return self.default.get(role)

    def set_default_capture(self, dev_id, roles=(0, 1, 2)):
        self.calls.append((dev_id, tuple(roles)))
        for r in roles:
            self.default[r] = dev_id


def test_engage_and_release_restores_each_role(tmp_path):
    w = FakeWin()
    sm = SystemMic(w, tmp_path / "estado.json")
    st = sm.engage("CABLE Input (VB-Audio Virtual Cable)")
    assert st["engaged"] and st["device"].startswith("CABLE Output") and w.default == {0: "cab", 1: "cab", 2: "cab"}
    saved = json.loads((tmp_path / "estado.json").read_text())
    assert saved["previous"] == {"0": "mic", "1": "mic", "2": "cam"}
    sm.engage()                                        # dos veces: no se guarda el cable como «original»
    assert json.loads((tmp_path / "estado.json").read_text())["previous"]["0"] == "mic"
    st = sm.release()
    assert not st["engaged"] and w.default == {0: "mic", 1: "mic", 2: "cam"}
    assert not (tmp_path / "estado.json").exists()


def test_recovers_after_crash(tmp_path):
    w = FakeWin()
    SystemMic(w, tmp_path / "estado.json").engage()    # la app se cierra de golpe sin restaurar
    sm2 = SystemMic(w, tmp_path / "estado.json")       # al volver a abrirla
    sm2.release()
    assert w.default[0] == "mic" and w.default[2] == "cam"


def test_missing_cable_reports_error(tmp_path):
    w = FakeWin()
    w.devs = w.devs[:2]
    st = SystemMic(w, tmp_path / "estado.json").engage()
    assert not st["engaged"] and "CABLE Output" in st["error"] and w.default[0] == "mic"


def test_picks_matching_cable_side(tmp_path):
    w = FakeWin()
    w.devs.append({"id": "cabA", "name": "CABLE-A Output (VB-Audio Cable A)"})
    sm = SystemMic(w, tmp_path / "estado.json")
    assert sm.find_cable("CABLE-A Input (VB-Audio Cable A)")["id"] == "cabA"
    assert sm.find_cable("CABLE Input (VB-Audio Virtual Cable)")["id"] == "cab"


def test_restore_skips_devices_that_disappeared(tmp_path):
    w = FakeWin()
    sm = SystemMic(w, tmp_path / "estado.json")
    sm.engage()
    w.devs = [d for d in w.devs if d["id"] != "cam"]   # la webcam se desconectó
    sm.release()
    assert w.default[0] == "mic" and w.default[2] == "cab"
