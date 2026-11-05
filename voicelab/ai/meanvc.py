"""Voz instantánea en directo (experimental): MeanVC2 en un proceso aparte.

Con unos segundos de audio de referencia (los de un perfil de «Clonar voz»)
convierte la voz del micrófono en tiempo real, sin entrenar nada. Es
conversión *zero-shot*: el timbre se parece al de la referencia, pero menos
que con un modelo RVC entrenado con esa voz.

Piezas:
* ``vc-runtime``: entorno de Python aparte con PyTorch para CPU (se instala a
  petición, unos 200 MB de descarga). La app principal nunca importa PyTorch.
* ``meanvc_worker.py``: proceso que carga MeanVC2 y atiende peticiones por
  tuberías (protocolo binario sencillo).
* :class:`RealtimeMeanVC`: procesador para el motor de audio. Remuestrea a
  16 kHz, envía bloques del tamaño natural del modelo (80 o 160 ms) y devuelve
  el audio convertido con un búfer adaptativo: el mínimo retraso sin cortes.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

from .. import paths
from ..audio.resampler import StreamResampler
from ..audio.ringbuffer import RingBuffer
from . import meanvc_worker as proto
from . import models

log = logging.getLogger(__name__)
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

MODEL_KEY = "meanvc2"
SR16 = proto.SR
CHUNK16 = proto.CHUNK
VARIANTS = {"40ms": "Baja latencia (≈ 0,25 s · más CPU)", "120ms": "Calidad (voz más parecida · ≈ 0,45 s)"}
# Medido en Windows con los modelos reales: el modo de baja latencia gasta ~3 veces más CPU.
# Se elige solo si este PC lo mueve con holgura (cálculo < 60 % del tiempo real).
LOW_LATENCY_MAX_RTF = 0.6
_ABOVE_NORMAL = 0x00008000 if sys.platform == "win32" else 0   # prioridad alta (sin llegar a tiempo real)


def packages(version: tuple = sys.version_info[:2]) -> list[str]:
    """PyTorch 2.5.1 (la versión que fija MeanVC2); con Python 3.13 hace falta la 2.6."""
    if tuple(version) >= (3, 13):
        base = ["torch==2.6.0", "torchaudio==2.6.0", "numpy>=2.1,<2.3"]
    else:
        base = ["torch==2.5.1", "torchaudio==2.5.1", "numpy>=1.26,<2.1"]
    return base + ["einops==0.8.0", "x-transformers==2.2.11", "safetensors>=0.4"]


RUNTIME_DOWNLOAD_GB = 0.25
RUNTIME_DISK_GB = 1.1
EMB_FILE = "meanvc_voice.json"


class WorkerError(RuntimeError):
    pass


# ----------------------------------------------------------------- rutas
def code_dir() -> Path:
    return Path(__file__).with_name("vendor") / "meanvc2"


def worker_script() -> Path:
    # VOICELAB_MEANVC_WORKER permite probar la interfaz con un proceso simulado (desarrollo).
    env = os.environ.get("VOICELAB_MEANVC_WORKER")
    return Path(env) if env else Path(__file__).with_name("meanvc_worker.py")


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _app_root() -> Path | None:
    """Carpeta de instalación (…\\VoiceLab AI) si la app corre desde el instalador clásico (.bat)."""
    try:
        root = Path(sys.executable).resolve().parents[2]
    except IndexError:
        return None
    return root if (root / "bin" / "uv.exe").exists() else None


def _uv() -> Path | None:
    """uv (gestor de Python y paquetes) que acompaña a la app."""
    cands = []
    if _frozen():
        exe_dir = Path(sys.executable).resolve().parent
        cands += [exe_dir / "bin" / "uv.exe", Path(getattr(sys, "_MEIPASS", exe_dir)) / "bin" / "uv.exe"]
    root = _app_root()
    if root:
        cands.append(root / "bin" / "uv.exe")
    return next((c for c in cands if c.exists()), None)


def _writable(d: Path) -> bool:
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".vl-probe"
        probe.write_text("ok")
        probe.unlink()
        return True
    except OSError:
        return False


def runtime_dir() -> Path:
    env = os.environ.get("VOICELAB_VC_RUNTIME")
    if env:
        return Path(env)
    if _frozen():                       # junto al .exe (instalación por usuario) o en LOCALAPPDATA
        exe_dir = Path(sys.executable).resolve().parent
        if _writable(exe_dir):
            return exe_dir / "vc-runtime"
        return Path(os.environ.get("LOCALAPPDATA", str(paths.data_dir()))) / "VoiceLabAI" / "vc-runtime"
    root = _app_root()
    return root / "vc-runtime" if root else paths.data_dir() / "vc-runtime"


def runtime_python() -> Path:
    d = runtime_dir()
    return d / "Scripts" / "python.exe" if sys.platform == "win32" else d / "bin" / "python"


def runtime_ready() -> bool:
    return runtime_python().exists() and (runtime_dir() / ".complete").exists()


def weights_dir() -> Path:
    return models.model_dir(MODEL_KEY)


def installed() -> bool:
    """Listo para usar: entorno, pesos y la prueba final superada (``bench.json``)."""
    return runtime_ready() and models.installed(MODEL_KEY) and bench() is not None


def bench(variant: str = "120ms") -> dict | None:
    """Velocidad medida al instalar (``bench.json`` es el modo «120ms», ``bench_40ms.json`` el otro)."""
    f = weights_dir() / ("bench.json" if variant == "120ms" else f"bench_{variant}.json")
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def recommended_variant() -> str:
    """Baja latencia si este PC la mueve con holgura; si no (o no se midió), calidad."""
    b = bench("40ms") or {}
    return "40ms" if b.get("rtf", 9.0) < LOW_LATENCY_MAX_RTF else "120ms"


def _bundled_python() -> Path | None:
    """Python 3.12 completo que acompaña al .exe (carpeta «pybase»), sin enlaces ni uniones.

    No se usa el Python «gestionado» de uv porque uv crea una unión de directorio
    (cpython-3.12-…) y Windows 11 puede bloquear recorrerla: «La ruta no se puede
    recorrer porque contiene un punto de montaje no confiable (os error 448)».
    """
    exe_dir = Path(sys.executable).resolve().parent
    for c in (exe_dir / "pybase" / "python.exe", Path(getattr(sys, "_MEIPASS", exe_dir)) / "pybase" / "python.exe"):
        if c.exists():
            return c
    return None


def supported() -> bool:
    """El ejecutable empaquetado necesita su «uv» y su Python base para crear el entorno de PyTorch."""
    return not _frozen() or (_uv() is not None and _bundled_python() is not None)


def _runtime_version() -> tuple:
    """Versión de Python del entorno de PyTorch (en el ejecutable se descarga la 3.12)."""
    return (3, 12) if _frozen() else tuple(sys.version_info[:2])


def status() -> dict:
    m = models.CATALOG[MODEL_KEY]
    return {"installed": installed(), "runtime": runtime_ready(), "weights": models.installed(MODEL_KEY),
            "supported": supported(), "hd": hd_installed(), "hd_mb": 119,
            "name": m["name"], "license": m["license"], "repo": m["repo"],
            "download_gb": round(m["approx_gb"] + RUNTIME_DOWNLOAD_GB, 1),
            "disk_gb": round(m["approx_gb"] + RUNTIME_DISK_GB, 1),
            "variants": VARIANTS, "bench": bench(), "bench_40ms": bench("40ms"), "bench_hd": bench_hd(),
            "recommended": recommended_variant()}


HD_KEY = "apbwe"


def hd_installed() -> bool:
    return models.installed(HD_KEY)


def hd_weights() -> Path:
    return models.model_dir(HD_KEY) / "apbwe_16kto48k.pt"


def worker_command(variant: str = "120ms", threads: int = 1, hd: bool = False, chunk: int = 0) -> list[str]:
    cmd = [str(runtime_python()), "-I", str(worker_script()), "--code", str(code_dir()),
           "--weights", str(weights_dir()), "--model", variant, "--threads", str(threads)]
    if hd:
        cmd += ["--hd", str(hd_weights())]
    if chunk:
        cmd += ["--chunk", str(int(chunk))]
    return cmd


# ------------------------------------------------------------ instalación
def _base_python() -> Path:
    exe = Path(getattr(sys, "_base_executable", "") or sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").exists():
        exe = exe.with_name("python.exe")
    return exe


def _run(cmd: list[str], what: str, env: dict | None = None) -> None:
    log.info("Ejecutando: %s", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=_NO_WINDOW, env=env,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "")[-1200:]
        log.error("%s falló:\n%s", what, tail)
        raise RuntimeError(f"{what} falló:\n{tail}")


def install_runtime(progress) -> None:
    """Crea ``vc-runtime`` (Python aparte) e instala PyTorch para CPU y lo necesario."""
    d = runtime_dir()
    uv = _uv()
    pkgs = packages(_runtime_version())
    progress(0.05)
    if d.exists() and not (d / ".complete").exists():
        shutil.rmtree(d, ignore_errors=True)            # instalación anterior a medias
    old = d.parent / "vc-python"                        # Python de uv de la v0.7.0 (con uniones): ya no se usa
    if _frozen() and old.exists():
        shutil.rmtree(old, ignore_errors=True)
    d.parent.mkdir(parents=True, exist_ok=True)
    env = None
    if uv is not None:
        if _frozen():
            base = _bundled_python()
            if base is None:
                raise RuntimeError("Falta la carpeta «pybase» junto a VoiceLab AI.exe; reinstala la aplicación.")
            pyspec = str(base)
            env = dict(os.environ, UV_PYTHON_DOWNLOADS="never")      # nunca un Python con uniones de uv
        else:
            pyspec = str(_base_python())
        if not runtime_python().exists():
            _run([str(uv), "venv", "--no-config", "--python", pyspec, str(d)], "Crear el entorno de PyTorch", env)
        progress(0.15)
        _run([str(uv), "pip", "install", "--no-config", "--no-cache", "--python", str(runtime_python()), *pkgs],
             "Instalar PyTorch (CPU)", env)
    elif _frozen():
        raise RuntimeError("Falta «uv» junto a VoiceLab AI.exe; reinstala la aplicación.")
    else:                                               # ejecución desde el código fuente
        if not runtime_python().exists():
            _run([str(_base_python()), "-m", "venv", str(d)], "Crear el entorno de PyTorch")
        progress(0.15)
        extra = [] if sys.platform == "win32" else ["--extra-index-url", "https://download.pytorch.org/whl/cpu"]
        _run([str(runtime_python()), "-m", "pip", "install", "--disable-pip-version-check", *extra, *pkgs],
             "Instalar PyTorch (CPU)")
    _check_no_junctions(d)
    (d / ".complete").write_text(json.dumps({"packages": pkgs}), encoding="utf-8")
    progress(1.0)


def _check_no_junctions(d: Path) -> None:
    """El entorno no debe depender de uniones de directorio (Windows puede bloquearlas)."""
    if sys.platform != "win32":
        return
    cfg = d / "pyvenv.cfg"
    try:
        home = next((ln.split("=", 1)[1].strip() for ln in cfg.read_text(encoding="utf-8").splitlines()
                     if ln.lower().startswith("home")), "")
    except OSError:
        return
    p = Path(home)
    while p != p.parent:
        if getattr(p, "is_junction", lambda: False)() or p.is_symlink():
            raise RuntimeError(f"El entorno de PyTorch depende de un enlace de directorio ({p}), que Windows "
                               "puede bloquear. Pulsa «Instalar» otra vez.")
        p = p.parent


def selftest(variant: str = "120ms", seconds: float = 4.0, hd: bool = False) -> dict:
    """Carga todo, calcula una huella de prueba y mide la velocidad real en este PC."""
    rng = np.random.default_rng(1)
    t = np.arange(int(SR16 * 2)) / SR16
    probe = (0.2 * np.sin(2 * np.pi * 140 * t) * (1 + 0.3 * np.sin(2 * np.pi * 3 * t))
             + 0.02 * rng.standard_normal(t.shape[0])).astype(np.float32)
    w = MeanVCWorker(worker_command(variant, hd=hd))
    try:
        emb = w.compute_embedding(probe)
        if emb.shape != (proto.EMB_DIM,) or not np.all(np.isfinite(emb)):
            raise WorkerError("La huella de voz calculada no es válida.")
        w.set_embedding(emb)
        c = int(w.hello.get("chunk", CHUNK16))
        n = max(3, int(seconds * SR16 / c))
        times, produced = [], 0
        for i in range(n):
            t0 = time.perf_counter()
            produced += w.process(probe[(i * c) % (probe.shape[0] - c):][:c]).shape[0]
            times.append(time.perf_counter() - t0)
        if produced == 0:
            raise WorkerError("El modelo no devolvió audio en la prueba.")
        ms = float(np.median(times[1:]) * 1000)
        res = {"variant": variant, "ms_per_chunk": round(ms, 1), "chunk_ms": c / SR16 * 1000,
               "rtf": round(ms / (c / SR16 * 1000), 3), "torch": w.hello.get("torch"),
               "hd": bool(w.hello.get("hd"))}
    finally:
        w.close()
    return res


def install(progress) -> dict:
    """Instalación completa: entorno de PyTorch, pesos y prueba de funcionamiento."""
    if not supported():
        raise RuntimeError("Falta «uv» junto a VoiceLab AI.exe: reinstala la aplicación para poder instalar "
                           "la voz instantánea en directo.")
    if not runtime_ready():
        install_runtime(lambda p: progress(p * 0.3))
    progress(0.3)
    if not models.installed(MODEL_KEY):
        models.install(MODEL_KEY, lambda p: progress(0.3 + p * 0.6))
    progress(0.9)
    res = selftest("120ms")
    (weights_dir() / "bench.json").write_text(json.dumps(res), encoding="utf-8")
    try:                                     # el modo de baja latencia gasta más: se mide aparte
        low = selftest("40ms")
        (weights_dir() / "bench_40ms.json").write_text(json.dumps(low), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        low = None
        log.warning("No se pudo medir el modo de baja latencia: %s", exc)
    hd_error = None
    try:                                     # alta definición: opcional, no impide usar la voz en directo
        install_hd(lambda p: progress(0.92 + p * 0.08))
    except Exception as exc:  # noqa: BLE001
        hd_error = str(exc)
        log.warning("Alta definición no disponible: %s", exc)
    progress(1.0)
    return {"installed": True, "bench": res, "bench_40ms": low, "variant": recommended_variant(),
            "hd": hd_installed(), "hd_error": hd_error, "bench_hd": bench_hd()}


def install_hd(progress) -> dict:
    """Descarga AP-BWE (120 MB) y mide la velocidad con la alta definición activada."""
    if not models.installed(HD_KEY):
        models.install(HD_KEY, lambda p: progress(p * 0.7))
    res = selftest("120ms", hd=True)
    (models.model_dir(HD_KEY) / "bench.json").write_text(json.dumps(res), encoding="utf-8")
    progress(1.0)
    return {"hd": True, "bench_hd": res}


def hd_allowed(variant: str) -> bool:
    """La alta definición solo en modo «Calidad» y si la CPU la aguanta.

    Medido en Windows: con bloques de 80 ms (baja latencia) la HD cuesta más del doble y no
    mejora la voz (DNSMOS 3,19 → 2,96); con «Calidad» apenas cambia (3,24 → 3,28).
    """
    return variant == "120ms" and hd_installed() and (bench_hd() or {}).get("rtf", 1.0) < 0.85


def bench_hd() -> dict | None:
    try:
        return json.loads((models.model_dir(HD_KEY) / "bench.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def remove() -> None:
    models.remove(MODEL_KEY)
    models.remove(HD_KEY)
    d = runtime_dir()
    for _ in range(10):                        # Windows: las DLL tardan un instante en liberarse
        if not d.exists():
            break
        shutil.rmtree(d, ignore_errors=True)
        time.sleep(0.5)
    py = d.parent / "vc-python"                 # restos de versiones que usaban el Python de uv
    if py.exists():
        shutil.rmtree(py, ignore_errors=True)
    if d.exists():
        raise RuntimeError(f"No se pudo borrar por completo {d}. Cierra VoiceLab AI y bórrala a mano.")


# ---------------------------------------------------------- huella de voz
def _ref_signature(ref: Path) -> dict:
    st = ref.stat()
    return {"size": st.st_size, "mtime": int(st.st_mtime)}


def cached_embedding(profile_dir: Path) -> np.ndarray | None:
    ref = profile_dir / "reference.wav"
    try:
        data = json.loads((profile_dir / EMB_FILE).read_text(encoding="utf-8"))
        if data.get("ref") != _ref_signature(ref):
            return None
        emb = np.asarray(data["embedding"], np.float32)
        return emb if emb.shape == (proto.EMB_DIM,) and np.all(np.isfinite(emb)) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def profile_embedding(worker: "MeanVCWorker", profile_dir: Path) -> np.ndarray:
    """Huella del perfil: la guardada o, la primera vez, calculada y guardada."""
    emb = cached_embedding(profile_dir)
    if emb is not None:
        return emb
    from ..audio import mediaio
    ref = profile_dir / "reference.wav"
    if not ref.exists():
        raise WorkerError("Ese perfil no tiene audio de referencia.")
    audio = mediaio.load_audio(ref, SR16)
    if audio.shape[0] < SR16 * 3:
        raise WorkerError("La referencia es demasiado corta (mínimo 3 segundos de voz).")
    emb = worker.compute_embedding(audio)
    (profile_dir / EMB_FILE).write_text(json.dumps({"ref": _ref_signature(ref), "embedding": emb.tolist()}),
                                        encoding="utf-8")
    return emb


# ------------------------------------------------------------- el proceso
class MeanVCWorker:
    """Proceso de MeanVC2. Las llamadas son síncronas y seguras entre hilos."""

    def __init__(self, cmd: list[str], start_timeout: float = 240.0, env: dict | None = None,
                 realtime: bool = False):
        self._lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._closed = False
        self._log = open(paths.logs_dir() / "voz-instantanea.log", "wb")  # noqa: SIM115
        try:
            # En directo, prioridad «por encima de lo normal»: un juego o el navegador no lo retrasan.
            flags = _NO_WINDOW | (_ABOVE_NORMAL if realtime else 0)
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._log,
                                         creationflags=flags, env=env)
        except OSError as exc:
            self._log.close()
            raise WorkerError(f"No se pudo iniciar el motor de voz instantánea: {exc}") from exc
        kind, data = self._call(None, b"", start_timeout)
        self.hello = self._json(kind, data)

    # -- canal
    def _kill(self) -> None:
        try:
            self.proc.kill()
        except OSError:
            pass

    def _call(self, kind: bytes | None, payload: bytes, timeout: float | None) -> tuple[bytes, bytes]:
        with self._lock:
            if self.proc.poll() is not None:
                raise WorkerError(self._died())
            timer = threading.Timer(timeout, self._kill) if timeout else None
            if timer:
                timer.daemon = True
                timer.start()
            try:
                if kind is not None:
                    proto.send(self.proc.stdin, kind, payload)
                return proto.recv(self.proc.stdout)
            except (EOFError, OSError, ValueError) as exc:
                if timer and not timer.is_alive():
                    raise WorkerError("El motor de voz instantánea no respondió a tiempo.") from exc
                raise WorkerError(self._died()) from exc
            finally:
                if timer:
                    timer.cancel()

    def _died(self) -> str:
        try:
            self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        try:
            self._log.flush()
            tail = (paths.logs_dir() / "voz-instantanea.log").read_text("utf-8", "replace").strip().splitlines()[-3:]
        except OSError:
            tail = []
        return "El motor de voz instantánea se ha cerrado" + (": " + " | ".join(tail) if tail else ".")

    @staticmethod
    def _json(kind: bytes, data: bytes) -> dict:
        if kind != b"J":
            raise WorkerError(f"Respuesta inesperada del motor ({kind!r}).")
        msg = json.loads(data.decode("utf-8"))
        if not msg.get("ok"):
            raise WorkerError(msg.get("error") or "Error desconocido en el motor de voz instantánea.")
        return msg

    # -- peticiones
    def set_embedding(self, emb: np.ndarray) -> None:
        self._json(*self._call(b"E", np.asarray(emb, np.float32).tobytes(), 30.0))

    def compute_embedding(self, audio16: np.ndarray) -> np.ndarray:
        kind, data = self._call(b"R", np.asarray(audio16, np.float32).tobytes(), 600.0)
        if kind != b"E":
            self._json(kind, data)
            raise WorkerError("Respuesta inesperada al calcular la huella de voz.")
        return np.frombuffer(data, np.float32).copy()

    def process(self, chunk16: np.ndarray) -> np.ndarray:
        kind, data = self._call(b"A", np.asarray(chunk16, np.float32).tobytes(), None)
        if kind != b"A":
            self._json(kind, data)
            raise WorkerError("Respuesta inesperada del motor de voz instantánea.")
        return np.frombuffer(data, np.float32)

    def reset(self) -> None:
        self._json(*self._call(b"Z", b"", 30.0))

    @property
    def alive(self) -> bool:
        return self.proc.poll() is None

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        if self.proc.poll() is None:
            try:
                with self._lock:
                    proto.send(self.proc.stdin, b"Q")
                self.proc.wait(timeout=3)
            except Exception:  # noqa: BLE001
                self._kill()
        for f in (self.proc.stdin, self.proc.stdout):
            try:
                f.close()
            except Exception:  # noqa: BLE001
                pass
        self._log.close()


# --------------------------------------------------- procesador del motor
_FADE = 64                                                  # muestras de fundido en los huecos


class RealtimeMeanVC:
    """Procesador para el motor de audio (misma interfaz que ``RealtimeRVC``).

    El hilo de audio solo copia muestras. Un hilo aparte remuestrea a 16 kHz, envía
    al proceso bloques del tamaño natural del modelo (80 ms en «40ms», 160 ms en
    «120ms») y deja el resultado en una cola de salida.

    La cola es un búfer adaptativo: arranca con un margen pequeño (más el vaivén
    propio del modelo), crece si la CPU se retrasa y, cuando sobra, se encoge sola
    en los silencios entre palabras, para que el retraso no se quede alto.
    """

    kind = "instant"
    MARGIN_S = 0.03                                         # margen inicial sobre el vaivén del modelo
    MARGIN_MIN_S = 0.015
    MARGIN_MAX_S = 0.25
    WINDOW_S = 3.0                                          # cada cuánto se revisa el margen
    STATS_S = 30.0                                          # cada cuánto se apunta en el registro

    def __init__(self, worker: MeanVCWorker, sr: int = 48000, variant: str = "120ms",
                 margin_s: float | None = None, owns_worker: bool = True):
        hello = getattr(worker, "hello", None) or {}
        self.w, self.sr, self.variant = worker, int(sr), variant
        self.owns_worker = owns_worker
        self.out_sr = int(hello.get("out_sr", SR16))
        self.chunk16 = int(hello.get("chunk", CHUNK16))
        self.align16 = int(hello.get("align", 0))
        self.hold_ms = float(hello.get("hold_ms", 0.0))
        # Vaivén de la salida (p. ej. 120/120/240 ms): ya va incluido en «hold_ms», que es el máximo
        # retenido; el margen solo cubre lo que varía el tiempo de cálculo.
        self.burst = int(float(hello.get("burst_ms", 0.0)) / 1000 * self.sr)
        self.block = int(round(self.chunk16 * self.sr / SR16))
        self._mmin = int(self.MARGIN_MIN_S * self.sr)
        self._mmax = int(self.MARGIN_MAX_S * self.sr)
        self.margin = max(self._mmin, int((self.MARGIN_S if margin_s is None else margin_s) * self.sr))
        self.inq = RingBuffer(self.sr * 10)
        self.outq = RingBuffer(self.sr * 10)
        self.infer_ms = 0.0
        self.underruns = 0
        self.dropped = 0                                    # entrada descartada por ir la CPU por detrás
        self.trimmed = 0                                    # salida sobrante quitada en silencios
        self.error: str | None = None
        self._skipped = 0                                   # alineación inicial (no es pérdida)
        self._lost = 0                                      # lo que el proceso tira al cambiar de voz
        self._in_total = 0
        self._out_real = 0
        self._priming = True
        self._lead = 0
        self._fade_in = False
        self._loud = 0.0
        self._trim = 0
        self._pad = 0
        self._was_quiet = True
        self._win_n = 0
        self._win_min: int | None = None
        self._win_under = 0
        self._calm = 0
        self._lat: float | None = None
        self._peak_ms = 0.0
        self._skip16 = self.align16
        self._realign = False
        self._tmp = np.zeros(self.sr, np.float32)
        self._ramp = np.linspace(0.0, 1.0, _FADE, dtype=np.float32)
        # Se crean aquí (en la tarea de carga) y no en el hilo, para no retrasar el primer audio.
        self._rs_in, self._rs_out = StreamResampler(self.sr, SR16), StreamResampler(self.out_sr, self.sr)
        self._ev = threading.Event()
        self._stop = False
        self._t = threading.Thread(target=self._run, name="voz-instantanea", daemon=True)
        self._t.start()

    # -- información
    def _estimate(self) -> float:
        """Retraso necesario: bloque + lo que retiene el modelo (como mucho) + cálculo + margen."""
        return (self.block + self.hold_ms / 1000 * self.sr + 1.15 * self.infer_ms / 1000 * self.sr
                + self.margin)

    @property
    def latency_samples(self) -> int:
        """Retraso real: lo que ha entrado y aún no ha salido (medido, no estimado)."""
        return int(self._lat if self._lat is not None else self._estimate())

    def set_embedding(self, emb: np.ndarray) -> None:
        """Cambia de voz sin reiniciar el proceso (perfiles instantáneos)."""
        self.w.set_embedding(emb)                           # el proceso reinicia su estado
        self._realign = True
        self._ev.set()

    def close(self) -> None:
        self._stop = True
        self._ev.set()
        if self.owns_worker:
            threading.Thread(target=self.w.close, daemon=True).start()

    # -- hilo de audio
    def process(self, x: np.ndarray) -> np.ndarray:
        n = x.shape[0]
        self.inq.write(x)
        self._in_total += n
        self._ev.set()                                      # el bloque se envía en cuanto está completo
        if self._tmp.shape[0] < 4 * n:
            self._tmp = np.zeros(8 * n, np.float32)
        out = np.zeros(n, np.float32)
        avail = self.outq.available()
        if self._priming:
            if avail == 0:
                return out
            self._priming = False
            # Arranca justo en el retraso necesario (bloque + lo retenido + cálculo + margen): lo que
            # falte hasta ahí se pone en silencio delante; con eso no hay cortes y no sobra retraso.
            now = self._in_total - self.dropped - self._skipped
            self._lead = max(0, int(self._estimate()) - now)
        pos = 0
        if self._lead:
            pos = min(self._lead, n)
            self._lead -= pos
        want = n - pos
        if avail > self.margin + 2 * self.block + n:        # tope: un atasco largo no deja el retraso alto
            self.trimmed += self.outq.skip(avail - (self.margin + self.block + n))
        elif self._trim and want:
            self._trim_quiet(want)
        elif self._pad and want and self._quiet_ahead(want):
            k = min(self._pad, want)                        # falta margen: se alarga un silencio
            self._pad -= k
            pos += k
            want -= k
        got = self.outq.read_into(self._tmp, want) if want else 0
        if got:
            seg = self._tmp[:got]
            if self._fade_in:
                k = min(got, _FADE)
                seg[:k] *= self._ramp[:k]
                self._fade_in = False
            out[pos:pos + got] = seg
            self._out_real += got
            peak = float(np.max(np.abs(seg)))
            self._loud = max(peak, self._loud * 0.999)
            self._was_quiet = peak < max(0.003, 0.05 * self._loud)
        if got < want:                                      # la CPU no llegó: hueco con fundidos
            if got:
                k = min(got, _FADE)
                out[pos + got - k:pos + got] *= self._ramp[:k][::-1]
            if not self._fade_in:                           # un hueco cuenta una vez, dure lo que dure
                self.underruns += 1
                self._win_under += 1
            self._fade_in = True
        self._lat = float(self._in_total - self.dropped - self._skipped - self.trimmed - self._lost
                          - self._out_real)
        level = self.outq.available()
        self._win_min = level if self._win_min is None else min(self._win_min, level)
        self._win_n += n
        if self._win_n >= self.WINDOW_S * self.sr:
            self._adapt()
        return out

    def _quiet_ahead(self, n: int) -> bool:
        """¿Lo próximo que va a sonar (y lo último que sonó) es silencio?"""
        if not self._was_quiet:
            return False
        got = self.outq.peek_into(self._tmp, n)
        return got == n and float(np.max(np.abs(self._tmp[:got]))) < max(0.003, 0.05 * self._loud)

    def _trim_quiet(self, want: int) -> None:
        """Quita el sobrante del búfer solo donde hay silencio (no se nota)."""
        k = min(self._trim, want, self.outq.available() - want)
        if k > 0 and self._quiet_ahead(k + want):
            self.trimmed += self.outq.skip(k)
            self._trim -= k

    def _adapt(self) -> None:
        log.debug("búfer: mínimo %s margen %s huecos %s recorte %s relleno %s retraso %s", self._win_min,
                  self.margin, self._win_under, self._trim, self._pad, self.latency_samples)
        if self._win_under:                                 # hubo huecos: más margen
            self.margin = min(self._mmax, self.margin + int(0.02 * self.sr))
            self._calm = 0
            self._trim = self._pad = 0
        else:
            self._calm += 1
            if self._calm * self.WINDOW_S >= 30:            # 30 s sin huecos: probar con algo menos
                self.margin = max(self._mmin, self.margin - int(0.005 * self.sr))
                self._calm = 0
            level = self._win_min or 0
            self._trim = level - self.margin if level - self.margin > int(0.01 * self.sr) else 0
            self._pad = self.margin - level if self.margin - level > int(0.005 * self.sr) else 0
        self._win_n, self._win_min, self._win_under = 0, None, 0

    # -- hilo de conversión
    def _run(self) -> None:
        rs_in, rs_out = self._rs_in, self._rs_out
        pend = np.zeros(0, np.float32)
        buf = np.zeros(self.sr * 2, np.float32)
        last_log, under0, drop0 = time.monotonic(), 0, 0
        while not self._stop:
            self._ev.wait(0.2)
            self._ev.clear()
            while not self._stop:
                if self._realign:                           # voz nueva: el proceso empezó de cero
                    self._realign = False
                    pend = np.zeros(0, np.float32)
                    self._skip16 = self.align16
                    # Lo que estaba dentro del proceso no saldrá: no cuenta como retraso.
                    inside = (self._in_total - self.dropped - self._skipped - self.trimmed - self._lost
                              - self._out_real - self.outq.available() - self.inq.available())
                    self._lost += max(0, int(inside))
                n = self.inq.available()
                if n == 0:
                    break
                if n > 3 * self.block:                      # la CPU va por detrás: se descarta lo viejo
                    self.dropped += self.inq.skip(n - self.block)
                    n = self.inq.available()
                k = self.inq.read_into(buf, min(n, buf.shape[0]))
                x16 = rs_in.process(buf[:k])
                if self._skip16:                            # alineación con la ventana del reconocedor
                    d = min(self._skip16, x16.shape[0])
                    x16 = x16[d:]
                    self._skip16 -= d
                    self._skipped += int(round(d * self.sr / SR16))
                pend = np.concatenate([pend, x16])
                while pend.shape[0] >= self.chunk16 and not self._stop and not self._realign:
                    chunk, pend = pend[:self.chunk16], pend[self.chunk16:]
                    t0 = time.perf_counter()
                    try:
                        y = self.w.process(chunk)
                    except Exception as exc:  # noqa: BLE001
                        if not self._stop:
                            self.error = str(exc)
                            log.error("Voz instantánea detenida: %s", exc)
                        self._stop = True
                        return
                    ms = (time.perf_counter() - t0) * 1000
                    self.infer_ms = ms if self.infer_ms == 0 else 0.85 * self.infer_ms + 0.15 * ms
                    self._peak_ms = max(self._peak_ms, ms)
                    if y.shape[0]:
                        self.outq.write(rs_out.process(y))
            if time.monotonic() - last_log >= self.STATS_S and not self._stop:
                last_log = time.monotonic()
                log.info("Voz instantánea (%s): retraso %d ms (modelo %d, margen %d), cálculo %.0f ms "
                         "por bloque de %d ms (pico %.0f), huecos %d, entrada descartada %d ms, recortado %d ms",
                         self.variant, self.latency_samples * 1000 // self.sr, self.hold_ms, self.margin * 1000 // self.sr,
                         self.infer_ms, self.chunk16 * 1000 // SR16, self._peak_ms, self.underruns - under0,
                         (self.dropped - drop0) * 1000 // self.sr, self.trimmed * 1000 // self.sr)
                under0, drop0, self._peak_ms = self.underruns, self.dropped, 0.0
