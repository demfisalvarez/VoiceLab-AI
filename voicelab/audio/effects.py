"""Cadena de efectos de voz (Fase 2).

Todo funciona en streaming con bloques de cualquier tamaño, tanto en el
modulador en tiempo real como al procesar archivos. Cada etapa se salta sola
cuando sus parámetros son neutros, así que la voz original no añade latencia.

Orden: pasaaltos → espectral (reducción de ruido, tono, formantes, robot) →
EQ/tono/pasabajos → compresor → distorsión/saturación/lo-fi → modulador en
anillo → chorus → eco → reverberación → ganancia → limitador.
"""

from __future__ import annotations

import math
import threading

import numpy as np
from scipy.signal import lfilter, sosfilt

from .dsp import db_to_lin, lin_to_db

EQ_FREQS = (31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)

# nombre: (por defecto, mínimo, máximo)  — los booleanos usan (False, None, None)
PARAMS: dict[str, tuple] = {
    "pitch": (0.0, -12.0, 12.0),            # semitonos
    "formant": (0.0, -12.0, 12.0),          # semitonos de desplazamiento de formantes
    "robot": (False, None, None),
    "noise_reduction": (0.0, 0.0, 100.0),   # %
    "hpf_enabled": (False, None, None),
    "hpf_hz": (80.0, 20.0, 1000.0),
    "lpf_enabled": (False, None, None),
    "lpf_hz": (12000.0, 1000.0, 20000.0),
    "bass": (0.0, -12.0, 12.0),             # dB, estantería 120 Hz
    "mid": (0.0, -12.0, 12.0),              # dB, campana 1 kHz
    "treble": (0.0, -12.0, 12.0),           # dB, estantería 6 kHz
    "comp_enabled": (False, None, None),
    "comp_threshold": (-24.0, -60.0, 0.0),
    "comp_ratio": (4.0, 1.0, 20.0),
    "comp_makeup": (0.0, 0.0, 24.0),
    "distortion": (0.0, 0.0, 100.0),
    "saturation": (0.0, 0.0, 100.0),
    "lofi": (0.0, 0.0, 100.0),
    "ring_hz": (0.0, 0.0, 2000.0),
    "ring_mix": (0.0, 0.0, 100.0),
    "chorus_mix": (0.0, 0.0, 100.0),
    "chorus_rate": (0.8, 0.1, 5.0),
    "chorus_depth": (4.0, 0.5, 12.0),        # ms
    "echo_mix": (0.0, 0.0, 100.0),
    "echo_delay": (250.0, 30.0, 1000.0),     # ms
    "echo_feedback": (35.0, 0.0, 90.0),      # %
    "reverb_mix": (0.0, 0.0, 100.0),
    "reverb_size": (50.0, 0.0, 100.0),
    "reverb_damping": (50.0, 0.0, 100.0),
    "gain": (0.0, -24.0, 24.0),
    "limiter_enabled": (False, None, None),
    "limiter_ceiling": (-1.0, -12.0, 0.0),
}
for _i, _f in enumerate(EQ_FREQS):
    PARAMS[f"eq{_i}"] = (0.0, -12.0, 12.0)

# Parámetros solo para archivos (no tienen sentido en directo).
OFFLINE_PARAMS = {"speed": (1.0, 0.5, 2.0), "tempo": (1.0, 0.5, 2.0)}


def default_params() -> dict:
    return {k: v[0] for k, v in PARAMS.items()}


def sanitize(params: dict | None) -> dict:
    """Valida y completa un diccionario de parámetros (los desconocidos se ignoran)."""
    out = default_params()
    for k, v in (params or {}).items():
        if k not in PARAMS:
            continue
        d, lo, hi = PARAMS[k]
        try:
            if isinstance(d, bool):
                out[k] = bool(v)
            else:
                f = float(v)
                if f == f:
                    out[k] = min(hi, max(lo, f))
        except (TypeError, ValueError):
            pass
    return out


def is_neutral(params: dict) -> bool:
    return sanitize(params) == default_params()


