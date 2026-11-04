"""Simulador de ``sounddevice`` con reloj real para probar el motor.

Imita un Windows con WASAPI y MME, un micrófono Realtek, altavoces, auriculares
y VB-CABLE. Cada flujo corre en su propio hilo y llama al callback al ritmo
real de su dispositivo; cada dispositivo puede tener una deriva de reloj
distinta (``clock``), como ocurre con el hardware de verdad.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import numpy as np


class PortAudioError(Exception):
    pass


class CallbackStop(Exception):
    pass


class WasapiSettings:
    def __init__(self, exclusive=False, auto_convert=False, explicit_sample_format=False):
        self.exclusive = exclusive
        self.auto_convert = auto_convert


def _dev(name, hostapi, ins, outs, sr=48000.0):
    return {"name": name, "hostapi": hostapi, "max_input_channels": ins, "max_output_channels": outs,
            "default_samplerate": sr, "default_low_input_latency": 0.01, "default_low_output_latency": 0.01}


WINDOWS_DEVICES = [
    # MME (hostapi 0) — nombres cortados a 31 caracteres como en Windows
    _dev("Micrófono (Realtek(R) Audio)", 0, 2, 0),
    _dev("Altavoces (Realtek(R) Audio)", 0, 0, 2),
    _dev("CABLE Input (VB-Audio Virtual C", 0, 0, 8),
    # WASAPI (hostapi 1)
    _dev("Micrófono (Realtek(R) Audio)", 1, 2, 0),
    _dev("Altavoces (Realtek(R) Audio)", 1, 0, 2),
    _dev("Auriculares (USB Headset)", 1, 0, 2),
    _dev("CABLE Input (VB-Audio Virtual Cable)", 1, 0, 8),
    _dev("CABLE Output (VB-Audio Virtual Cable)", 1, 8, 0),
    _dev("Altavoces (Realtek(R) Audio) [Loopback]", 1, 2, 0),
]
WINDOWS_HOSTAPIS = [
    {"name": "MME", "devices": [0, 1, 2], "default_input_device": 0, "default_output_device": 1},
    {"name": "Windows WASAPI", "devices": [3, 4, 5, 6, 7, 8], "default_input_device": 3, "default_output_device": 4},
]


class FakeStream:
    def __init__(self, sd, kind, device=None, samplerate=48000, blocksize=256, channels=1, dtype="float32",
                 latency="low", callback=None, finished_callback=None, extra_settings=None, **_):
        self.sd = sd
        self.kind = kind
        self.device = device
        self.samplerate = samplerate
        self.blocksize = blocksize
        self.channels = channels
        self.callback = callback
        self.finished_callback = finished_callback
        self.extra_settings = extra_settings
        self.latency = 0.010
        self.cpu_load = 0.02
        self.active = False
        self.closed = False
        self._stop = threading.Event()
        self._thread = None
        dev = sd.devices[device]
        if dev["name"] in sd.fail_open:
            raise PortAudioError(sd.fail_open[dev["name"]])
        if kind == "input" and channels > dev["max_input_channels"]:
            raise PortAudioError("Invalid number of channels [PaErrorCode -9998]")
        if kind == "output" and channels > dev["max_output_channels"]:
            raise PortAudioError("Invalid number of channels [PaErrorCode -9998]")
        if samplerate not in sd.supported_rates:
            raise PortAudioError("Invalid sample rate [PaErrorCode -9997]")
        self.clock = sd.clocks.get(dev["name"], 1.0)
        self.recorded: list[np.ndarray] = []
        self.frames_done = 0
        sd.streams.append(self)

    def start(self):
        self.active = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        period = self.blocksize / (self.samplerate * self.clock)
        next_t = time.perf_counter()
        flags = SimpleNamespace(input_overflow=False, output_underflow=False)
        while not self._stop.is_set():
            if self.kind == "input" and self.sd.disconnect.is_set():
                break
            n = self.blocksize
            try:
                if self.kind == "input":
                    t = (self.frames_done + np.arange(n)) / self.samplerate
                    sig = self.sd.signal(t).astype(np.float32)
                    data = np.repeat(sig[:, None], self.channels, axis=1)
                    self.callback(data, n, None, flags)
                else:
                    out = np.zeros((n, self.channels), dtype=np.float32)
                    self.callback(out, n, None, flags)
                    self.recorded.append(out[:, 0].copy())
            except CallbackStop:
                break
            self.frames_done += n
            next_t += period
            delay = next_t - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
        self.active = False
        if self.finished_callback:
            self.finished_callback()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
        self.active = False

    def close(self):
        self.stop()
        self.closed = True

    def output(self) -> np.ndarray:
        return np.concatenate(self.recorded) if self.recorded else np.zeros(0, np.float32)


class FakeSD:
    PortAudioError = PortAudioError
    CallbackStop = CallbackStop
    WasapiSettings = WasapiSettings

    def __init__(self, devices=None, hostapis=None):
        self.devices = [dict(d) for d in (devices or WINDOWS_DEVICES)]
        self.hostapis = [dict(h) for h in (hostapis or WINDOWS_HOSTAPIS)]
        self.streams: list[FakeStream] = []
        self.clocks: dict[str, float] = {}
        self.fail_open: dict[str, str] = {}
        self.supported_rates = {44100, 48000}
        self.disconnect = threading.Event()
        self.signal = lambda t: 0.25 * np.sin(2 * np.pi * 220.0 * t)
        self.reinit_count = 0

    def query_devices(self):
        return self.devices

    def query_hostapis(self):
        return self.hostapis

    def get_portaudio_version(self):
        return (1, "PortAudio simulado")

    def _terminate(self):
        pass

    def _initialize(self):
        self.reinit_count += 1

    def InputStream(self, **kw):  # noqa: N802
        return FakeStream(self, "input", **kw)

    def OutputStream(self, **kw):  # noqa: N802
        return FakeStream(self, "output", **kw)

    def outputs_for(self, name: str) -> list[FakeStream]:
        return [s for s in self.streams if s.kind == "output" and self.devices[s.device]["name"] == name]
