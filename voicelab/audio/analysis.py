"""Análisis y limpieza de voz para clonación, grabación y editor."""

from __future__ import annotations

import numpy as np
from scipy.signal import butter, sosfiltfilt

from .dsp import lin_to_db

FRAME_S = 0.03


def _frames_rms(x: np.ndarray, sr: int) -> np.ndarray:
    n = int(sr * FRAME_S)
    k = x.shape[0] // n
    if k == 0:
        return np.zeros(0)
    f = x[: k * n].reshape(k, n)
    return np.sqrt(np.mean(f * f, axis=1) + 1e-12)


def speech_mask(x: np.ndarray, sr: int) -> np.ndarray:
    """Tramas de 30 ms con voz (umbral adaptativo sobre el ruido de fondo)."""
    rms = _frames_rms(x, sr)
    if rms.size == 0:
        return np.zeros(0, bool)
    db = 20 * np.log10(rms)
    floor = np.percentile(db, 10)
    thr = max(floor + 10.0, -55.0)
    mask = db > thr
    # Rellena huecos cortos (pausas entre sílabas < 200 ms)
    gap = int(0.2 / FRAME_S)
    idx = np.flatnonzero(mask)
    for a, b in zip(idx[:-1], idx[1:]):
        if 1 < b - a <= gap:
            mask[a:b] = True
    return mask