# ======================================================================= filtros
def _biquad(kind: str, f0: float, sr: int, gain_db: float = 0.0, q: float = 0.707) -> np.ndarray:
    """Coeficientes RBJ (Audio EQ Cookbook) como una sección SOS."""
    f0 = min(f0, sr * 0.45)
    a = 10 ** (gain_db / 40.0)
    w0 = 2 * math.pi * f0 / sr
    cw, sw = math.cos(w0), math.sin(w0)
    alpha = sw / (2 * q)
    if kind == "hp":
        b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]
        aa = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "lp":
        b = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2]
        aa = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "bp":
        b = [alpha, 0.0, -alpha]
        aa = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "peak":
        b = [1 + alpha * a, -2 * cw, 1 - alpha * a]
        aa = [1 + alpha / a, -2 * cw, 1 - alpha / a]
    elif kind in ("lowshelf", "highshelf"):
        sq = 2 * math.sqrt(a) * alpha
        sgn = 1 if kind == "lowshelf" else -1
        b = [a * ((a + 1) - sgn * (a - 1) * cw + sq), sgn * 2 * a * ((a - 1) - sgn * (a + 1) * cw),
             a * ((a + 1) - sgn * (a - 1) * cw - sq)]
        aa = [(a + 1) + sgn * (a - 1) * cw + sq, -sgn * 2 * ((a - 1) + sgn * (a + 1) * cw),
              (a + 1) + sgn * (a - 1) * cw - sq]
    else:
        raise ValueError(kind)
    return np.array([[b[0] / aa[0], b[1] / aa[0], b[2] / aa[0], 1.0, aa[1] / aa[0], aa[2] / aa[0]]])


class FilterBank:
    """Serie de biquads con estado continuo entre bloques."""

    def __init__(self):
        self._lock = threading.Lock()
        self.sos: np.ndarray | None = None
        self.zi: np.ndarray | None = None

    def set(self, sections: list[np.ndarray]) -> None:
        with self._lock:
            if not sections:
                self.sos = None
                return
            sos = np.vstack(sections)
            if self.zi is None or self.zi.shape[0] != sos.shape[0]:
                self.zi = np.zeros((sos.shape[0], 2))
            self.sos = sos

    def process(self, x: np.ndarray) -> np.ndarray:
        with self._lock:
            if self.sos is None:
                return x
            y, self.zi = sosfilt(self.sos, x, zi=self.zi)
        return y.astype(np.float32)


