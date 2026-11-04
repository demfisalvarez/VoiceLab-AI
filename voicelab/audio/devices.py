"""Enumeración de dispositivos de audio y detección del cable virtual.

Los dispositivos se guardan en los ajustes por **nombre** (y controlador), no
por índice: los índices de PortAudio cambian cada vez que se conecta o
desconecta algo.
"""

from __future__ import annotations

import logging
import sys
import threading
from dataclasses import asdict, dataclass

log = logging.getLogger(__name__)

# Se guarda aparte para poder simular Windows en las pruebas.
PLATFORM = sys.platform

# Orden de preferencia de controladores en Windows. WASAPI ofrece la menor
# latencia en modo compartido y nombres de dispositivo completos (MME los
# corta a 31 caracteres).
HOSTAPI_PREFERENCE = ("Windows WASAPI", "MME", "Windows DirectSound", "Windows WDM-KS", "ASIO",
                      "ALSA", "Core Audio", "JACK Audio Connection Kit")

HOSTAPI_LABELS = {
    "Windows WASAPI": "WASAPI (recomendado)",
    "MME": "MME (compatibilidad)",
    "Windows DirectSound": "DirectSound",
    "Windows WDM-KS": "WDM-KS (avanzado)",
    "ASIO": "ASIO (interfaces profesionales)",
    "ALSA": "ALSA",
    "Core Audio": "Core Audio",
}

# Patrones (en minúsculas) para reconocer dispositivos virtuales.
_VBCABLE_TAG = "vb-audio virtual cable"
_VIRTUAL_HINTS = ("vb-audio", "voicemeeter", "virtual audio", "virtual mic", "virtual speaker",
                  "virtual cable", "steam streaming")


@dataclass
class DeviceInfo:
    index: int
    name: str
    hostapi: str
    inputs: int
    outputs: int
    default_samplerate: float
    is_default_input: bool = False
    is_default_output: bool = False
    # "vbcable_playback": salida donde VoiceLab escribe (CABLE Input)
    # "vbcable_record":   micrófono que usan las demás apps (CABLE Output)
    # "virtual":          otro dispositivo virtual · "physical": real
    kind: str = "physical"

    def to_dict(self) -> dict:
        return asdict(self)


def classify(name: str, inputs: int, outputs: int) -> str:
    low = name.lower()
    is_vbcable = _VBCABLE_TAG in low or low.startswith("cable input") or low.startswith("cable output")
    if is_vbcable:
        if outputs > 0 and inputs == 0:
            return "vbcable_playback"
        if inputs > 0 and outputs == 0:
            return "vbcable_record"
    if any(h in low for h in _VIRTUAL_HINTS) or "voicelab" in low:
        return "virtual"
    return "physical"


class AudioBackendUnavailable(RuntimeError):
    pass


def load_sounddevice():
    """Importa sounddevice con un mensaje comprensible si falta PortAudio."""
    try:
        import sounddevice as sd  # noqa: WPS433
    except OSError as exc:  # PortAudio no encontrado (Linux sin libportaudio)
        raise AudioBackendUnavailable(
            "No se encontró la biblioteca de audio PortAudio. En Windows viene incluida con "
            "VoiceLab AI; reinstala la aplicación si ves este mensaje."
        ) from exc
    except ImportError as exc:
        raise AudioBackendUnavailable(
            "Falta el módulo 'sounddevice'. Ejecuta de nuevo el instalador de VoiceLab AI."
        ) from exc
    return sd


