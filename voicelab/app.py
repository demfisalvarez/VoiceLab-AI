"""Punto de entrada de VoiceLab AI.

Modos:
* Ventana nativa (por defecto): pywebview + WebView2 de Edge.
* Modo navegador (``--browser`` o automático si WebView2 falla): servidor
  local + ventana de Edge en modo aplicación.
"""

from __future__ import annotations

import argparse
import gc
import logging
import os
import subprocess
import sys
import threading
import traceback
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import APP_NAME, __version__, paths

log = logging.getLogger("voicelab")


# ------------------------------------------------------------------ registro
def setup_logging(debug: bool = False) -> Path:
    log_file = paths.logs_dir() / "voicelab.log"
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    if sys.stderr is not None and sys.stderr.isatty():
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)
    return log_file


def message_box(text: str, title: str = APP_NAME, error: bool = False) -> None:
    """Muestra un mensaje aunque no haya consola (pythonw)."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text, title, 0x10 if error else 0x40)  # type: ignore[attr-defined]
            return
        except Exception:
            pass
    print(f"{title}: {text}", file=sys.stderr)


# ---------------------------------------------------------- instancia única
class SingleInstance:
    def __init__(self):
        self._handle = None
        self._file = None

    def acquire(self) -> bool:
        if sys.platform == "win32":
            import ctypes
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            self._handle = kernel32.CreateMutexW(None, False, "Local\\VoiceLabAI_SingleInstance")
            return kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS
        import fcntl
        self._file = open(paths.data_dir() / ".lock", "w")  # noqa: SIM115
        try:
            fcntl.flock(self._file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    @staticmethod
    def focus_existing() -> None:
        if sys.platform != "win32":
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
            hwnd = user32.FindWindowW(None, APP_NAME)
            if hwnd:
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                user32.SetForegroundWindow(hwnd)
        except Exception:
            pass


# ------------------------------------------------------------------ montaje
def build_services():
    from .api import Api
    from .audio.devices import DeviceManager
    from .audio.engine import AudioEngine
    from .config import Settings

    settings = Settings()
    devices = DeviceManager()
    engine = AudioEngine(devices)
    api = Api(settings, devices, engine)
    return settings, devices, engine, api


def _find_edge() -> str | None:
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft/Edge/Application/msedge.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def run_browser(api, port: int = 0, open_window: bool = True) -> None:
    from .devserver import DevServer

    server = DevServer(api, port=port)
    server.start()
    api._on_quit = server.stop  # noqa: SLF001
    proc = None
    if open_window:
        edge = _find_edge() if sys.platform == "win32" else None
        if edge:
            profile = paths.data_dir() / "edge-app"
            proc = subprocess.Popen([edge, f"--app={server.url}", "--window-size=1320,860",
                                     f"--user-data-dir={profile}", "--no-first-run"])
        else:
            webbrowser.open(server.url)
    print(f"{APP_NAME} en modo navegador: {server.url}", flush=True)
    if proc is not None:
        # La ventana de Edge vive en su propio perfil: cuando el proceso
        # termina, la ventana se ha cerrado.
        watcher = threading.Thread(target=lambda: (proc.wait(), server.stop()), daemon=True)
        watcher.start()
    try:
        server.wait_until_closed()
    except KeyboardInterrupt:
        pass
    finally:
        if not server.stopped.is_set():
            server.stop()


def run_webview(api, engine, debug: bool = False, selftest: str | None = None) -> None:
    import webview  # pywebview

    window = webview.create_window(
        APP_NAME,
        url=str(paths.UI_DIR / "index.html"),
        js_api=api,
        width=1320,
        height=860,
        min_size=(1100, 720),
        background_color="#0B0D12",
        text_select=False,
    )
    window.events.closing += engine.stop
    t0 = __import__("time").perf_counter()
    window.events.loaded += lambda: log.info("Ventana cargada en %.1f s", __import__("time").perf_counter() - t0)
    api._window = window  # noqa: SLF001 - diálogos de archivo nativos
    api._on_quit = window.destroy  # noqa: SLF001
    if selftest:                        # compilación: ¿llega la interfaz a estar lista?
        def watch():
            import json
            import time
            t0 = time.perf_counter()
            ok = api._ui_ready.wait(180)
            Path(selftest).write_text(json.dumps({"ok": ok, "seconds": round(time.perf_counter() - t0, 1)}),
                                      encoding="utf-8")
            time.sleep(1)
            window.destroy()
        threading.Thread(target=watch, daemon=True).start()
    icon = paths.icon_file()
    options = dict(
        gui="edgechromium" if sys.platform == "win32" else None,
        debug=debug,
        private_mode=False,
        storage_path=str(paths.data_dir() / "webview"),
    )
    try:
        webview.start(icon=str(icon) if icon else None, **options)
    except TypeError:  # versiones de pywebview sin el parámetro «icon»
        webview.start(**options)


_crash_file = None


def _enable_crash_log() -> None:
    """Si algo revienta en código nativo, deja la pila de Python en logs/fallos.log."""
    global _crash_file
    try:
        import faulthandler
        _crash_file = open(paths.logs_dir() / "fallos.log", "a", encoding="utf-8")  # noqa: SIM115
        faulthandler.enable(_crash_file)
    except Exception:  # noqa: BLE001
        pass


def _set_app_user_model_id() -> None:
    """Agrupa la ventana en la barra de tareas con su propio icono."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("VoiceLabAI.Studio")  # type: ignore[attr-defined]
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="voicelab", description=f"{APP_NAME} {__version__}")
    parser.add_argument("--browser", action="store_true", help="usar el modo navegador")
    parser.add_argument("--port", type=int, default=0, help="puerto del modo navegador")
    parser.add_argument("--no-window", action="store_true", help="no abrir ventana (solo servidor)")
    parser.add_argument("--debug", action="store_true", help="registro detallado y herramientas web")
    parser.add_argument("--selftest", metavar="JSON", help="autocomprobación sin ventana (compilación)")
    parser.add_argument("--selftest-window", metavar="JSON", help="abre la ventana, espera a la interfaz y sale")
    parser.add_argument("--selftest-live", metavar="JSON", help="instala el entorno de PyTorch y prueba el proceso")
    args = parser.parse_args(argv)

    log_file = setup_logging(args.debug)
    log.info("Iniciando %s %s (Python %s, %s%s)", APP_NAME, __version__, sys.version.split()[0], sys.platform,
             ", ejecutable" if getattr(sys, "frozen", False) else "")
    _enable_crash_log()

    if args.selftest:
        from . import selftest
        return selftest.run(Path(args.selftest))
    if args.selftest_live:
        from . import selftest
        return selftest.run_live_runtime(Path(args.selftest_live))

    instance = SingleInstance()
    if not instance.acquire():
        SingleInstance.focus_existing()
        message_box(f"{APP_NAME} ya está abierto.")
        return 1

    _set_app_user_model_id()
    try:
        settings, devices, engine, api = build_services()
    except Exception:
        log.exception("Error al iniciar los servicios")
        message_box(f"No se pudo iniciar {APP_NAME}.\n\nDetalles en:\n{log_file}", error=True)
        return 2

    # Los objetos creados al arrancar no los revisará el recolector de basura:
    # menos pausas en el hilo de audio.
    gc.collect()
    gc.freeze()

    try:
        if args.browser or args.no_window:
            run_browser(api, port=args.port, open_window=not args.no_window)
        else:
            try:
                run_webview(api, engine, debug=args.debug, selftest=args.selftest_window)
            except Exception:
                log.error("Ventana nativa no disponible, se usa el modo navegador:\n%s", traceback.format_exc())
                run_browser(api, port=args.port)
    finally:
        engine.stop()
        try:
            engine.set_ai(None)                 # cierra los procesos de IA en directo
            from .ai import tts
            tts.unload()
        except Exception:  # noqa: BLE001
            log.exception("Al cerrar los procesos de IA")
        try:
            settings.save()
        except OSError:
            log.exception("No se pudieron guardar los ajustes")
        log.info("%s cerrado", APP_NAME)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
