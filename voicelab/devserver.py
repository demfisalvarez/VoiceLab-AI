"""Servidor local para el «modo navegador».

Se usa cuando la ventana nativa (WebView2) no está disponible y para las
pruebas automáticas. Sirve la misma interfaz y expone la misma API por HTTP
en 127.0.0.1, protegida con un token aleatorio por sesión.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .paths import UI_DIR

log = logging.getLogger(__name__)

_TYPES = {".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml",
          ".html": "text/html", ".png": "image/png", ".ico": "image/x-icon", ".woff2": "font/woff2"}


class DevServer:
    def __init__(self, api, host: str = "127.0.0.1", port: int = 0, ui_dir: Path = UI_DIR):
        self.api = api
        self.token = secrets.token_urlsafe(24)
        self.ui_dir = ui_dir.resolve()
        self.last_request = time.monotonic()
        self.closing_requested_at: float | None = None
        self.stopped = threading.Event()
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):  # silencio: se registran solo errores
                log.debug("http: " + fmt, *args)

            def _send(self, code: int, body: bytes, ctype: str) -> None:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)

            def _json(self, code: int, payload: dict) -> None:
                self._send(code, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                           "application/json; charset=utf-8")

            def do_GET(self):  # noqa: N802
                path = urlparse(self.path).path
                if path in ("", "/"):
                    path = "/index.html"
                target = (server.ui_dir / path.lstrip("/")).resolve()
                if server.ui_dir not in target.parents or not target.is_file():
                    self._send(404, b"No encontrado", "text/plain; charset=utf-8")
                    return
                ctype = _TYPES.get(target.suffix) or mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                if ctype.startswith("text/"):
                    ctype += "; charset=utf-8"
                self._send(200, target.read_bytes(), ctype)

            def do_POST(self):  # noqa: N802
                url = urlparse(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                if url.path == "/api/__closing":
                    # sendBeacon no permite cabeceras: el token va en la URL.
                    if parse_qs(url.query).get("token", [""])[0] == server.token:
                        server.closing_requested_at = time.monotonic()
                    self._send(204, b"", "text/plain")
                    return
                if self.headers.get("X-VoiceLab-Token") != server.token:
                    self._json(403, {"ok": False, "error": "Acceso no autorizado"})
                    return
                if not url.path.startswith("/api/"):
                    self._json(404, {"ok": False, "error": "Ruta desconocida"})
                    return
                name = url.path[len("/api/"):]
                func = getattr(server.api, name, None) if name and not name.startswith("_") else None
                if not callable(func):
                    self._json(404, {"ok": False, "error": f"Función desconocida: {name}"})
                    return
                try:
                    args = json.loads(raw or b"{}").get("args", [])
                    if not isinstance(args, list):
                        raise ValueError("args debe ser una lista")
                except ValueError as exc:
                    self._json(400, {"ok": False, "error": f"Petición no válida: {exc}"})
                    return
                server.last_request = time.monotonic()
                server.closing_requested_at = None
                try:
                    result = func(*args)
                except Exception as exc:  # pragma: no cover
                    log.exception("Error en la API: %s", name)
                    result = {"ok": False, "error": f"Error interno: {exc}"}
                self._json(200, result)

        self.httpd = ThreadingHTTPServer((host, port), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/?token={self.token}"

    def start(self) -> None:
        self._thread = threading.Thread(target=self.httpd.serve_forever, name="servidor-ui", daemon=True)
        self._thread.start()
        log.info("Interfaz disponible en http://127.0.0.1:%s", self.port)

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.stopped.set()

    def wait_until_closed(self, grace: float = 4.0, idle_timeout: float | None = None) -> None:
        """Bloquea hasta que se cierre la pestaña (aviso de cierre sin recarga
        posterior) o hasta que se llame a ``stop``."""
        while not self.stopped.is_set():
            time.sleep(0.5)
            now = time.monotonic()
            if self.closing_requested_at and now - self.closing_requested_at > grace:
                log.info("La interfaz se ha cerrado")
                return
            if idle_timeout and now - self.last_request > idle_timeout:
                log.info("Sin actividad de la interfaz durante %.0f s", idle_timeout)
                return
