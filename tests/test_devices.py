import pytest

from fake_sd import FakeSD
from voicelab.audio import devices as devmod
from voicelab.audio.devices import DeviceManager, classify


@pytest.fixture
def dm(monkeypatch):
    monkeypatch.setattr(devmod, "PLATFORM", "win32")
    return DeviceManager(FakeSD())


def test_wasapi_is_preferred_on_windows(dm):
    assert dm.preferred_hostapi() == "Windows WASAPI"
    assert dm.hostapi_names()[0] == "Windows WASAPI"
    assert dm.resolve_hostapi("MME") == "MME"
    assert dm.resolve_hostapi("No existe") == "Windows WASAPI"


def test_loopback_devices_are_hidden(dm):
    names = [d.name for d in dm.inputs("Windows WASAPI")]
    assert not any("[Loopback]" in n for n in names)


def test_vbcable_detection(dm):
    out = dm.virtual_cable_output("Windows WASAPI")
    rec = dm.virtual_cable_record("Windows WASAPI")
    assert out.name == "CABLE Input (VB-Audio Virtual Cable)" and out.kind == "vbcable_playback"
    assert rec.name == "CABLE Output (VB-Audio Virtual Cable)" and rec.kind == "vbcable_record"
    # MME corta el nombre a 31 caracteres: también se reconoce
    assert dm.virtual_cable_output("MME").kind == "vbcable_playback"


def test_defaults_never_pick_virtual_cable(dm):
    assert dm.default_input("Windows WASAPI").name == "Micrófono (Realtek(R) Audio)"
    assert dm.default_output("Windows WASAPI").name == "Altavoces (Realtek(R) Audio)"


def test_renamed_cable_still_detected():
    assert classify("VoiceLab AI Microphone (VB-Audio Virtual Cable)", 8, 0) == "vbcable_record"
    assert classify("Altavoces (Realtek(R) Audio)", 0, 2) == "physical"
    assert classify("Voicemeeter Input (VB-Audio Voicemeeter VAIO)", 0, 8) == "virtual"


def test_find_by_name_and_direction(dm):
    assert dm.find("Windows WASAPI", "Auriculares (USB Headset)", "output") is not None
    assert dm.find("Windows WASAPI", "Auriculares (USB Headset)", "input") is None
    assert dm.find("MME", "Auriculares (USB Headset)", "output") is None


def test_refresh_reinitialises_portaudio(dm):
    dm.refresh()
    assert dm.sd.reinit_count == 1