def estimate_f0(x: np.ndarray, sr: int, mask: np.ndarray) -> np.ndarray:
    """Tono fundamental por autocorrelación en tramas con voz (60–500 Hz)."""
    n = int(sr * 0.04)
    hop = int(sr * FRAME_S)
    lo, hi = int(sr / 500), int(sr / 60)
    f0s = []
    for i in np.flatnonzero(mask)[:: max(1, int(mask.sum() // 400) or 1)]:
        seg = x[i * hop: i * hop + n]
        if seg.shape[0] < n:
            continue
        seg = seg - seg.mean()
        ac = np.fft.irfft(np.abs(np.fft.rfft(seg, 2 * n)) ** 2)[: hi + 1]
        if ac[0] <= 0:
            continue
        lag = lo + int(np.argmax(ac[lo:hi]))
        if ac[lag] / ac[0] > 0.45:
            f0s.append(sr / lag)
    return np.array(f0s)


def analyze(x: np.ndarray, sr: int) -> dict:
    mask = speech_mask(x, sr)
    rms = _frames_rms(x, sr)
    speech_s = float(mask.sum() * FRAME_S)
    total_s = float(x.shape[0] / sr)
    if mask.any() and (~mask).any():
        snr = float(20 * np.log10(np.mean(rms[mask]) / (np.mean(rms[~mask]) + 1e-9)))
    elif mask.any():
        snr = 40.0
    else:
        snr = 0.0
    level = lin_to_db(float(np.mean(rms[mask]))) if mask.any() else -120.0
    clip = float(np.mean(np.abs(x) > 0.99)) if x.size else 0.0
    f0 = estimate_f0(x, sr, mask) if mask.any() else np.array([])
    warnings = []
    if snr < 15:
        warnings.append("Hay bastante ruido de fondo: activa la limpieza o usa una grabación más limpia.")
    if clip > 0.001:
        warnings.append("La grabación está saturada en algunos tramos; el modelo copiará esa distorsión.")
    if level < -40:
        warnings.append("El volumen de la voz es muy bajo.")
    if speech_s < 10:
        tier, label = "insufficient", "Insuficiente: hacen falta al menos 10 segundos de voz"
    elif speech_s < 300:
        tier, label = "instant", "Suficiente para un perfil de IA instantánea (10–30 s recomendado)"
    elif speech_s < 600:
        tier, label = "rvc_basic", "Suficiente para un modelo RVC básico (5–10 min)"
    else:
        tier, label = "rvc_good", "Suficiente para un modelo RVC de calidad (10 min o más)"
    return {
        "total_s": round(total_s, 2), "speech_s": round(speech_s, 2),
        "speech_ratio": round(speech_s / total_s, 3) if total_s else 0.0,
        "snr_db": round(snr, 1), "level_db": round(level, 1), "clip_ratio": round(clip, 5),
        "f0_median": round(float(np.median(f0)), 1) if f0.size else None,
        "f0_p10": round(float(np.percentile(f0, 10)), 1) if f0.size else None,
        "f0_p90": round(float(np.percentile(f0, 90)), 1) if f0.size else None,
        "tier": tier, "tier_label": label, "warnings": warnings,
    }


def normalize(x: np.ndarray, peak_db: float = -1.0) -> np.ndarray:
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    if peak < 1e-6:
        return x.astype(np.float32)
    return (x * (10 ** (peak_db / 20) / peak)).astype(np.float32)


def denoise(x: np.ndarray, sr: int, strength: float = 0.7) -> np.ndarray:
    """Reducción de ruido estacionario: perfil de ruido tomado de los tramos sin voz."""
    n, hop = 2048, 512
    if x.shape[0] < n * 2:
        return x.astype(np.float32)
    win = np.hanning(n)
    pad = np.concatenate([np.zeros(n), x, np.zeros(n)])
    starts = range(0, pad.shape[0] - n, hop)
    spec = np.array([np.fft.rfft(pad[i:i + n] * win) for i in starts])
    power = np.abs(spec) ** 2
    frame_db = 10 * np.log10(power.mean(axis=1) + 1e-12)
    quiet = frame_db <= np.percentile(frame_db, 15)
    noise = np.median(power[quiet], axis=0) if quiet.any() else power.min(axis=0)
    gain = np.clip(1 - (1 + 2 * strength) * noise / (power + 1e-12), 10 ** (-(10 + 20 * strength) / 20), 1)
    # Suavizado temporal para evitar «ruido musical»
    from scipy.ndimage import uniform_filter1d
    gain = uniform_filter1d(gain, size=3, axis=0)
    out = np.zeros(pad.shape[0])
    for j, i in enumerate(starts):
        out[i:i + n] += np.fft.irfft(spec[j] * gain[j], n) * win
    out /= np.sum(win ** 2) / hop
    return out[n:n + x.shape[0]].astype(np.float32)


def highpass(x: np.ndarray, sr: int, hz: float = 70.0) -> np.ndarray:
    sos = butter(2, hz, "highpass", fs=sr, output="sos")
    return sosfiltfilt(sos, x).astype(np.float32)


def remove_silences(x: np.ndarray, sr: int, min_silence: float = 0.6, keep: float = 0.2) -> np.ndarray:
    """Acorta los silencios de más de ``min_silence`` s dejando ``keep`` s."""
    mask = speech_mask(x, sr)
    hop = int(sr * FRAME_S)
    keep_frames = int(keep / FRAME_S)
    out, i = [], 0
    while i < mask.size:
        j = i
        while j < mask.size and mask[j] == mask[i]:
            j += 1
        a, b = i * hop, j * hop
        if not mask[i] and (j - i) * FRAME_S > min_silence:
            out.append(x[a:a + keep_frames * hop // 2])
            out.append(x[b - keep_frames * hop // 2:b])
        else:
            out.append(x[a:b])
        i = j
    out.append(x[mask.size * hop:])
    return np.concatenate(out).astype(np.float32) if out else x


def best_segment(x: np.ndarray, sr: int, seconds: float = 20.0) -> tuple[int, int]:
    """Tramo con más voz (para la referencia de clonación instantánea)."""
    mask = speech_mask(x, sr).astype(float)
    win = int(seconds / FRAME_S)
    if mask.size <= win:
        return 0, x.shape[0]
    score = np.convolve(mask, np.ones(win), "valid")
    i = int(np.argmax(score))
    hop = int(sr * FRAME_S)
    return i * hop, min(x.shape[0], (i + win) * hop)


def clean_for_cloning(x: np.ndarray, sr: int, denoise_strength: float = 0.6, trim: bool = True) -> np.ndarray:
    y = highpass(x, sr)
    if denoise_strength > 0:
        y = denoise(y, sr, denoise_strength)
    if trim:
        y = remove_silences(y, sr, 0.5, 0.25)
    return normalize(y, -1.0)


def waveform(x: np.ndarray, points: int = 1600) -> list[list[float]]:
    """Pares mínimo/máximo para dibujar la forma de onda."""
    if x.size == 0:
        return []
    points = max(1, min(points, x.shape[0]))
    k = x.shape[0] // points
    if k < 1:
        return [[float(v), float(v)] for v in x]
    f = x[: k * points].reshape(points, k)
    return np.round(np.stack([f.min(axis=1), f.max(axis=1)], axis=1), 4).tolist()
