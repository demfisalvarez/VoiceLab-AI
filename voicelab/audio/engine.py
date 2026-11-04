"""Motor de audio en tiempo real.

Flujo de la señal::

    micrófono ─► mezcla a mono ─► ganancia ─► [cadena de procesado] ─┬─► búfer ─► micrófono virtual
                                       │                             ├─► búfer ─► monitorización
                                  medidor entrada              medidor salida └─► búfer ─► salida auxiliar

Cada destino tiene su propio flujo de PortAudio y su propio búfer circular,
porque cada dispositivo tiene su reloj. El búfer mantiene un colchón objetivo
(``buffer_blocks`` bloques): si crece por deriva de reloj se recorta, y si se
vacía se rellena con silencio y se vuelve a cebar. Así la latencia no crece
con el tiempo.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field, replace

import numpy as np

from .devices import DeviceInfo, DeviceManager
from .dsp import LevelMeter, NoiseGate, SafetyLimiter, SmoothedGain, downmix, make_test_tone
from .effects import VoiceChain, default_params, sanitize
from .ringbuffer import RingBuffer

log = logging.getLogger(__name__)

ROUTE_NAMES = ("cable", "monitor", "aux")
ROUTE_LABELS = {
    "cable": "el micrófono virtual",
    "monitor": "la salida de monitorización",
    "aux": "la salida auxiliar",
}


class EngineError(RuntimeError):
    """Error con un mensaje listo para mostrar al usuario."""


@dataclass
class RouteConfig:
    device: str | None = None
    enabled: bool = False
    volume_db: float = 0.0


@dataclass
class EngineConfig:
    hostapi: str | None = None
    input_device: str | None = None
    input_channel_mode: str = "mix"
    input_gain_db: float = 0.0
    gate_enabled: bool = False
    gate_threshold_db: float = -50.0
    sample_rate: int = 48000
    block_size: int = 256
    buffer_blocks: int = 2
    routes: dict[str, RouteConfig] = field(default_factory=lambda: {n: RouteConfig() for n in ROUTE_NAMES})
    voice_params: dict = field(default_factory=default_params)
    monitor_source: str = "processed"   # "original" = escuchar el micrófono sin efectos

    @classmethod
    def from_settings(cls, audio: dict, voice: dict | None = None) -> "EngineConfig":
        return cls(
            voice_params=sanitize((voice or {}).get("params")),
            monitor_source=audio.get("monitor_source", "processed"),
            hostapi=audio.get("hostapi"),
            input_device=audio.get("input_device"),
            input_channel_mode=audio.get("input_channel_mode", "mix"),
            input_gain_db=float(audio.get("input_gain_db", 0.0)),
            gate_enabled=bool(audio.get("gate_enabled", False)),
            gate_threshold_db=float(audio.get("gate_threshold_db", -50.0)),
            sample_rate=int(audio.get("sample_rate", 48000)),
            block_size=int(audio.get("block_size", 256)),
            buffer_blocks=int(audio.get("buffer_blocks", 2)),
            routes={
                n: RouteConfig(
                    device=audio.get(f"{n}_device"),
                    enabled=bool(audio.get(f"{n}_enabled", False)),
                    volume_db=float(audio.get(f"{n}_volume_db", 0.0)),
                )
                for n in ROUTE_NAMES
            },
        )

    def structural_key(self) -> tuple:
        """Parámetros que obligan a reabrir la entrada si cambian."""
        return (self.hostapi, self.input_device, self.sample_rate, self.block_size, self.buffer_blocks)


def explain_stream_error(exc: Exception, what: str, device: str | None, sample_rate: int) -> str:
    """Traduce un error de PortAudio a un mensaje comprensible."""
    msg = str(exc).lower()
    dev = f"«{device}»" if device else ""
    if "invalid sample rate" in msg or "sample rate" in msg:
        return (f"{what.capitalize()} {dev} no admite {sample_rate} Hz. Prueba con otra frecuencia "
                "de muestreo en Ajustes o usa el controlador WASAPI.")
    if "invalid number of channels" in msg:
        return f"{what.capitalize()} {dev} no admite la configuración de canales solicitada."
    if "invalid device" in msg or "device unavailable" in msg or "no such device" in msg:
        return (f"No se encuentra {what} {dev}. Puede que se haya desconectado: pulsa "
                "«Actualizar dispositivos» en Ajustes.")
    if "unanticipated host error" in msg or "busy" in msg or "exclusive" in msg:
        return (f"Windows no ha permitido abrir {what} {dev}. Puede que otra aplicación lo esté "
                "usando en modo exclusivo o que se haya desconectado.")
    return f"No se pudo abrir {what} {dev}: {exc}"


def _extra_settings(sd, hostapi: str | None):
    """En WASAPI compartido se pide conversión automática de frecuencia para
    poder trabajar siempre a la misma frecuencia en todos los dispositivos."""
    if hostapi == "Windows WASAPI" and hasattr(sd, "WasapiSettings"):
        try:
            return sd.WasapiSettings(auto_convert=True)
        except TypeError:  # versiones antiguas de sounddevice
            return None
    return None


class _Route:
    """Un destino de salida: búfer + volumen + limitador + flujo de PortAudio."""

    def __init__(self, name: str, sd, device: DeviceInfo, cfg: RouteConfig, sample_rate: int,
                 block_size: int, buffer_blocks: int, extra):
        self.name = name
        self.device = device
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.channels = max(1, min(2, device.outputs))
        capacity = max(block_size * (buffer_blocks + 16), int(sample_rate * 0.5))
        self.ring = RingBuffer(capacity)
        self.target = block_size * buffer_blocks
        # Por encima de este nivel se recorta el colchón (deriva de reloj).
        self.high = self.target + max(2 * block_size, int(sample_rate * 0.02))
        self.gain = SmoothedGain(cfg.volume_db)
        self.limiter = SafetyLimiter(sample_rate)
        self.meter = LevelMeter()
        self.priming = True
        self.underruns = 0
        self.trims = 0
        self.xruns = 0
        self.dropped = 0
        self.fill_ema = float(self.target)
        self.error: str | None = None
        self.closing = False
        self.source = "processed"
        self._tmp = np.zeros(block_size * 4, dtype=np.float32)
        self.stream = sd.OutputStream(
            device=device.index, samplerate=sample_rate, blocksize=block_size,
            channels=self.channels, dtype="float32", latency="low",
            callback=self._callback, finished_callback=self._finished, extra_settings=extra,
        )

    # Hilo de audio (salida) ------------------------------------------------
    def _callback(self, outdata, frames, time_info, status) -> None:
        try:
            if status.output_underflow:
                self.xruns += 1
            if frames > self._tmp.shape[0]:
                self._tmp = np.zeros(frames * 2, dtype=np.float32)
            ring = self.ring
            avail = ring.available()
            self.fill_ema += 0.05 * (avail - self.fill_ema)
            if self.priming:
                if avail < self.target:
                    outdata.fill(0.0)
                    return
                self.priming = False
            if avail > self.high:
                ring.skip(avail - self.target)
                self.trims += 1
            got = ring.read_into(self._tmp, frames)
            block = self._tmp[:frames]
            if got < frames:
                block[got:] = 0.0
                self.underruns += 1
                self.priming = True
            out = self.limiter.process(self.gain.process(block))
            self.meter.update(out)
            outdata[:] = out[:, None]
        except Exception as exc:  # nunca se propaga al hilo de PortAudio
            outdata.fill(0.0)
            self.error = f"Error interno de audio: {exc!r}"

    def _finished(self) -> None:
        if not self.closing and self.error is None:
            self.error = f"Se perdió la conexión con «{self.device.name}». ¿Se ha desconectado?"

    # Control ----------------------------------------------------------------
    def start(self) -> None:
        self.stream.start()

    def close(self) -> None:
        self.closing = True
        try:
            self.stream.stop()
        except Exception:
            pass
        try:
            self.stream.close()
        except Exception:
            pass

    def latency_out(self) -> float:
        try:
            return float(self.stream.latency)
        except Exception:
            return 0.0


class AudioEngine:
    def __init__(self, devices: DeviceManager):
        self.devices = devices
        self.sd = devices.sd
        self.cfg = EngineConfig()
        self._lock = threading.RLock()
        self._state = "stopped"
        self._error: str | None = None
        self._stopping = False
        self._in_stream = None
        self._input_device: DeviceInfo | None = None
        self._routes: dict[str, _Route] = {}
        self._route_errors: dict[str, str] = {}
        self._live: tuple[_Route, ...] = ()
        self._in_overflows = 0
        self._callback_error: str | None = None
        self._channel_mode = "mix"
        self._gain = SmoothedGain(0.0)
        self._gate = NoiseGate(48000)
        self._meter_in = LevelMeter()
        self._meter_proc = LevelMeter()
        # Procesadores en cadena (cada uno con .process(bloque) -> bloque).
        # Fase 1: puerta de ruido. Las fases siguientes añaden efectos e IA.
        self._chain = VoiceChain(48000)
        self._ai = None   # conversión de voz por IA (Fase 4): procesador con .process()
        self._processors: tuple = (self._gate, self._chain)
        self._tone_threads: list[threading.Thread] = []

    # ================================================================ estado
    @property
    def running(self) -> bool:
        return self._state == "running"

    def _resolve_input(self, cfg: EngineConfig) -> DeviceInfo:
        hostapi = self.devices.resolve_hostapi(cfg.hostapi)
        dev = self.devices.find(hostapi, cfg.input_device, "input") if cfg.input_device else None
        if cfg.input_device and dev is None:
            raise EngineError(f"No se encuentra el micrófono «{cfg.input_device}». Elige otro en Ajustes "
                              "o pulsa «Actualizar dispositivos».")
        if dev is None:
            dev = self.devices.default_input(hostapi)
        if dev is None:
            raise EngineError("No hay ningún micrófono disponible en Windows.")
        if dev.kind == "vbcable_record":
            raise EngineError("Has elegido el micrófono virtual como entrada. Eso crearía un bucle: "
                              "elige tu micrófono físico en Ajustes.")
        return dev

    def _resolve_route_device(self, name: str, cfg: EngineConfig) -> DeviceInfo:
        hostapi = self.devices.resolve_hostapi(cfg.hostapi)
        rc = cfg.routes[name]
        dev = self.devices.find(hostapi, rc.device, "output") if rc.device else None
        if rc.device and dev is None:
            raise EngineError(f"No se encuentra el dispositivo «{rc.device}». Elige otro en Ajustes.")
        if dev is None:
            if name == "cable":
                dev = self.devices.virtual_cable_output(hostapi)
                if dev is None:
                    raise EngineError("No se ha encontrado el cable virtual (VB-CABLE). Instálalo desde "
                                      "Ajustes → Micrófono virtual para que otras apps reciban tu voz.")
            elif name == "monitor":
                dev = self.devices.default_output(hostapi)
                if dev is None:
                    raise EngineError("No hay altavoces ni auriculares disponibles.")
            else:
                raise EngineError("Elige un dispositivo para la salida auxiliar en Ajustes.")
        if name != "cable" and dev.kind == "vbcable_playback":
            raise EngineError("Ese dispositivo es el micrófono virtual. Para enviar tu voz a otras apps "
                              "usa la ruta «Micrófono virtual».")
        return dev

    # ============================================================= arranque
    def start(self, cfg: EngineConfig | None = None) -> None:
        if self.sd is None:
            raise EngineError(self.devices.error or "El sistema de audio no está disponible.")
        with self._lock:
            if cfg is not None:
                self.cfg = cfg
            if self.running:
                return
            self._close_all()
            cfg = self.cfg
            hostapi = self.devices.resolve_hostapi(cfg.hostapi)
            extra = _extra_settings(self.sd, hostapi)
            dev = self._resolve_input(cfg)
            sr, bs = cfg.sample_rate, cfg.block_size

            self._channel_mode = cfg.input_channel_mode
            self._gain = SmoothedGain(cfg.input_gain_db)
            self._gate = NoiseGate(sr, threshold_db=cfg.gate_threshold_db, enabled=cfg.gate_enabled)
            self._chain = VoiceChain(sr, cfg.voice_params)
            if self._ai is not None and getattr(self._ai, "sr", sr) != sr:
                self._ai = None
            self._rebuild_processors()
            self._meter_in = LevelMeter()
            self._meter_proc = LevelMeter()
            self._in_overflows = 0
            self._callback_error = None
            self._error = None
            self._stopping = False
            self._route_errors = {}

            channels = max(1, min(2, dev.inputs))
            if self._channel_mode == "right" and channels < 2:
                self._channel_mode = "left"
            try:
                self._in_stream = self.sd.InputStream(
                    device=dev.index, samplerate=sr, blocksize=bs, channels=channels,
                    dtype="float32", latency="low", callback=self._on_input,
                    finished_callback=self._on_input_finished, extra_settings=extra,
                )
            except Exception as exc:
                self._in_stream = None
                raise EngineError(explain_stream_error(exc, "el micrófono", dev.name, sr)) from exc
            self._input_device = dev

            for name in ROUTE_NAMES:
                if cfg.routes[name].enabled and self._open_route(name, cfg, extra):
                    try:
                        self._routes[name].start()
                    except Exception as exc:
                        self._routes.pop(name).close()
                        self._route_errors[name] = explain_stream_error(
                            exc, ROUTE_LABELS[name], cfg.routes[name].device, sr)
            self._publish_live()

            try:
                self._in_stream.start()
            except Exception as exc:
                self._close_all()
                raise EngineError(explain_stream_error(exc, "el micrófono", dev.name, sr)) from exc
            self._state = "running"
            log.info("Motor iniciado: entrada=%s sr=%s bloque=%s rutas=%s", dev.name, sr, bs,
                     list(self._routes))

    def _open_route(self, name: str, cfg: EngineConfig, extra) -> bool:
        """Abre una ruta. Los errores se guardan por ruta y no detienen el motor."""
        self._route_errors.pop(name, None)
        try:
            dev = self._resolve_route_device(name, cfg)
            route = _Route(name, self.sd, dev, cfg.routes[name], cfg.sample_rate, cfg.block_size,
                           cfg.buffer_blocks, extra)
        except EngineError as exc:
            self._route_errors[name] = str(exc)
            return False
        except Exception as exc:
            self._route_errors[name] = explain_stream_error(exc, ROUTE_LABELS[name],
                                                            cfg.routes[name].device, cfg.sample_rate)
            return False
        route.source = cfg.monitor_source if name == "monitor" else "processed"
        self._routes[name] = route
        return True

    def _close_route(self, name: str) -> None:
        route = self._routes.pop(name, None)
        self._publish_live()
        if route is not None:
            route.close()

    def _publish_live(self) -> None:
        # Asignación atómica: el hilo de entrada siempre ve una tupla completa.
        self._live = tuple(self._routes.values())

    def _rebuild_processors(self) -> None:
        procs = [self._gate]
        if self._ai is not None:
            procs.append(self._ai)
        procs.append(self._chain)
        self._processors = tuple(procs)        # asignación atómica

    @property
    def ai(self):
        """Procesador de IA activo (o ``None``)."""
        return self._ai

    def set_ai(self, processor) -> None:
        """Activa o quita la conversión por IA sin detener el audio."""
        old, self._ai = self._ai, processor
        self._rebuild_processors()
        if old is not None and old is not processor and hasattr(old, "close"):
            old.close()

    def stop(self) -> None:
        with self._lock:
            self._stopping = True
            self._close_all()
            self._state = "stopped"
            self._stopping = False
            log.info("Motor detenido")

    def _close_all(self) -> None:
        self._live = ()
        if self._in_stream is not None:
            try:
                self._in_stream.stop()
            except Exception:
                pass
            try:
                self._in_stream.close()
            except Exception:
                pass
            self._in_stream = None
        for name in list(self._routes):
            self._close_route(name)

    # ===================================================== cambios en vivo
    def apply(self, cfg: EngineConfig) -> None:
        """Aplica una configuración nueva. Si el motor está en marcha, cambia en
        caliente lo que se puede y reinicia la entrada solo si es necesario."""
        with self._lock:
            old, self.cfg = self.cfg, cfg
            if not self.running:
                return
            if old.structural_key() != cfg.structural_key():
                self._stopping = True
                self._close_all()
                self._state = "stopped"
                self._stopping = False
                self.start()
                return
            self._gain.set_db(cfg.input_gain_db)
            if cfg.voice_params != old.voice_params:
                self._chain.set_params(cfg.voice_params)
            if "monitor" in self._routes:
                self._routes["monitor"].source = cfg.monitor_source
            self._gate.enabled = cfg.gate_enabled
            self._gate.threshold_db = cfg.gate_threshold_db
            mode = cfg.input_channel_mode
            if mode == "right" and (self._input_device is None or self._input_device.inputs < 2):
                mode = "left"
            self._channel_mode = mode
            hostapi = self.devices.resolve_hostapi(cfg.hostapi)
            extra = _extra_settings(self.sd, hostapi)
            for name in ROUTE_NAMES:
                o, n = old.routes[name], cfg.routes[name]
                is_open = name in self._routes
                if not n.enabled:
                    if is_open:
                        self._close_route(name)
                    self._route_errors.pop(name, None)
                    continue
                if is_open and o.device == n.device:
                    self._routes[name].gain.set_db(n.volume_db)
                    continue
                if is_open:
                    self._close_route(name)
                if self._open_route(name, cfg, extra):
                    try:
                        self._routes[name].start()
                    except Exception as exc:
                        self._routes.pop(name).close()
                        self._route_errors[name] = explain_stream_error(
                            exc, ROUTE_LABELS[name], n.device, cfg.sample_rate)
                self._publish_live()

    # ============================================================ hilo audio
    def _on_input(self, indata, frames, time_info, status) -> None:
        try:
            if status.input_overflow:
                self._in_overflows += 1
            dry = self._gain.process(downmix(indata, self._channel_mode))
            self._meter_in.update(dry)
            x = dry
            for proc in self._processors:
                x = proc.process(x)
            self._meter_proc.update(x)
            for route in self._live:
                dropped = route.ring.write(x if route.source == "processed" else dry)
                if dropped:
                    route.dropped += dropped
        except Exception as exc:  # nunca se propaga a PortAudio
            self._callback_error = f"Error interno de audio: {exc!r}"

    def _on_input_finished(self) -> None:
        if not self._stopping and self._state == "running":
            self._state = "error"
            name = self._input_device.name if self._input_device else ""
            self._error = f"Se perdió la conexión con el micrófono «{name}». ¿Se ha desconectado?"

    # ================================================================ estado
    def status(self) -> dict:
        with self._lock:
            state = self._state
            if state == "running" and self._in_stream is not None:
                try:
                    active = bool(self._in_stream.active)
                except Exception:
                    active = False
                if not active and not self._stopping:
                    state = self._state = "error"
                    self._error = self._error or "La captura del micrófono se ha detenido inesperadamente."
            sr = self.cfg.sample_rate
            bs = self.cfg.block_size
            in_lat = 0.0
            cpu = 0.0
            if self._in_stream is not None:
                try:
                    in_lat = float(self._in_stream.latency)
                    cpu = float(self._in_stream.cpu_load)
                except Exception:
                    pass
            routes = {}
            for name in ROUTE_NAMES:
                rc = self.cfg.routes[name]
                r = self._routes.get(name)
                info = {"enabled": rc.enabled, "active": False, "device": rc.device,
                        "error": self._route_errors.get(name), "latency_ms": None,
                        "underruns": 0, "trims": 0, "limiting": False,
                        "peak_db": -120.0, "rms_db": -120.0, "clip": False}
                if r is not None:
                    try:
                        stream_active = bool(r.stream.active)
                    except Exception:
                        stream_active = False
                    fx = (self._chain.latency_samples + (self._ai.latency_samples if self._ai else 0)) if r.source == "processed" else 0
                    latency = in_lat + r.latency_out() + (r.fill_ema + bs + fx) / sr
                    info.update(r.meter.read())
                    info.update({
                        "source": r.source,
                        "active": stream_active and r.error is None,
                        "device": r.device.name,
                        "error": r.error,
                        "latency_ms": round(latency * 1000.0, 1),
                        "underruns": r.underruns,
                        "trims": r.trims,
                        "limiting": r.limiter.active,
                    })
                routes[name] = info
            main_latency = None
            for name in ("cable", "monitor", "aux"):
                if routes[name]["active"] and routes[name]["latency_ms"] is not None:
                    main_latency = routes[name]["latency_ms"]
                    break
            if main_latency is None and state == "running":
                main_latency = round((in_lat + bs / sr) * 1000.0, 1)
            return {
                "state": state,
                "running": state == "running",
                "error": self._error or self._callback_error,
                "sample_rate": sr,
                "block_size": bs,
                "hostapi": self.devices.resolve_hostapi(self.cfg.hostapi),
                "input": {
                    "device": self._input_device.name if (self._input_device and state != "stopped") else None,
                    **self._meter_in.read(),
                    "gate_enabled": self._gate.enabled,
                    "gate_open": self._gate.is_open,
                    "overflows": self._in_overflows,
                },
                "processed": self._meter_proc.read(),
                "routes": routes,
                "latency_ms": main_latency,
                "cpu_load": round(cpu, 3),
                "voice_latency_ms": round(self._chain.latency_samples / sr * 1000.0, 1),
                "ai": None if self._ai is None else {
                    "infer_ms": round(getattr(self._ai, "infer_ms", 0.0), 1),
                    "block_ms": round(getattr(self._ai, "block", 0) / sr * 1000.0, 1),
                    "latency_ms": round(self._ai.latency_samples / sr * 1000.0, 1),
                    "underruns": getattr(self._ai, "underruns", 0),
                    "kind": getattr(self._ai, "kind", "rvc"),
                    "variant": getattr(self._ai, "variant", None),
                    "dropped_ms": round(getattr(self._ai, "dropped", 0) / sr * 1000.0),
                    "error": getattr(self._ai, "error", None)},
            }

    # ======================================================= tono de prueba
    def play_test_tone(self, device: DeviceInfo, sample_rate: int | None = None) -> None:
        """Reproduce un tono corto por ``device`` en un hilo aparte."""
        if self.sd is None:
            raise EngineError(self.devices.error or "El sistema de audio no está disponible.")
        sd = self.sd
        sr = sample_rate or self.cfg.sample_rate
        tone = make_test_tone(sr)
        channels = max(1, min(2, device.outputs))
        extra = _extra_settings(sd, device.hostapi)
        done = threading.Event()
        pos = [0]

        def callback(outdata, frames, time_info, status):
            chunk = tone[pos[0]:pos[0] + frames]
            n = chunk.shape[0]
            outdata[:n] = chunk[:, None]
            outdata[n:] = 0.0
            pos[0] += n
            if n < frames:
                raise sd.CallbackStop

        try:
            stream = sd.OutputStream(device=device.index, samplerate=sr, channels=channels,
                                     dtype="float32", callback=callback,
                                     finished_callback=done.set, extra_settings=extra)
        except Exception as exc:
            raise EngineError(explain_stream_error(exc, "el dispositivo", device.name, sr)) from exc

        def run():
            try:
                stream.start()
                done.wait(timeout=3.0)
            finally:
                try:
                    stream.close()
                except Exception:
                    pass

        t = threading.Thread(target=run, name="tono-prueba", daemon=True)
        self._tone_threads = [x for x in self._tone_threads if x.is_alive()] + [t]
        t.start()


def config_with(cfg: EngineConfig, **changes) -> EngineConfig:
    """Copia de la configuración con cambios (incluidas rutas)."""
    routes = {n: replace(r) for n, r in cfg.routes.items()}
    new = replace(cfg, routes=routes)
    for k, v in changes.items():
        setattr(new, k, v)
    return new
