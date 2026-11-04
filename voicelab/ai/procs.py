"""Modelos de IA en un proceso aparte.

Crear una sesión de ONNX Runtime con un modelo grande bloquea el intérprete
de Python (no suelta el GIL) durante decenas de segundos, y un fallo del
controlador de la GPU puede tumbar el proceso entero. Por eso los modelos
viven en un proceso hijo: la ventana nunca se congela, un cuelgue se detecta
y se corta, y un fallo se convierte en un mensaje en lugar de cerrar la app.

Uso::

    r = Remote("voicelab.ai.tts:open_engine", ("chatterbox-v2", False), name="texto a voz")
    wav = r.call("synthesize", texto, ..., progress=cb, timeout=120)

El objeto se crea en el hijo con ``fábrica(*args, stage=…, cancel=…)``.
``stage(texto)`` informa de lo que está haciendo (y sirve de latido);
``cancel`` es un evento que la app activa para pedir que pare.
"""

from __future__ import annotations

import importlib
import logging
import multiprocessing as mp
import threading
import time
import traceback
from typing import Any, Callable

log = logging.getLogger(__name__)


class RemoteError(RuntimeError):
    """Error del proceso hijo, ya con un mensaje para el usuario."""

    def __init__(self, message: str, kind: str = "error"):
        super().__init__(message)
        self.kind = kind          # «error», «crash», «timeout» o «cancelled»