class DeviceManager:
    def __init__(self, sd_module=None):
        self._lock = threading.RLock()
        self.error: str | None = None
        if sd_module is not None:
            self.sd = sd_module
        else:
            try:
                self.sd = load_sounddevice()
            except AudioBackendUnavailable as exc:
                self.sd = None
                self.error = str(exc)
        self._devices: list[DeviceInfo] = []
        self._hostapis: list[dict] = []
        if self.sd is not None:
            self._scan()

    @property
    def available(self) -> bool:
        return self.sd is not None

    # ------------------------------------------------------------- escaneo
    def _scan(self) -> None:
        sd = self.sd
        hostapis = list(sd.query_hostapis())
        devices = sd.query_devices()
        result: list[DeviceInfo] = []
        for idx, dev in enumerate(devices):
            name = str(dev["name"])
            if "[loopback]" in name.lower():
                continue  # capturas de lo que suena por una salida: no son micrófonos
            ha = hostapis[dev["hostapi"]]
            result.append(DeviceInfo(
                index=idx,
                name=name,
                hostapi=ha["name"],
                inputs=int(dev["max_input_channels"]),
                outputs=int(dev["max_output_channels"]),
                default_samplerate=float(dev["default_samplerate"]),
                is_default_input=(ha.get("default_input_device") == idx),
                is_default_output=(ha.get("default_output_device") == idx),
                kind=classify(name, int(dev["max_input_channels"]), int(dev["max_output_channels"])),
            ))
        with self._lock:
            self._hostapis = hostapis
            self._devices = result

    def refresh(self) -> None:
        """Vuelve a leer la lista de dispositivos de Windows.

        PortAudio solo detecta dispositivos nuevos al reiniciarse, así que se
        reinicializa. Debe llamarse con el motor de audio detenido.
        """
        if self.sd is None:
            return
        with self._lock:
            try:
                self.sd._terminate()  # noqa: SLF001 - API documentada de facto
                self.sd._initialize()  # noqa: SLF001
            except Exception as exc:  # pragma: no cover - depende del sistema
                log.warning("No se pudo reiniciar PortAudio: %s", exc)
            self._scan()

    # ------------------------------------------------------------ consultas
    def hostapi_names(self) -> list[str]:
        with self._lock:
            names = [h["name"] for h in self._hostapis if any(d.hostapi == h["name"] for d in self._devices)]
        order = {n: i for i, n in enumerate(HOSTAPI_PREFERENCE)}
        return sorted(names, key=lambda n: order.get(n, 99))

    def preferred_hostapi(self) -> str | None:
        names = self.hostapi_names()
        if not names:
            return None
        if PLATFORM == "win32" and "Windows WASAPI" in names:
            return "Windows WASAPI"
        return names[0]

    def resolve_hostapi(self, wanted: str | None) -> str | None:
        names = self.hostapi_names()
        if wanted in names:
            return wanted
        return self.preferred_hostapi()

    def list(self, hostapi: str | None) -> list[DeviceInfo]:
        with self._lock:
            return [d for d in self._devices if d.hostapi == hostapi]

    def inputs(self, hostapi: str | None) -> list[DeviceInfo]:
        return [d for d in self.list(hostapi) if d.inputs > 0]

    def outputs(self, hostapi: str | None) -> list[DeviceInfo]:
        return [d for d in self.list(hostapi) if d.outputs > 0]

    def find(self, hostapi: str | None, name: str | None, direction: str) -> DeviceInfo | None:
        """Busca un dispositivo por nombre exacto; ``direction`` es 'input' u 'output'."""
        if not name:
            return None
        pool = self.inputs(hostapi) if direction == "input" else self.outputs(hostapi)
        for d in pool:
            if d.name == name:
                return d
        return None

    def default_input(self, hostapi: str | None) -> DeviceInfo | None:
        ins = self.inputs(hostapi)
        for d in ins:
            if d.is_default_input and d.kind != "vbcable_record":
                return d
        for d in ins:
            if d.kind == "physical":
                return d
        return ins[0] if ins else None

    def default_output(self, hostapi: str | None) -> DeviceInfo | None:
        outs = [d for d in self.outputs(hostapi) if d.kind != "vbcable_playback"]
        for d in outs:
            if d.is_default_output:
                return d
        return outs[0] if outs else None

    def virtual_cable_output(self, hostapi: str | None) -> DeviceInfo | None:
        """Salida del cable virtual (donde escribe VoiceLab AI)."""
        outs = self.outputs(hostapi)
        for d in outs:
            if d.kind == "vbcable_playback":
                return d
        for d in outs:
            if d.kind == "virtual":
                return d
        return None

    def virtual_cable_record(self, hostapi: str | None) -> DeviceInfo | None:
        """Lado "micrófono" del cable (lo que se elige en Discord, etc.)."""
        for d in self.inputs(hostapi):
            if d.kind == "vbcable_record":
                return d
        return None

    def portaudio_version(self) -> str | None:
        if self.sd is None:
            return None
        try:
            return self.sd.get_portaudio_version()[1]
        except Exception:  # pragma: no cover
            return None
