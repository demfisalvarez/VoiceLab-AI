"""«Entrenar voz fiel»: entrena una voz RVC con el material de un perfil.

Pasos (todo en el equipo, sin servicios externos):

1. Comprueba lo necesario: el entorno de PyTorch (el mismo de la voz instantánea),
   la base de conversión RVC (ContentVec + RMVPE, ONNX) y los modelos preentrenados
   de RVC v2 a 40 kHz (``f0G40k``/``f0D40k``, MIT, 0,2 GB).
2. Prepara los datos en un proceso aparte: trocea la voz en fragmentos de ~3,7 s,
   y saca de cada uno el contenido (ContentVec) y el tono (RMVPE), con la GPU si hay.
3. Entrena en otro proceso (``rvc_trainer.py``, PyTorch en la CPU, prioridad baja)
   durante el tiempo elegido, guardando puntos de control: se puede parar y seguir.
4. Exporta a ONNX (con decodificación parcial para el directo) y la app crea un
   perfil RVC con la voz entrenada.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

import numpy as np

from .. import paths
from . import meanvc, models

log = logging.getLogger(__name__)

PRETRAIN_KEY = "rvc-train"
SR_IN = 48000
MIN_SPEECH_S = 60                      # menos de 1 min no da para una voz fiel
GOOD_SPEECH_S = 600                    # a partir de ~10 min, muy fiel
MAX_DATA_MIN = 30                      # más no mejora y tarda más en preparar
DURATIONS = {30: "30 min (prueba rápida)", 60: "1 hora", 120: "2 horas (recomendado)", 240: "4 horas (máxima)"}
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
_BELOW_NORMAL = 0x00004000 if sys.platform == "win32" else 0


class TrainError(RuntimeError):
    pass


# ------------------------------------------------------------------- rutas
def vendor_dir() -> Path:
    return Path(__file__).with_name("vendor")


def trainer_script() -> Path:
    return Path(__file__).with_name("rvc_trainer.py")


def work_dir(profile_id: str) -> Path:
    return paths.data_dir() / "training" / profile_id


def material(profile_dir: Path) -> Path | None:
    f = profile_dir / "material.wav"
    return f if f.exists() else None


def pretrained() -> tuple[Path, Path]:
    d = models.model_dir(PRETRAIN_KEY)
    return d / "pretrained_v2" / "f0G40k.pth", d / "pretrained_v2" / "f0D40k.pth"


def default_threads() -> int:
    """Núcleos físicos menos uno: el PC sigue respondiendo mientras entrena."""
    return max(1, (os.cpu_count() or 2) // 2 - 1)


# ---------------------------------------------------- preparación de datos
def slice_pieces(x: np.ndarray, sr: int, per: float = 3.7, overlap: float = 0.3,
                 min_silence: float = 0.4, min_len: float = 0.6) -> list[np.ndarray]:
    """Trocea por los silencios y luego en fragmentos de ``per`` s con solape (como RVC)."""
    hop = sr // 100
    n = x.shape[0] // hop
    if n == 0:
        return []
    rms = np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    loud = np.percentile(db, 95)
    voiced = db > max(-50.0, loud - 35.0)
    # Segmentos con voz separados por silencios de al menos «min_silence».
    segs, start, quiet = [], None, 0
    for i, v in enumerate(voiced):
        if v:
            if start is None:
                start = i
            quiet = 0
        elif start is not None:
            quiet += 1
            if quiet * 0.01 >= min_silence:
                segs.append((start, i - quiet + 1))
                start, quiet = None, 0
    if start is not None:
        segs.append((start, n))
    pieces = []
    keep = int(0.15 * sr)                                   # algo de silencio en los bordes
    step, length = int((per - overlap) * sr), int(per * sr)
    for a, b in segs:
        seg = x[max(0, a * hop - keep): min(x.shape[0], b * hop + keep)]
        i = 0
        while i < seg.shape[0]:
            piece = seg[i:i + length]
            if seg.shape[0] - i <= int((per + overlap) * sr):   # el resto entero, sin dejar colas cortas
                piece = seg[i:]
                if piece.shape[0] >= min_len * sr:
                    pieces.append(piece)
                break
            pieces.append(piece)
            i += step
    return pieces


def normalize(p: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(p)))
    if not np.isfinite(peak) or peak <= 1e-4:
        return p
    return (p / peak * (0.9 * 0.75) + 0.25 * p).astype(np.float32)        # igual que RVC


class Preparer:
    """Se crea en un proceso aparte (``procs.Remote``): ContentVec y RMVPE en ONNX."""

    def __init__(self, prefer_gpu: bool = True, stage=None, cancel=None):
        from . import runtime
        from .rvc import RMVPE
        base = models.model_dir("rvc-base")
        if stage:
            stage("Cargando el extractor de contenido…")
        self.vec = runtime.session(base / "vec-768-layer-12.onnx", prefer_gpu=prefer_gpu)
        if stage:
            stage("Cargando el detector de tono…")
        self.rmvpe = RMVPE(runtime.session(base / "rmvpe.onnx", prefer_gpu=prefer_gpu))
        self.cancel = cancel
        provs = self.vec.get_providers() if hasattr(self.vec, "get_providers") else []
        self.info = {"device": "gpu" if provs and provs[0] != "CPUExecutionProvider" else "cpu"}

    def features(self, x16: np.ndarray) -> np.ndarray:
        out = self.vec.run(None, {self.vec.get_inputs()[0].name: x16[None, None, :].astype(np.float32)})[0]
        if out.shape[-1] != 768 and out.shape[1] == 768:
            out = out.transpose(0, 2, 1)
        return out[0]

    def run(self, source: str, out: str, max_minutes: float = MAX_DATA_MIN, progress=None) -> dict:
        from ..audio import mediaio
        from scipy.signal import butter, sosfilt
        x = mediaio.load_audio(source, SR_IN)
        x = sosfilt(butter(5, 48, "highpass", fs=SR_IN, output="sos"), x).astype(np.float32)
        pieces = slice_pieces(x, SR_IN)
        total = sum(p.shape[0] for p in pieces) / SR_IN
        if total > max_minutes * 60:                        # repartido por todo el audio
            k = max_minutes * 60 / total
            pieces = [p for i, p in enumerate(pieces) if int((i + 1) * k) > int(i * k)]
        wav, feat, f0 = [], [], []
        for i, p in enumerate(pieces):
            if self.cancel is not None and self.cancel.is_set():
                raise TrainError("Cancelado.")
            p = normalize(p)
            w40 = mediaio.resample(p, SR_IN, 40000)
            x16 = mediaio.resample(p, SR_IN, 16000)
            wav.append(np.clip(w40 * 32767, -32768, 32767).astype(np.int16))
            feat.append(self.features(x16).astype(np.float16))
            f0.append(self.rmvpe.f0(x16).astype(np.float32))
            if progress:
                progress((i + 1) / len(pieces))

        def off(parts):
            return np.concatenate([[0], np.cumsum([q.shape[0] for q in parts])]).astype(np.int64)
        tmp = Path(out).with_suffix(".tmp.npz")
        np.savez(tmp, wav=np.concatenate(wav), wav_off=off(wav), feat=np.concatenate(feat), feat_off=off(feat),
                 f0=np.concatenate(f0), f0_off=off(f0))
        os.replace(tmp, out)
        voiced = np.concatenate(f0)
        med = float(np.median(voiced[voiced > 0])) if (voiced > 0).any() else 0.0
        return {"pieces": len(pieces), "minutes": round(sum(w.shape[0] for w in wav) / 40000 / 60, 1),
                "f0_median": round(med, 1)}


# ------------------------------------------------------------- entrenador
def trainer_command(data: Path, out: Path, minutes: float, steps: int = 0, threads: int | None = None,
                    extend: bool = False) -> list[str]:
    g, d = pretrained()
    cmd = [str(meanvc.runtime_python()), "-I", str(trainer_script()), "--code", str(vendor_dir()),
           "--data", str(data), "--out", str(out), "--pretrain-g", str(g), "--pretrain-d", str(d),
           "--minutes", str(minutes), "--threads", str(threads or default_threads())]
    if steps:
        cmd += ["--steps", str(int(steps))]
    if extend:
        cmd += ["--extend"]
    return cmd


class TrainerProcess:
    """El proceso de entrenamiento: lee su progreso (líneas JSON) en un hilo."""

    def __init__(self, cmd: list[str], out: Path, on_event: Callable[[dict], None]):
        self.out = out
        self._log = open(paths.logs_dir() / "entrenamiento.log", "ab")  # noqa: SIM115
        self._log.write(f"\n==== {time.strftime('%Y-%m-%d %H:%M:%S')} ====\n".encode())
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=self._log,
                                     creationflags=_NO_WINDOW | _BELOW_NORMAL)
        self.on_event = on_event
        self._t = threading.Thread(target=self._read, name="entrenamiento", daemon=True)
        self._t.start()

    def _read(self) -> None:
        for raw in self.proc.stdout:                       # type: ignore[union-attr]
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("{"):
                continue
            try:
                self.on_event(json.loads(line))
            except ValueError:
                continue

    def stop(self) -> None:
        """Pide que pare: guarda, exporta lo aprendido y termina."""
        try:
            (self.out / "STOP").write_text("1", encoding="utf-8")
        except OSError:
            pass

    def wait(self, timeout: float | None = None) -> int | None:
        try:
            rc = self.proc.wait(timeout)
        except subprocess.TimeoutExpired:
            return None
        self._t.join(5)
        self._log.close()
        return rc

    def kill(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()


class TrainingManager:
    """Un entrenamiento a la vez. Estado consultable por la interfaz (``status``)."""

    def __init__(self):
        self._lock = threading.Lock()
        self.state: dict = {"state": "idle"}
        self._proc: TrainerProcess | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def status(self) -> dict:
        with self._lock:
            return dict(self.state)

    def _set(self, **kw) -> None:
        with self._lock:
            self.state.update(kw)

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, profile: dict, profile_dir: Path, minutes: float, on_done: Callable[[dict], None],
              prefer_gpu: bool = True, extend: bool = False, threads: int | None = None) -> None:
        if self.busy:
            raise TrainError("Ya hay un entrenamiento en marcha.")
        src = material(profile_dir)
        if src is None:
            raise TrainError("Este perfil no guarda audio para entrenar. Crea el perfil con 1 minuto de voz o más.")
        speech = float((profile.get("cloning") or {}).get("analysis", {}).get("speech_s", 0) or 0)
        if speech and speech < MIN_SPEECH_S:
            raise TrainError(f"Hay {speech:.0f} s de voz: hace falta al menos 1 minuto (mejor 10 min o más).")
        self._stop.clear()
        self.state = {"state": "starting", "profile_id": profile["id"], "name": profile["name"],
                      "minutes": minutes, "phase": "Preparando…", "progress": 0.0, "started": time.time()}
        self._thread = threading.Thread(
            target=self._run, args=(profile, profile_dir, src, minutes, on_done, prefer_gpu, extend, threads),
            name="entrenar-voz", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Parar ahora conservando lo aprendido (se exporta y se crea el perfil)."""
        self._stop.set()
        if self._proc is not None:
            self._proc.stop()
        self._set(phase="Guardando lo aprendido…")

    def shutdown(self) -> None:
        """Al cerrar la app: el entrenador guarda y termina solo; se podrá continuar."""
        self._stop.set()
        if self._proc is not None:
            self._proc.stop()

    # -- hilo
    def _run(self, profile, profile_dir, src, minutes, on_done, prefer_gpu, extend, threads) -> None:
        wd = work_dir(profile["id"])
        wd.mkdir(parents=True, exist_ok=True)
        try:
            self._prepare_env(wd)
            if self._stop.is_set():
                raise TrainError("Cancelado.")
            data = wd / "dataset.npz"
            sig = f"{src.stat().st_size}:{int(src.stat().st_mtime)}"
            meta_f = wd / "dataset.json"
            meta = json.loads(meta_f.read_text(encoding="utf-8")) if meta_f.exists() else {}
            if not data.exists() or meta.get("source") != sig:
                for old in ("checkpoint.pt", "model.onnx"):      # material nuevo: se empieza de cero
                    (wd / old).unlink(missing_ok=True)
                meta = self._prepare_data(src, data, prefer_gpu)
                meta["source"] = sig
                meta_f.write_text(json.dumps(meta), encoding="utf-8")
            if self._stop.is_set():
                raise TrainError("Cancelado.")
            res = self._train(wd, data, minutes, extend, threads)
            res.update({"dataset": meta, "work_dir": str(wd)})
            self._set(state="finishing", phase="Creando el perfil con la voz entrenada…", progress=0.99)
            prof = on_done(res)
            self._set(state="done", phase="Voz fiel lista.", progress=1.0, result_profile=prof.get("id") if prof else None,
                      steps=res.get("step"), finished=time.time())
        except Exception as exc:  # noqa: BLE001
            stopped = self._stop.is_set()
            log.warning("Entrenamiento: %s", exc, exc_info=not isinstance(exc, TrainError))
            self._set(state="stopped" if stopped else "error", phase="Detenido." if stopped else str(exc),
                      error=None if stopped else str(exc))
        finally:
            self._proc = None

    def _prepare_env(self, wd: Path) -> None:
        if not meanvc.runtime_ready():
            self._set(phase="Instalando PyTorch para la CPU (una vez, ~250 MB)…", progress=0.01)
            meanvc.install_runtime(lambda p: self._set(progress=0.01 + 0.03 * p))
        self._set(phase="Comprobando el entorno de PyTorch…")
        meanvc.ensure_extras(meanvc.TRAIN_EXTRAS)
        for key, label in (("rvc-base", "la base de conversión RVC"), (PRETRAIN_KEY, "los modelos preentrenados")):
            if not models.installed(key):
                self._set(phase=f"Descargando {label}…")
                models.install(key, lambda p: self._set(progress=0.04 + 0.02 * p))

    def _prepare_data(self, src: Path, data: Path, prefer_gpu: bool) -> dict:
        from .procs import Remote
        self._set(state="preparing", phase="Preparando la voz (contenido y tono)…", progress=0.06)
        r = Remote("voicelab.ai.rvc_train:Preparer", (prefer_gpu,), name="preparar el entrenamiento",
                   log_name="entrenamiento-datos", load_timeout=600,
                   on_stage=lambda t: self._set(phase=t), low_priority=True)
        try:
            return r.call("run", str(src), str(data), MAX_DATA_MIN,
                          progress=lambda p: self._set(progress=0.06 + 0.06 * p,
                                                       phase=f"Preparando la voz… {int(p * 100)} %"),
                          timeout=900)
        finally:
            r.close()

    def _train(self, wd: Path, data: Path, minutes: float, extend: bool, threads: int | None) -> dict:
        self._set(state="training", phase="Empezando a entrenar…", progress=0.12)
        last: dict = {}

        def on_event(ev: dict) -> None:
            kind = ev.get("type")
            if kind == "progress":
                total = max(1, int(ev.get("total") or 1))
                frac = min(1.0, ev["step"] / total)
                self._set(progress=0.12 + 0.86 * frac, step=ev["step"], total=total, eta_s=ev.get("eta_s"),
                          loss_mel=ev.get("loss_mel"),
                          phase=f"Entrenando… paso {ev['step']} de {total}")
            elif kind == "ready":
                self._set(pieces=ev.get("pieces"), data_minutes=ev.get("minutes"))
            elif kind == "exported":
                last.update(ev)
            elif kind == "error":
                last["error"] = ev.get("message")

        self._proc = TrainerProcess(trainer_command(data, wd, minutes, extend=extend, threads=threads), wd, on_event)
        if self._stop.is_set():
            self._proc.stop()
        rc = self._proc.wait()
        if rc != 0 or "path" not in last:
            raise TrainError("El entrenamiento falló: " + (last.get("error") or f"código {rc}") +
                             ". Detalles en logs\\entrenamiento.log")
        return last


_manager: TrainingManager | None = None


def manager() -> TrainingManager:
    global _manager
    if _manager is None:
        _manager = TrainingManager()
    return _manager
