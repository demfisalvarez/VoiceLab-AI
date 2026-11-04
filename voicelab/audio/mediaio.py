"""Lectura y escritura de audio y vídeo.

WAV se lee y escribe directamente. El resto (MP3, FLAC, M4A, AAC, OGG, MP4,
MKV, MOV, WEBM…) pasa por FFmpeg, que en Windows instala el paquete
``imageio-ffmpeg`` junto con la aplicación.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

INPUT_FORMATS = (".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".mp4", ".mkv", ".mov", ".webm")
VIDEO_FORMATS = (".mp4", ".mkv", ".mov", ".webm")
EXPORT_FORMATS = ("wav", "mp3", "flac", "ogg")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class MediaError(RuntimeError):
    pass


def find_ffmpeg() -> str | None:
    env = os.environ.get("VOICELAB_FFMPEG")
    if env and Path(env).exists():
        return env
    try:
        import imageio_ffmpeg  # type: ignore
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    return shutil.which("ffmpeg")


def _run(args: list[str], stdin: bytes | None = None) -> subprocess.CompletedProcess:
    exe = find_ffmpeg()
    if not exe:
        raise MediaError("No se encuentra FFmpeg. Vuelve a ejecutar el instalador de VoiceLab AI.")
    return subprocess.run([exe, "-hide_banner", "-nostdin", *args], input=stdin, capture_output=True,
                          creationflags=_NO_WINDOW)


def probe(path: str | Path) -> dict:
    """Duración y si tiene vídeo/audio, leyendo la cabecera con FFmpeg."""
    path = Path(path)
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path)) as w:
                return {"duration": w.getnframes() / w.getframerate(), "video": False, "audio": True}
        except (wave.Error, EOFError):
            pass
    r = _run(["-i", str(path)])
    text = r.stderr.decode("utf-8", "replace")
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", text)
    dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None
    return {"duration": dur, "video": bool(re.search(r"Stream #\S+.*Video:", text)),
            "audio": bool(re.search(r"Stream #\S+.*Audio:", text))}


def _read_wav(path: Path, sr: int) -> np.ndarray | None:
    try:
        w = wave.open(str(path))
    except (wave.Error, EOFError):
        return None  # p. ej. WAV en coma flotante: lo lee FFmpeg
    with w:
        ch, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if width == 2:
        x = np.frombuffer(raw, "<i2").astype(np.float32) / 32768.0
    elif width == 3:
        b = np.frombuffer(raw, np.uint8).reshape(-1, 3)
        x = ((b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16)) << 8 >> 8)
        x = x.astype(np.float32) / 8388608.0
    elif width == 4:
        x = np.frombuffer(raw, "<i4").astype(np.float32) / 2147483648.0
    elif width == 1:
        x = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128) / 128.0
    else:
        return None
    x = x.reshape(-1, ch).mean(axis=1)
    if rate != sr:
        x = resample(x, rate, sr)
    return x.astype(np.float32)


def resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst:
        return x.astype(np.float32)
    from math import gcd

    from scipy.signal import resample_poly
    g = gcd(src, dst)
    return resample_poly(x, dst // g, src // g).astype(np.float32)


def load_audio(path: str | Path, sr: int = 48000) -> np.ndarray:
    """Devuelve audio mono float32 a ``sr``. Si es un vídeo, extrae su pista de audio."""
    path = Path(path)
    if not path.exists():
        raise MediaError(f"No existe el archivo «{path.name}».")
    if path.suffix.lower() == ".wav":
        x = _read_wav(path, sr)
        if x is not None:
            return x
    r = _run(["-i", str(path), "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-acodec", "pcm_f32le", "-"])
    if r.returncode != 0 or not r.stdout:
        err = r.stderr.decode("utf-8", "replace")
        if "does not contain any stream" in err or "Output file #0 does not contain" in err or "matches no streams" in err:
            raise MediaError(f"«{path.name}» no tiene pista de audio.")
        raise MediaError(f"No se pudo leer «{path.name}». ¿Es un archivo de audio o vídeo válido?")
    return np.frombuffer(r.stdout, "<f4").astype(np.float32)


def save_wav(path: str | Path, audio: np.ndarray, sr: int) -> Path:
    path = Path(path)
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return path


def export(path: str | Path, audio: np.ndarray, sr: int, fmt: str | None = None) -> Path:
    path = Path(path)
    fmt = (fmt or path.suffix.lstrip(".")).lower()
    if fmt not in EXPORT_FORMATS:
        raise MediaError(f"Formato no admitido: {fmt}")
    path = path.with_suffix("." + fmt)
    if fmt == "wav":
        return save_wav(path, audio, sr)
    codecs = {"mp3": [["-c:a", "libmp3lame", "-b:a", "192k"]],
              "flac": [["-c:a", "flac"]],
              "ogg": [["-c:a", "libvorbis", "-q:a", "6"], ["-c:a", "libopus", "-b:a", "128k"],
                      ["-c:a", "vorbis", "-strict", "-2", "-ac", "2"]]}[fmt]
    data = np.clip(audio, -1, 1).astype("<f4").tobytes()
    last = ""
    for codec in codecs:
        r = _run(["-y", "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "-", *codec, str(path)], stdin=data)
        if r.returncode == 0 and path.exists():
            return path
        last = r.stderr.decode("utf-8", "replace")[-300:]
    raise MediaError(f"No se pudo exportar a {fmt.upper()}: {last}")
