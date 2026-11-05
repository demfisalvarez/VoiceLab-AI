"""Conversión de voz RVC v2 en ONNX (Fase 4), en archivos y en tiempo real.

Flujo (igual que RVC-WebUI): audio 16 kHz → ContentVec (768 dim, 50 fps,
duplicado a 100 fps) + tono RMVPE (100 fps) → sintetizador RVC → audio a la
frecuencia del modelo. Todo con ONNX Runtime (DirectML o CPU).
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

import numpy as np

from . import models, runtime
from ..audio.mediaio import resample

log = logging.getLogger(__name__)
SR16 = 16000


class RVCError(RuntimeError):
    pass


# ======================================================================= RMVPE
def _mel_basis(sr=16000, n_fft=1024, n_mels=128, fmin=30.0, fmax=8000.0) -> np.ndarray:
    """Banco de filtros mel (escala HTK, normalización «slaney»), como librosa htk=True."""
    def hz2mel(f):
        return 2595.0 * np.log10(1.0 + np.asarray(f) / 700.0)

    def mel2hz(m):
        return 700.0 * (10 ** (np.asarray(m) / 2595.0) - 1.0)
    fft_f = np.linspace(0, sr / 2, n_fft // 2 + 1)
    pts = mel2hz(np.linspace(hz2mel(fmin), hz2mel(fmax), n_mels + 2))
    fdiff = np.diff(pts)
    ramps = pts[:, None] - fft_f[None, :]
    lower = -ramps[:-2] / fdiff[:-1, None]
    upper = ramps[2:] / fdiff[1:, None]
    w = np.maximum(0, np.minimum(lower, upper))
    w *= (2.0 / (pts[2:n_mels + 2] - pts[:n_mels]))[:, None]
    return w.astype(np.float32)


class RMVPE:
    def __init__(self, session):
        self.s = session
        self.basis = _mel_basis()
        self.win = np.hanning(1025)[:1024].astype(np.float32)   # hann periódica
        cents = 20 * np.arange(360) + 1997.3794084376191
        self.cents = np.pad(cents, (4, 4))

    def mel(self, x16: np.ndarray) -> np.ndarray:
        pad = np.pad(x16, (512, 512), mode="reflect")
        n = 1 + (pad.shape[0] - 1024) // 160
        idx = np.arange(1024)[None, :] + 160 * np.arange(n)[:, None]
        mag = np.abs(np.fft.rfft(pad[idx] * self.win, axis=1)).T
        return np.log(np.maximum(self.basis @ mag, 1e-5)).astype(np.float32)

    def f0(self, x16: np.ndarray, thred: float = 0.03) -> np.ndarray:
        mel = self.mel(x16)[None]
        frames = mel.shape[-1]
        pad = 32 * ((frames - 1) // 32 + 1) - frames
        if pad:
            mel = np.pad(mel, ((0, 0), (0, 0), (0, pad)))
        hidden = self.s.run(None, {self.s.get_inputs()[0].name: mel})[0][0, :frames]
        center = np.argmax(hidden, axis=1) + 4
        sal = np.pad(hidden, ((0, 0), (4, 4)))
        idx = center[:, None] + np.arange(-4, 5)[None, :]
        s9 = np.take_along_axis(sal, idx, axis=1)
        c9 = self.cents[idx]
        cents = (s9 * c9).sum(1) / np.maximum(s9.sum(1), 1e-9)
        cents[hidden.max(axis=1) <= thred] = 0
        f0 = 10 * 2 ** (cents / 1200)
        f0[f0 == 10] = 0
        return f0.astype(np.float32)


def coarse_f0(f0: np.ndarray) -> np.ndarray:
    lo, hi = 1127 * np.log(1 + 50 / 700), 1127 * np.log(1 + 1100 / 700)
    mel = 1127 * np.log(1 + f0 / 700)
    mel[mel > 0] = (mel[mel > 0] - lo) * 254 / (hi - lo) + 1
    mel = np.clip(mel, 1, 255)
    return np.rint(mel).astype(np.int64)


# ===================================================================== modelo
class RVCModel:
    """Sintetizador RVC exportado a ONNX (formato RVC-WebUI o w-okada)."""

    def __init__(self, path: Path, base_dir: Path | None = None, sessions: dict | None = None,
                 prefer_gpu: bool = True, stage=None):
        if sessions is None:
            base = base_dir or models.model_dir("rvc-base")
            if not models.installed("rvc-base"):
                raise RVCError("Falta la base de conversión RVC. Descárgala en Ajustes → Motor de IA.")
            sessions = {}
            for i, (key, f, label) in enumerate((("vec", base / "vec-768-layer-12.onnx", "extractor de contenido"),
                                                 ("rmvpe", base / "rmvpe.onnx", "detector de tono"),
                                                 ("synth", path, "modelo de la voz")), 1):
                if stage:
                    stage(f"Cargando el {label} ({i}/3)…")
                sessions[key] = runtime.session(f, prefer_gpu=prefer_gpu)
        self.vec, self.synth = sessions["vec"], sessions["synth"]
        self.rmvpe = RMVPE(sessions["rmvpe"])
        names = [i.name for i in self.synth.get_inputs()]
        self.names = names
        self.style = "okada" if "feats" in names else "webui"
        if self.style == "webui" and not {"phone", "phone_lengths", "pitch", "pitchf", "ds"} <= set(names):
            raise RVCError("El archivo no parece un modelo RVC v2 con tono en ONNX (entradas: %s)." % ", ".join(names))
        self.sr = self.detect_sr()

    def features(self, x16: np.ndarray) -> np.ndarray:
        out = self.vec.run(None, {self.vec.get_inputs()[0].name: x16[None, None, :].astype(np.float32)})[0]
        if out.shape[-1] != 768 and out.shape[1] == 768:
            out = out.transpose(0, 2, 1)
        return np.repeat(out, 2, axis=1).astype(np.float32)          # 50 → 100 fps

    def _feed(self, feats, f0, sid=0, seed=0):
        n = min(feats.shape[1], f0.shape[0])
        feats, f0 = feats[:, :n], f0[:n]
        pitch, pitchf = coarse_f0(f0)[None], f0[None].astype(np.float32)
        if self.style == "okada":
            return {"feats": feats, "p_len": np.array([n], np.int64), "pitch": pitch, "pitchf": pitchf,
                    "sid": np.array([sid], np.int64)}
        feed = {"phone": feats, "phone_lengths": np.array([n], np.int64), "pitch": pitch, "pitchf": pitchf,
                "ds": np.array([sid], np.int64)}
        if "rnd" in self.names:
            feed["rnd"] = np.random.default_rng(seed).standard_normal((1, 192, n)).astype(np.float32)
        if "skip_head" in self.names:                     # modelos entrenados en la app: por defecto, todo
            feed["skip_head"] = np.zeros(1, np.int64)
        return feed

    def detect_sr(self) -> int:
        """Frecuencia del modelo: muestras de salida por trama de 10 ms × 100."""
        n = 64
        out = self.synth.run(None, self._feed(np.zeros((1, n, 768), np.float32), np.full(n, 150.0, np.float32)))[0]
        sr = int(round(np.asarray(out).size / n * 100))
        return min((32000, 40000, 44100, 48000), key=lambda r: abs(r - sr))

    @property
    def can_skip(self) -> bool:
        """Modelos entrenados con VoiceLab: el decodificador puede saltarse el contexto."""
        return "skip_head" in self.names

    def convert16(self, x16: np.ndarray, semitones: float = 0.0, keep: int = 0) -> np.ndarray:
        """Convierte audio a 16 kHz. ``keep`` (tramas de 10 ms): si el modelo lo admite, solo se
        sintetizan las últimas ``keep`` tramas (en directo, el resto es contexto)."""
        feats = self.features(x16)
        f0 = self.rmvpe.f0(x16) * (2 ** (semitones / 12))
        feed = self._feed(feats, f0)
        if self.can_skip:
            n = int(feed["phone_lengths"][0])
            feed["skip_head"] = np.array([max(0, n - keep) if keep else 0], np.int64)
        out = self.synth.run(None, feed)[0]
        return np.asarray(out, dtype=np.float32).reshape(-1)

    def convert(self, audio: np.ndarray, sr: int, semitones: float = 0.0, progress=None) -> np.ndarray:
        """Archivos: por tramos de 10 s con 0,5 s de solape."""
        x16 = resample(audio, sr, SR16)
        seg, ov = SR16 * 10, SR16 // 2
        outs = []
        starts = list(range(0, max(1, x16.shape[0]), seg))
        for k, s in enumerate(starts):
            a, b = max(0, s - ov), min(x16.shape[0], s + seg + ov)
            y = resample(self.convert16(x16[a:b], semitones), self.sr, sr)
            ratio = sr / SR16
            lead = int((s - a) * ratio)
            keep = int((min(s + seg, x16.shape[0]) - s) * ratio)
            outs.append(y[lead:lead + keep])
            if progress:
                progress((k + 1) / len(starts))
        return np.concatenate(outs).astype(np.float32)


def load_profile_model(profile_dir: Path, prefer_gpu: bool = True, stage=None) -> RVCModel:
    meta = profile_dir / "model" / "rvc.json"
    if not meta.exists():
        raise RVCError("Este perfil no tiene un modelo RVC.")
    info = json.loads(meta.read_text(encoding="utf-8"))
    return RVCModel(profile_dir / "model" / info["file"], prefer_gpu=prefer_gpu, stage=stage)


def open_model(target: str, kind: str = "profile", prefer_gpu: bool = True, stage=None, cancel=None) -> RVCModel:
    """Fábrica para el proceso aparte: ``kind`` es «profile» (carpeta de perfil) o «file» (.onnx)."""
    m = load_profile_model(Path(target), prefer_gpu, stage) if kind == "profile" else \
        RVCModel(Path(target), prefer_gpu=prefer_gpu, stage=stage)
    provs = m.synth.get_providers() if hasattr(m.synth, "get_providers") else []
    m.info = {"sr": m.sr, "style": m.style, "can_skip": m.can_skip,
              "device": "gpu" if provs and provs[0] != "CPUExecutionProvider" else "cpu"}
    return m


class RemoteRVC:
    """Mismo uso que ``RVCModel`` pero el modelo vive en un proceso aparte.

    Si la GPU falla al cargar, se reintenta con la CPU.
    """

    def __init__(self, target: Path, kind: str = "profile", prefer_gpu: bool = True, on_stage=None,
                 remote_cls=None):
        from .procs import Remote, RemoteError
        cls = remote_cls or Remote
        self.fallback = None
        try:
            self.r = cls("voicelab.ai.rvc:open_model", (str(target), kind, prefer_gpu), name="motor RVC",
                         log_name="rvc", load_timeout=600, on_stage=on_stage)
        except RemoteError as exc:
            if not prefer_gpu or exc.kind == "cancelled" or "no parece un modelo" in str(exc):
                raise RVCError(str(exc)) from None
            self.fallback = str(exc)
            log.warning("RVC: la GPU falló (%s); se usa la CPU", exc)
            try:
                self.r = cls("voicelab.ai.rvc:open_model", (str(target), kind, False), name="motor RVC",
                             log_name="rvc", load_timeout=600, on_stage=on_stage)
            except RemoteError as exc2:
                raise RVCError(str(exc2)) from None
        info = self.r.info or {}
        self.sr, self.style, self.device = info.get("sr", 40000), info.get("style", "webui"), info.get("device", "cpu")
        self.can_skip = bool(info.get("can_skip"))

    def convert16(self, x16: np.ndarray, semitones: float = 0.0, keep: int = 0) -> np.ndarray:
        return self.r.call("convert16", x16, semitones, keep, timeout=30)

    def convert(self, audio: np.ndarray, sr: int, semitones: float = 0.0, progress=None) -> np.ndarray:
        return self.r.call("convert", audio, sr, semitones, progress=progress, timeout=180)

    def close(self) -> None:
        self.r.close()


# ============================================================ tiempo real
class RealtimeRVC:
    """Procesador para el motor de audio: convierte por bloques en un hilo aparte.

    El hilo de audio solo copia muestras; la inferencia corre en otro hilo (ONNX
    Runtime suelta el GIL). Cada bloque se convierte con un poco de contexto previo
    y se empalma con fundido alineado (SOLA). Para bajar el retraso:

    * bloques cortos (empieza en 0,1 s) que se agrandan solos si el equipo no llega;
    * con modelos entrenados en la app, el decodificador solo sintetiza el final;
    * cola de salida adaptativa (``LiveOutput``): arranca en el retraso justo.
    """

    kind = "rvc"
    MIN_BLOCK_S, MAX_BLOCK_S = 0.06, 0.3
    WINDOW_S = 3.0
    STATS_S = 30.0

    def __init__(self, model: RVCModel, sr: int = 48000, block_s: float = 0.10, context_s: float = 0.4,
                 fade_s: float = 0.02, semitones: float = 0.0, adaptive: bool = True):
        from ..audio.ringbuffer import RingBuffer
        from .livebuf import LiveOutput
        self.m, self.sr = model, sr
        self.block, self.context, self.fade = int(block_s * sr), int(context_s * sr), int(fade_s * sr)
        self.adaptive = adaptive
        self.semitones = semitones
        self.inq = RingBuffer(sr * 10)
        self.out = LiveOutput(sr, self._need, int(self.MAX_BLOCK_S * sr), window_s=self.WINDOW_S)
        self.hist = np.zeros(self.context + self.block + self.fade, np.float32)
        self.prev_tail: np.ndarray | None = None
        self.infer_ms = 0.0
        self.error: str | None = None
        self._slow = 0
        self._ev = threading.Event()
        self._stop = False
        self._t = threading.Thread(target=self._worker, name="rvc-tiempo-real", daemon=True)
        self._t.start()

    # -- información
    def _need(self) -> float:
        """Bloque + cola del empalme (como mucho 2 fundidos) + cálculo."""
        return self.block + 2 * self.fade + 1.15 * self.infer_ms / 1000 * self.sr

    @property
    def latency_samples(self) -> int:
        return self.out.latency_samples

    underruns = property(lambda self: self.out.underruns)
    dropped = property(lambda self: self.out.dropped)

    def close(self) -> None:
        self._stop = True
        self._ev.set()
        if hasattr(self.m, "close"):                      # modelo en proceso aparte
            threading.Thread(target=self.m.close, daemon=True).start()

    # -- hilo de audio
    def process(self, x: np.ndarray) -> np.ndarray:
        self.inq.write(x)
        self.out.in_total += x.shape[0]
        if self.inq.available() >= self.block:
            self._ev.set()
        return self.out.read(x.shape[0])

    # -- hilo de conversión
    def _keep_frames(self) -> int:
        """Tramas (10 ms) que hay que sintetizar: bloque + 2 fundidos + margen para el decodificador."""
        return int(np.ceil((self.block + 2 * self.fade) / self.sr * 100)) + 8

    def _grow(self, ms: float) -> None:
        """Si el cálculo no cabe con holgura en el bloque, bloque más grande (más retraso, sin cortes)."""
        if not self.adaptive:
            return
        self._slow = self._slow + 1 if ms > 0.75 * self.block / self.sr * 1000 else 0
        if self._slow >= 3 and self.block < self.MAX_BLOCK_S * self.sr:
            new = min(int(self.MAX_BLOCK_S * self.sr), int(ms / 0.6 / 1000 * self.sr / 480 + 1) * 480)
            log.info("RVC en directo: el cálculo (%.0f ms) no cabe en bloques de %d ms; se pasa a %d ms",
                     ms, self.block * 1000 // self.sr, new * 1000 // self.sr)
            self.block, self._slow = new, 0
            self.hist = np.concatenate([np.zeros(max(0, self.context + self.block + self.fade - self.hist.shape[0]),
                                                 np.float32), self.hist])[-(self.context + self.block + self.fade):]

    def _worker(self) -> None:
        import time
        buf = np.zeros(int(self.MAX_BLOCK_S * self.sr), np.float32)
        last_log, under0 = time.monotonic(), 0
        while not self._stop:
            self._ev.wait(0.5)
            self._ev.clear()
            while not self._stop and self.inq.available() >= self.block:
                b = self.block
                if self.inq.available() > 4 * b:          # va por detrás: se descarta lo viejo
                    self.out.dropped += self.inq.skip(self.inq.available() - b)
                self.inq.read_into(buf, b)
                self.hist = np.concatenate([self.hist[b:], buf[:b]])
                t0 = time.perf_counter()
                try:
                    x16 = resample(self.hist, self.sr, SR16)
                    y = resample(self.m.convert16(x16, self.semitones, self._keep_frames()), self.m.sr, self.sr)
                    self._fails = 0
                except Exception as exc:  # noqa: BLE001
                    self._fails = getattr(self, "_fails", 0) + 1
                    log.error("RVC en tiempo real: %s", exc)
                    if self._fails >= 3:                       # el motor se ha caído: se informa y se para
                        self.error = str(exc)
                        self._stop = True
                        return
                    y = np.zeros(b + 2 * self.fade, np.float32)
                ms = (time.perf_counter() - t0) * 1000
                self.infer_ms = ms if self.infer_ms == 0 else 0.8 * self.infer_ms + 0.2 * ms
                need = b + 2 * self.fade
                y = np.pad(y, (max(0, need - y.shape[0]), 0))[-need:]
                self.out.write(self._splice(y, b))
                self._grow(ms)
            if time.monotonic() - last_log >= self.STATS_S and not self._stop:
                last_log = time.monotonic()
                log.info("RVC en directo: retraso %d ms, bloque %d ms, cálculo %.0f ms, huecos %d, margen %d ms",
                         self.latency_samples * 1000 // self.sr, self.block * 1000 // self.sr, self.infer_ms,
                         self.underruns - under0, self.out.margin * 1000 // self.sr)
                under0 = self.underruns

    def _splice(self, seg: np.ndarray, b: int) -> np.ndarray:
        """Devuelve ``b`` muestras nuevas empalmadas con la cola anterior (``seg``: b + 2 fundidos)."""
        f = self.fade
        if self.prev_tail is None:
            self.prev_tail = seg[-f:].copy()
            return seg[f:f + b].astype(np.float32)
        # SOLA: desplazamiento que mejor encaja con la cola anterior.
        search = seg[: 2 * f]
        corr = np.correlate(search, self.prev_tail, mode="valid")
        energy = np.sqrt(np.convolve(search ** 2, np.ones(f), mode="valid")) + 1e-6
        k = int(np.argmax(corr / energy))
        piece = seg[k:k + b + f].copy()
        if piece.shape[0] < b + f:
            piece = np.pad(piece, (0, b + f - piece.shape[0]))
        ramp = np.linspace(0, 1, f, dtype=np.float32)
        piece[:f] = piece[:f] * ramp + self.prev_tail * (1 - ramp)
        self.prev_tail = piece[b:b + f].copy()
        return piece[:b].astype(np.float32)
