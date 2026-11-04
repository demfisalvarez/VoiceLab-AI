"""Autocomprobación del ejecutable (la usa la compilación en Windows).

``VoiceLab AI.exe --selftest resultado.json`` arranca los servicios sin
ventana y comprueba lo que suele romperse al empaquetar: recursos de la
interfaz, dispositivos de audio, ONNX Runtime, FFmpeg, los procesos aparte
de IA (multiprocessing en el .exe) y los archivos de la voz en directo.
Con ``--selftest-window`` además abre la ventana real y espera a que la
interfaz avise de que está lista.
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path


def _check(results: dict, name: str, fn) -> None:
    t0 = time.perf_counter()
    try:
        value = fn()
        results[name] = {"ok": True, "value": value, "s": round(time.perf_counter() - t0, 2)}
    except Exception as exc:  # noqa: BLE001
        results[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc()[-1500:], "s": round(time.perf_counter() - t0, 2)}


def echo_factory(stage=None, cancel=None):
    """Objeto mínimo para comprobar los procesos aparte."""
    class Echo:
        info = {"pid_ok": True}

        @staticmethod
        def double(x):
            return x * 2
    if stage:
        stage("eco listo")
    return Echo()


def run(out: Path, services=None) -> int:
    from . import __version__, paths
    from .ai import meanvc, models, runtime
    results: dict = {"version": __version__, "frozen": bool(getattr(sys, "frozen", False)),
                     "python": sys.version.split()[0], "executable": sys.executable}

    _check(results, "ui", lambda: (paths.UI_DIR / "index.html").stat().st_size)
    _check(results, "icon", lambda: str(paths.icon_file()))

    def devices():
        from .audio.devices import DeviceManager
        dm = services[1] if services else DeviceManager()
        return {"portaudio": dm.sd.get_portaudio_version()[1], "devices": len(dm.sd.query_devices())}
    _check(results, "audio", devices)

    def ort():
        import onnxruntime
        return {"version": onnxruntime.__version__, "providers": runtime.providers()}
    _check(results, "onnxruntime", ort)
    _check(results, "tokenizers", lambda: __import__("tokenizers").__version__)

    def ffmpeg():
        from .audio import mediaio
        return str(mediaio.find_ffmpeg())
    _check(results, "ffmpeg", ffmpeg)

    def remote():
        from .ai.procs import Remote
        r = Remote("voicelab.selftest:echo_factory", name="proceso de prueba", log_name="autocomprobacion",
                   load_timeout=120)
        try:
            return {"double": r.call("double", 21, timeout=30), "pid": r.pid}
        finally:
            r.close()
    _check(results, "procesos_ia", remote)

    _check(results, "voz_en_directo", lambda: {
        "worker": meanvc.worker_script().exists(), "codigo": (meanvc.code_dir() / "runtime" / "run_rt.py").exists(),
        "uv": str(meanvc._uv()), "pybase": str(meanvc._bundled_python()), "supported": meanvc.supported(),
        "runtime_dir": str(meanvc.runtime_dir())})
    _check(results, "modelos", lambda: {k: models.installed(k) for k in models.CATALOG})

    results["ok"] = all(v.get("ok") for v in results.values() if isinstance(v, dict) and "ok" in v)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if results["ok"] else 1


def run_live_runtime(out: Path) -> int:
    """Instala el entorno de PyTorch como lo haría el usuario y arranca el proceso de la voz en directo.

    Sin pesos del modelo: basta con que el proceso arranque, importe PyTorch y avise de que faltan
    archivos (así se comprueba la ruta completa del .exe sin descargar 1,6 GB).
    """
    from .ai import meanvc
    results: dict = {}
    _check(results, "instalar_entorno", lambda: (meanvc.install_runtime(lambda p: None),
                                                 str(meanvc.runtime_python()))[1])

    def worker():
        import tempfile
        cmd = meanvc.worker_command("120ms")
        cmd[cmd.index("--weights") + 1] = tempfile.mkdtemp()
        try:
            meanvc.MeanVCWorker(cmd, start_timeout=300).close()
        except meanvc.WorkerError as exc:
            if "Faltan archivos del modelo" in str(exc):
                return "arranca e importa PyTorch: " + str(exc)[:120]
            raise
        raise RuntimeError("arrancó sin pesos (inesperado)")
    _check(results, "proceso_voz_en_directo", worker)
    results["ok"] = all(v.get("ok") for v in results.values() if isinstance(v, dict))
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if results["ok"] else 1