# ============================================================ etapa espectral
class Spectral:
    """STFT en streaming (1024/256): reducción de ruido, tono con formantes
    conservados, desplazamiento de formantes y voz robótica."""

    N = 1024
    HOP = 256

    def __init__(self, sr: int):
        self.sr = sr
        n, h = self.N, self.HOP
        self.win = np.hanning(n + 1)[:n].astype(np.float32)
        # Normalización de la superposición ventana² con salto N/4.
        self.norm = 1.0 / (np.sum(self.win ** 2) / h)
        self.k = np.arange(n // 2 + 1)
        self.expected = 2 * np.pi * h * self.k / n
        self.reset()
        self.pitch_ratio = 1.0
        self.formant_ratio = 1.0
        self.robot = False
        self.nr = 0.0

    def reset(self) -> None:
        n, h = self.N, self.HOP
        self.inbuf = np.zeros(n, np.float32)
        self.in_fill = n - h
        self.outacc = np.zeros(n, np.float32)
        self.outq = np.zeros(h, np.float32)
        self.reset_pending = False
        self.last_phase = np.zeros(n // 2 + 1)
        self.sum_phase = np.zeros(n // 2 + 1)
        self.noise = None
        self.gain_prev = None

    @property
    def latency(self) -> int:
        # N−HOP de la ventana de análisis + HOP de colchón para bloques irregulares.
        return self.N

    def active(self) -> bool:
        return self.pitch_ratio != 1.0 or self.formant_ratio != 1.0 or self.robot or self.nr > 0

    def _envelope(self, mag: np.ndarray, lifter: int = 40) -> np.ndarray:
        cep = np.fft.irfft(np.log(mag + 1e-9))
        cep[lifter:-lifter] = 0.0
        return np.exp(np.fft.rfft(cep).real)

    def _frame(self, frame: np.ndarray) -> np.ndarray:
        n, h = self.N, self.HOP
        spec = np.fft.rfft(frame * self.win)
        mag, phase = np.abs(spec), np.angle(spec)

        if self.nr > 0:
            power = mag ** 2
            if self.noise is None:
                self.noise = power.copy()
            # Seguimiento de mínimos: baja rápido, sube despacio.
            self.noise = np.where(power < self.noise, 0.7 * self.noise + 0.3 * power, self.noise * 1.004)
            strength = self.nr / 100.0
            gain = np.clip(1.0 - (1.0 + 2.5 * strength) * self.noise / (power + 1e-12), 0.0, 1.0)
            floor = 10 ** ((-6 - 24 * strength) / 20)
            gain = np.maximum(gain, floor)
            if self.gain_prev is not None:
                gain = 0.6 * gain + 0.4 * self.gain_prev
            self.gain_prev = gain
            mag = mag * gain

        if self.pitch_ratio != 1.0 or self.formant_ratio != 1.0:
            env = self._envelope(mag)
            excit = mag / (env + 1e-9)
            dphi = phase - self.last_phase - self.expected
            dphi = dphi - 2 * np.pi * np.round(dphi / (2 * np.pi))
            true_bin = self.k + dphi * n / (2 * np.pi * h)
            r = self.pitch_ratio
            tgt = np.round(self.k * r).astype(int)
            ok = (tgt >= 0) & (tgt < self.k.size)
            new_exc = np.zeros_like(excit)
            np.add.at(new_exc, tgt[ok], excit[ok])
            new_freq = np.zeros_like(true_bin)
            new_freq[tgt[ok]] = true_bin[ok] * r
            # Envolvente: se mantiene (voz natural) y se desplaza si hay formantes.
            src = self.k / self.formant_ratio
            env_w = np.interp(src, self.k, env, right=env[-1] * 1e-3)
            mag = new_exc * env_w
            self.sum_phase += 2 * np.pi * h * new_freq / n
            phase_out = self.sum_phase
        else:
            phase_out = phase
        self.last_phase = phase

        if self.robot:
            # Fase constante en cada trama: tono monocorde y metálico.
            phase_out = np.zeros_like(phase_out)
            mag = mag * 1.4
        out = np.fft.irfft(mag * np.exp(1j * phase_out), n).astype(np.float32)
        return out * self.win * self.norm

    def process(self, x: np.ndarray) -> np.ndarray:
        if self.reset_pending:
            self.reset()
        n, h = self.N, self.HOP
        out_parts = [self.outq]
        pos = 0
        total = x.shape[0]
        while pos < total:
            take = min(h - (self.in_fill - (n - h)), total - pos)
            self.inbuf[self.in_fill:self.in_fill + take] = x[pos:pos + take]
            self.in_fill += take
            pos += take
            if self.in_fill == n:
                y = self._frame(self.inbuf)
                self.outacc += y
                out_parts.append(self.outacc[:h].copy())
                self.outacc = np.concatenate([self.outacc[h:], np.zeros(h, np.float32)])
                self.inbuf = np.concatenate([self.inbuf[h:], np.zeros(h, np.float32)])
                self.in_fill = n - h
        allout = np.concatenate(out_parts)
        result, self.outq = allout[:total], allout[total:]
        return result


# ========================================================== dinámica y color
class Compressor:
    def __init__(self, sr: int):
        self.sr = sr
        self.threshold, self.ratio, self.makeup = -24.0, 4.0, 0.0
        self.env_db = -120.0
        self.att = math.exp(-1.0 / (sr * 0.005 / 32))
        self.rel = math.exp(-1.0 / (sr * 0.120 / 32))
        self.gr_db = 0.0

    def process(self, x: np.ndarray) -> np.ndarray:
        n = x.shape[0]
        sub = 32
        gains = np.empty((n + sub - 1) // sub, np.float32)
        for i in range(gains.size):
            seg = x[i * sub:(i + 1) * sub]
            lvl = lin_to_db(float(np.max(np.abs(seg))) if seg.size else 0.0)
            c = self.att if lvl > self.env_db else self.rel
            self.env_db = c * self.env_db + (1 - c) * lvl
            over = self.env_db - self.threshold
            gr = over * (1 - 1 / self.ratio) if over > 0 else 0.0
            self.gr_db = gr
            gains[i] = db_to_lin(self.makeup - gr)
        g = np.repeat(gains, sub)[:n]
        return x * g


class Drive:
    """Distorsión (recorte), saturación (cálida, asimétrica) y lo-fi."""

    def __init__(self):
        self.distortion = self.saturation = self.lofi = 0.0
        self._hold = 0.0

    def process(self, x: np.ndarray) -> np.ndarray:
        if self.saturation > 0:
            s = self.saturation / 100.0
            k = 1 + 4 * s
            y = np.tanh(k * (x + 0.08 * s * x * x)) / math.tanh(k)
            x = (1 - s) * x + s * y.astype(np.float32)
        if self.distortion > 0:
            d = self.distortion / 100.0
            k = 1 + 40 * d
            y = np.tanh(k * x) / math.tanh(k)
            x = ((1 - d) * x + d * y * 0.8).astype(np.float32)
        if self.lofi > 0:
            l = self.lofi / 100.0
            bits = 16 - 12 * l
            q = 2 ** (bits - 1)
            x = (np.round(x * q) / q).astype(np.float32)
            factor = max(1, int(1 + 11 * l))
            if factor > 1:
                held = np.repeat(x[::factor], factor)[: x.shape[0]]
                x = held.astype(np.float32)
        return x


class RingMod:
    def __init__(self, sr: int):
        self.sr, self.freq, self.mix, self.phase = sr, 0.0, 0.0, 0.0

    def process(self, x: np.ndarray) -> np.ndarray:
        n = x.shape[0]
        inc = 2 * math.pi * self.freq / self.sr
        ph = self.phase + inc * np.arange(n)
        self.phase = float((self.phase + inc * n) % (2 * math.pi))
        m = self.mix / 100.0
        return (x * (1 - m) + x * np.sin(ph) * m).astype(np.float32)


class Chorus:
    VOICES = 3

    def __init__(self, sr: int):
        self.sr = sr
        self.mix, self.rate, self.depth_ms = 0.0, 0.8, 4.0
        self.hist = np.zeros(int(sr * 0.05), np.float32)
        self.t = 0

    def process(self, x: np.ndarray) -> np.ndarray:
        n, sr = x.shape[0], self.sr
        buf = np.concatenate([self.hist, x])
        base = len(self.hist)
        idx = np.arange(n)
        wet = np.zeros(n, np.float32)
        tt = (self.t + idx) / sr
        for v in range(self.VOICES):
            lfo = np.sin(2 * np.pi * self.rate * tt + v * 2 * np.pi / self.VOICES)
            delay = (0.012 + 0.003 * v) * sr + (self.depth_ms / 1000 * sr / 2) * (1 + lfo)
            pos = base + idx - delay
            i0 = np.floor(pos).astype(int)
            frac = (pos - i0).astype(np.float32)
            wet += buf[i0] * (1 - frac) + buf[i0 + 1] * frac
        wet /= self.VOICES
        self.hist = buf[-len(self.hist):].copy()
        self.t += n
        m = self.mix / 100.0
        return ((1 - 0.5 * m) * x + m * wet).astype(np.float32)


class Echo:
    """Eco con realimentación. La línea de retardo se procesa en trozos no
    mayores que el retardo, así funciona con cualquier tamaño de bloque."""

    def __init__(self, sr: int):
        self.sr = sr
        self.mix, self.delay_ms, self.feedback = 0.0, 250.0, 35.0
        self.line = np.zeros(sr * 2, np.float32)
        self.w = 0

    def process(self, x: np.ndarray) -> np.ndarray:
        d = max(1, int(self.delay_ms / 1000 * self.sr))
        fb = self.feedback / 100.0
        m = self.mix / 100.0
        L = self.line.shape[0]
        out = np.empty_like(x)
        pos = 0
        while pos < x.shape[0]:
            k = min(d, x.shape[0] - pos)
            ridx = (self.w - d + np.arange(k)) % L
            delayed = self.line[ridx]
            seg = x[pos:pos + k]
            self.line[(self.w + np.arange(k)) % L] = seg + fb * delayed
            out[pos:pos + k] = seg + m * delayed
            self.w = (self.w + k) % L
            pos += k
        return out


class Reverb:
    """Reverberación por convolución particionada con una respuesta al impulso
    sintética (ruido con caída exponencial y amortiguación de agudos)."""

    P = 256

    def __init__(self, sr: int):
        self.sr = sr
        self.mix = 0.0
        self._lock = threading.Lock()
        self.size = self.damping = None
        self.configure(50.0, 50.0)
        self.inq = np.zeros(0, np.float32)
        self.outq = np.zeros(self.P, np.float32)   # retraso de una partición (pre-delay)
        self.prev = np.zeros(self.P, np.float32)

    def configure(self, size: float, damping: float) -> None:
        if (size, damping) == (self.size, self.damping):
            return
        sr, P = self.sr, self.P
        t60 = 0.3 + 2.7 * (size / 100.0)
        n = int(sr * min(t60, 3.0))
        rng = np.random.default_rng(7)
        t = np.arange(n) / sr
        ir = rng.standard_normal(n) * np.exp(-6.9 * t / t60)
        # Amortiguación: los agudos decaen antes (filtro de un polo variable por tramos).
        damp = damping / 100.0
        out = np.empty_like(ir)
        y = 0.0
        for i0 in range(0, n, 512):
            frac = i0 / n
            a = min(0.95, 0.05 + damp * 0.9 * frac + 0.1 * damp)
            seg = ir[i0:i0 + 512]
            seg_f, zf = lfilter([1 - a], [1, -a], seg, zi=[y * a])
            y = float(seg_f[-1]) if seg_f.size else y
            out[i0:i0 + 512] = seg_f
        ir = out / (np.sqrt(np.sum(out ** 2)) + 1e-9) * 0.6
        parts = (n + P - 1) // P
        ir = np.pad(ir, (0, parts * P - n))
        H = np.fft.rfft(np.pad(ir.reshape(parts, P), ((0, 0), (0, P))), axis=1)
        G = H[::-1]
        G2 = np.ascontiguousarray(np.concatenate([G, G]))   # permite vistas circulares sin copiar
        fdl = np.zeros_like(H)
        with self._lock:
            self.G2, self.fdl, self.idx = G2, fdl, 0
            self.size, self.damping = size, damping

    def process(self, x: np.ndarray) -> np.ndarray:
        P = self.P
        self.inq = np.concatenate([self.inq, x])
        outs = [self.outq]
        with self._lock:
            G2, fdl = self.G2, self.fdl
            np_ = fdl.shape[0]
            while self.inq.shape[0] >= P:
                cur = self.inq[:P]
                self.inq = self.inq[P:]
                X = np.fft.rfft(np.concatenate([self.prev, cur]))
                self.prev = cur.copy()
                # Línea de retardo circular: Y = Σ_k X[n−k]·H[k], sin mover memoria.
                self.idx = (self.idx + 1) % np_
                fdl[self.idx] = X
                start = (np_ - 1 - self.idx) % np_
                acc = np.einsum("ij,ij->j", fdl, G2[start:start + np_])
                outs.append(np.fft.irfft(acc)[P:].astype(np.float32))
        allout = np.concatenate(outs)
        wet, self.outq = allout[:x.shape[0]], allout[x.shape[0]:]
        m = self.mix / 100.0
        return ((1 - 0.4 * m) * x + m * wet).astype(np.float32)


class OutputStage:
    def __init__(self, sr: int):
        self.gain_db = 0.0
        self.limit = False
        self.ceiling = db_to_lin(-1.0)
        self._g = 1.0
        self._lgain = 1.0

    def process(self, x: np.ndarray) -> np.ndarray:
        g = db_to_lin(self.gain_db)
        if g != self._g:
            x = x * np.linspace(self._g, g, x.shape[0], endpoint=False, dtype=np.float32)
            self._g = g
        elif g != 1.0:
            x = x * np.float32(g)
        if self.limit:
            peak = float(np.max(np.abs(x))) if x.size else 0.0
            need = self.ceiling / peak if peak > self.ceiling else 1.0
            start = self._lgain
            end = need if need < start else start + (1.0 - start) * 0.15
            x = x * np.linspace(start, end, x.shape[0], endpoint=False, dtype=np.float32)
            self._lgain = end
            x = np.clip(x, -self.ceiling, self.ceiling)
        return x.astype(np.float32)


# ===================================================================== cadena
class VoiceChain:
    """Cadena completa. ``set_params`` se puede llamar desde otro hilo."""

    def __init__(self, sr: int, params: dict | None = None):
        self.sr = sr
        self.hpf = FilterBank()
        self.spectral = Spectral(sr)
        self.tone = FilterBank()
        self.comp = Compressor(sr)
        self.drive = Drive()
        self.ring = RingMod(sr)
        self.chorus = Chorus(sr)
        self.echo = Echo(sr)
        self.reverb = Reverb(sr)
        self.out = OutputStage(sr)
        self.params = default_params()
        self._flags: dict[str, bool] = {}
        self.set_params(params or {})

    def set_params(self, params: dict) -> None:
        p = sanitize(params)
        sr = self.sr
        self.hpf.set([_biquad("hp", p["hpf_hz"], sr)] if p["hpf_enabled"] else [])
        sp = self.spectral
        sp.pitch_ratio = 2 ** (p["pitch"] / 12)
        sp.formant_ratio = 2 ** (p["formant"] / 12)
        sp.robot = p["robot"]
        sp.nr = p["noise_reduction"]
        tone = []
        for i, f in enumerate(EQ_FREQS):
            if p[f"eq{i}"] != 0 and f < sr * 0.45:
                tone.append(_biquad("peak", f, sr, p[f"eq{i}"], q=1.1))
        if p["bass"]:
            tone.append(_biquad("lowshelf", 120, sr, p["bass"]))
        if p["mid"]:
            tone.append(_biquad("peak", 1000, sr, p["mid"], q=0.8))
        if p["treble"]:
            tone.append(_biquad("highshelf", 6000, sr, p["treble"]))
        if p["lpf_enabled"]:
            tone.append(_biquad("lp", p["lpf_hz"], sr))
        self.tone.set(tone)
        self.comp.threshold, self.comp.ratio, self.comp.makeup = p["comp_threshold"], p["comp_ratio"], p["comp_makeup"]
        self.drive.distortion, self.drive.saturation, self.drive.lofi = p["distortion"], p["saturation"], p["lofi"]
        self.ring.freq, self.ring.mix = p["ring_hz"], p["ring_mix"]
        self.chorus.mix, self.chorus.rate, self.chorus.depth_ms = p["chorus_mix"], p["chorus_rate"], p["chorus_depth"]
        self.echo.mix, self.echo.delay_ms, self.echo.feedback = p["echo_mix"], p["echo_delay"], p["echo_feedback"]
        if p["reverb_mix"] > 0:
            self.reverb.configure(p["reverb_size"], p["reverb_damping"])
        self.reverb.mix = p["reverb_mix"]
        self.out.gain_db = p["gain"]
        self.out.limit = p["limiter_enabled"]
        self.out.ceiling = db_to_lin(p["limiter_ceiling"])
        was_spectral = self._flags.get("spectral", False)
        self._flags = {
            "spectral": sp.active(),
            "comp": p["comp_enabled"],
            "drive": p["distortion"] > 0 or p["saturation"] > 0 or p["lofi"] > 0,
            "ring": p["ring_hz"] > 0 and p["ring_mix"] > 0,
            "chorus": p["chorus_mix"] > 0,
            "echo": p["echo_mix"] > 0,
            "reverb": p["reverb_mix"] > 0,
        }
        if self._flags["spectral"] and not was_spectral:
            sp.reset_pending = True  # se reinicia en el hilo de audio
        self.params = p

    @property
    def latency_samples(self) -> int:
        return self.spectral.latency if self._flags.get("spectral") else 0

    def process(self, x: np.ndarray) -> np.ndarray:
        f = self._flags
        x = self.hpf.process(x)
        if f.get("spectral"):
            x = self.spectral.process(x)
        x = self.tone.process(x)
        if f.get("comp"):
            x = self.comp.process(x)
        if f.get("drive"):
            x = self.drive.process(x)
        if f.get("ring"):
            x = self.ring.process(x)
        if f.get("chorus"):
            x = self.chorus.process(x)
        if f.get("echo"):
            x = self.echo.process(x)
        if f.get("reverb"):
            x = self.reverb.process(x)
        return self.out.process(x)


# =========================================================== uso con archivos
def process_offline(audio: np.ndarray, sr: int, params: dict, block: int = 1024) -> np.ndarray:
    """Aplica la cadena a un archivo completo y compensa la latencia."""
    chain = VoiceChain(sr, params)
    lat = chain.latency_samples
    tail = int(sr * (3.5 if chain.params["reverb_mix"] > 0 or chain.params["echo_mix"] > 0 else 0.1))
    x = np.concatenate([audio.astype(np.float32), np.zeros(lat + tail, np.float32)])
    out = np.concatenate([chain.process(x[i:i + block]) for i in range(0, x.shape[0], block)])
    return out[lat:lat + audio.shape[0] + tail]


def time_stretch(audio: np.ndarray, rate: float, n: int = 2048, hop: int = 512) -> np.ndarray:
    """Cambia la duración sin cambiar el tono (vocoder de fase). rate>1 acelera."""
    if abs(rate - 1.0) < 1e-3 or audio.size < n:
        return audio.astype(np.float32)
    win = np.hanning(n)
    frames = range(0, audio.shape[0] - n, hop)
    spec = np.array([np.fft.rfft(audio[i:i + n] * win) for i in frames])
    steps = np.arange(0, spec.shape[0] - 1, rate)
    phase = np.angle(spec[0])
    expected = 2 * np.pi * hop * np.arange(n // 2 + 1) / n
    out = np.zeros(int(len(steps) * hop + n))
    for j, s in enumerate(steps):
        i = int(s)
        frac = s - i
        mag = (1 - frac) * np.abs(spec[i]) + frac * np.abs(spec[i + 1])
        frame = np.fft.irfft(mag * np.exp(1j * phase), n) * win
        out[j * hop:j * hop + n] += frame
        dphi = np.angle(spec[i + 1]) - np.angle(spec[i]) - expected
        dphi -= 2 * np.pi * np.round(dphi / (2 * np.pi))
        phase = phase + expected + dphi
    out /= np.sum(win ** 2) / hop
    return out.astype(np.float32)


def change_speed(audio: np.ndarray, rate: float) -> np.ndarray:
    """Velocidad de reproducción (cambia duración y tono, como una cinta)."""
    if abs(rate - 1.0) < 1e-3:
        return audio.astype(np.float32)
    idx = np.arange(0, audio.shape[0] - 1, rate)
    return np.interp(idx, np.arange(audio.shape[0]), audio).astype(np.float32)


# ================================================================== preajustes
PRESETS: dict[str, dict] = {
    "muy_grave": {"label": "Voz muy grave", "params": {"pitch": -9, "formant": -4, "bass": 3, "comp_enabled": True, "comp_threshold": -22, "comp_ratio": 3}},
    "grave": {"label": "Voz grave", "params": {"pitch": -4, "formant": -2, "bass": 2}},
    "aguda": {"label": "Voz aguda", "params": {"pitch": 5, "formant": 2, "treble": 2}},
    "infantil": {"label": "Voz infantil ficticia", "params": {"pitch": 7, "formant": 5, "treble": 3, "bass": -4}},
    "robot": {"label": "Voz robótica", "params": {"robot": True, "ring_hz": 60, "ring_mix": 35, "chorus_mix": 20, "hpf_enabled": True, "hpf_hz": 120}},
    "monstruo": {"label": "Voz de monstruo", "params": {"pitch": -8, "formant": -6, "distortion": 20, "saturation": 40, "reverb_mix": 22, "reverb_size": 70, "bass": 4}},
    "radio": {"label": "Voz de radio", "params": {"hpf_enabled": True, "hpf_hz": 250, "lpf_enabled": True, "lpf_hz": 4500, "mid": 4, "saturation": 35, "comp_enabled": True, "comp_threshold": -28, "comp_ratio": 6, "comp_makeup": 6}},
    "telefono": {"label": "Voz de teléfono", "params": {"hpf_enabled": True, "hpf_hz": 380, "lpf_enabled": True, "lpf_hz": 3200, "mid": 5, "lofi": 25, "saturation": 20}},
    "megafono": {"label": "Voz de megáfono", "params": {"hpf_enabled": True, "hpf_hz": 600, "lpf_enabled": True, "lpf_hz": 3800, "mid": 8, "distortion": 45, "reverb_mix": 12, "reverb_size": 30}},
    "alien": {"label": "Voz de extraterrestre", "params": {"pitch": 3, "formant": 7, "ring_hz": 420, "ring_mix": 45, "chorus_mix": 40, "chorus_rate": 2.2, "echo_mix": 18, "echo_delay": 140}},
    "videojuego": {"label": "Voz de videojuego", "params": {"pitch": 2, "lofi": 70, "hpf_enabled": True, "hpf_hz": 200, "comp_enabled": True, "comp_threshold": -24}},
}