# ------------------------------------------------------------- proceso hijo
def _child(conn, factory: str, args: tuple, kwargs: dict, cancel, log_name: str) -> None:
    import faulthandler

    from .. import paths
    log_path = paths.logs_dir() / f"{log_name}.log"
    fh = open(log_path, "a", encoding="utf-8")  # noqa: SIM115 - abierto mientras viva el proceso
    faulthandler.enable(fh)                     # si el código nativo revienta, queda la pila de Python
    logging.basicConfig(stream=fh, level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    clog = logging.getLogger(f"voicelab.{log_name}")

    def send(*msg) -> None:
        try:
            conn.send(msg)
        except (BrokenPipeError, OSError):
            raise SystemExit(0) from None

    def stage(text: str) -> None:
        clog.info("%s", text)
        send("stage", text)

    try:
        mod, _, attr = factory.partition(":")
        t0 = time.perf_counter()
        obj = getattr(importlib.import_module(mod), attr)(*args, stage=stage, cancel=cancel, **kwargs)
        clog.info("Listo en %.1f s", time.perf_counter() - t0)
        send("ready", getattr(obj, "info", None))
    except BaseException as exc:  # noqa: BLE001
        clog.error("No se pudo cargar:\n%s", traceback.format_exc())
        send("error", _friendly(exc), traceback.format_exc()[-3000:])
        return
    while True:
        try:
            method, cargs, ckw, want_progress = conn.recv()
        except (EOFError, OSError):
            return
        if method is None:
            return
        try:
            if want_progress:
                ckw["progress"] = lambda p: send("progress", float(p))
            t0 = time.perf_counter()
            result = getattr(obj, method)(*cargs, **ckw)
            clog.info("%s en %.2f s", method, time.perf_counter() - t0)
            send("result", result)
        except BaseException as exc:  # noqa: BLE001
            if isinstance(exc, SystemExit):
                raise
            cancelled = getattr(exc, "cancelled", False) or (cancel is not None and cancel.is_set())
            clog.error("%s falló:\n%s", method, traceback.format_exc())
            send("cancelled" if cancelled else "error", _friendly(exc), traceback.format_exc()[-3000:])


def _friendly(exc: BaseException) -> str:
    msg = str(exc) or type(exc).__name__
    low = msg.lower()
    if isinstance(exc, MemoryError) or "bad_alloc" in low or "not enough memory" in low:
        return "No hay memoria suficiente para cargar el modelo. Cierra otros programas y vuelve a intentarlo."
    if "dml" in low or "directml" in low or "d3d12" in low:
        return "La GPU (DirectML) ha fallado: " + msg
    return msg


# ------------------------------------------------------------ proceso padre
class Remote:
    """Objeto que vive en un proceso hijo. Las llamadas son de una en una."""

    def __init__(self, factory: str, args: tuple = (), kwargs: dict | None = None, *, name: str = "modelo",
                 log_name: str = "ia", load_timeout: float = 600.0,
                 on_stage: Callable[[str], None] | None = None):
        self.name = name
        self.stage = ""
        ctx = mp.get_context("spawn")
        self._conn, child = ctx.Pipe()
        self._cancel = ctx.Event()
        self._lock = threading.Lock()
        self._closed = False
        self._proc = ctx.Process(target=_child, args=(child, factory, tuple(args), dict(kwargs or {}), self._cancel,
                                                      log_name), name=f"voicelab-{log_name}", daemon=True)
        self._proc.start()
        child.close()
        try:
            self.info = self._wait(("ready",), load_timeout, on_stage, None)
        except BaseException:
            self.close()
            raise

    # -- estado
    @property
    def alive(self) -> bool:
        return not self._closed and self._proc.is_alive()

    @property
    def pid(self) -> int | None:
        return self._proc.pid

    # -- canal
    def _wait(self, final: tuple, timeout: float | None, on_stage, progress) -> Any:
        last = time.monotonic()
        while True:
            if self._conn.poll(0.25):
                try:
                    msg = self._conn.recv()
                except (EOFError, OSError):
                    raise self._crashed() from None
                kind = msg[0]
                last = time.monotonic()
                if kind == "stage":
                    self.stage = msg[1]
                    if on_stage:
                        on_stage(msg[1])
                elif kind == "progress":
                    if progress:
                        progress(msg[1])
                elif kind in final:
                    return msg[1]
                elif kind == "cancelled":
                    raise RemoteError("Cancelado.", "cancelled")
                elif kind == "error":
                    raise RemoteError(msg[1])
            elif not self._proc.is_alive():
                raise self._crashed()
            elif timeout is not None and time.monotonic() - last > timeout:
                self._kill()
                raise RemoteError(f"El {self.name} no responde (más de {int(timeout)} s sin avanzar) y se ha detenido.",
                                  "timeout")

    def _crashed(self) -> RemoteError:
        self._proc.join(2)
        code = self._proc.exitcode
        self._closed = True
        if self._cancel.is_set():
            return RemoteError("Cancelado.", "cancelled")
        hint = ""
        if code is not None and code < 0 or code in (3221225477, -1073741819):     # 0xC0000005: acceso no válido
            hint = " (fallo en código nativo; suele ser el controlador de la GPU)"
        return RemoteError(f"El {self.name} se ha cerrado inesperadamente (código {code}){hint}.", "crash")

    def call(self, method: str, *args, progress: Callable[[float], None] | None = None,
             timeout: float | None = 120.0, on_stage: Callable[[str], None] | None = None, **kwargs) -> Any:
        """Llama a ``obj.method(*args, **kwargs)`` en el hijo.

        ``timeout`` es el tiempo máximo **sin noticias** (progreso o etapas),
        no la duración total: una tarea larga que avanza no se corta.
        """
        with self._lock:
            if not self.alive:
                raise RemoteError(f"El {self.name} no está en marcha.", "crash")
            self._cancel.clear()
            try:
                self._conn.send((method, args, kwargs, progress is not None))
            except (BrokenPipeError, OSError):
                raise self._crashed() from None
            return self._wait(("result",), timeout, on_stage, progress)

    def cancel(self, grace: float = 8.0) -> None:
        """Pide parar; si el hijo no obedece a tiempo, se termina el proceso."""
        self._cancel.set()

        def later():
            time.sleep(grace)
            if self._cancel.is_set() and self._lock.locked():
                log.warning("El %s no atendió la cancelación: se termina el proceso", self.name)
                self._kill()
        threading.Thread(target=later, daemon=True).start()

    def _kill(self) -> None:
        self._closed = True
        try:
            self._proc.kill()
        except Exception:  # noqa: BLE001
            pass

    def close(self) -> None:
        if self._closed and not self._proc.is_alive():
            return
        self._closed = True
        try:
            self._conn.send((None, (), {}, False))
        except Exception:  # noqa: BLE001
            pass
        self._proc.join(3)
        if self._proc.is_alive():
            self._proc.kill()
            self._proc.join(2)
        try:
            self._conn.close()
        except Exception:  # noqa: BLE001
            pass
