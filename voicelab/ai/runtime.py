"""Motor de inferencia: ONNX Runtime con DirectML (GPU AMD/Intel/NVIDIA) o CPU."""

from __future__ import annotations

import importlib
import importlib.util
import logging
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def packages() -> list[str]:
    ort = "onnxruntime-directml" if sys.platform == "win32" else "onnxruntime"
    return [ort, "tokenizers"]


def available() -> bool:
    return importlib.util.find_spec("onnxruntime") is not None and importlib.util.find_spec("tokenizers") is not None


def providers(prefer_gpu: bool = True) -> list[str]:
    import onnxruntime as ort
    avail = ort.get_available_providers()
    order = ["DmlExecutionProvider", "CUDAExecutionProvider", "ROCMExecutionProvider"] if prefer_gpu else []
    return [p for p in order if p in avail] + ["CPUExecutionProvider"]


def session(path: Path, prefer_gpu: bool = True, threads: int | None = None):
    """Crea una sesión. Ojo: bloquea el intérprete mientras carga; úsese en un proceso aparte."""
    import onnxruntime as ort
    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    if threads:
        so.intra_op_num_threads = threads
    provs = providers(prefer_gpu)
    if "DmlExecutionProvider" in provs:
        so.enable_mem_pattern = False          # requisito de DirectML
        so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    try:
        return ort.InferenceSession(str(path), sess_options=so, providers=provs)
    except Exception as exc:
        if len(provs) > 1:
            log.warning("GPU no disponible para %s (%s); se usa la CPU", path.name, exc)
            return ort.InferenceSession(str(path), sess_options=so, providers=["CPUExecutionProvider"])
        raise


def install(progress) -> dict:
    """Instala ONNX Runtime (DirectML en Windows) y tokenizers en el entorno de la app."""
    root = Path(sys.executable).resolve().parents[2]          # …\VoiceLab AI\runtime\Scripts\python.exe
    uv = root / "bin" / "uv.exe"
    progress(0.1)
    py = Path(sys.executable)
    if py.name.lower() == "pythonw.exe":
        py = py.with_name("python.exe")
    if uv.exists():
        cmd = [str(uv), "pip", "install", "--no-config", "--python", str(py), *packages()]
    else:
        cmd = [str(py), "-m", "pip", "install", "--disable-pip-version-check", *packages()]
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=_NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError("No se pudo instalar el motor de IA:\n" + (r.stderr or r.stdout)[-800:])
    importlib.invalidate_caches()
    progress(1.0)
    return {"installed": available()}
