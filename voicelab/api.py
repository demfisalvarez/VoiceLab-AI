"""API que la interfaz llama desde JavaScript.

Cada método público devuelve un diccionario JSON con ``ok`` y, si algo falla,
``error`` con un mensaje en español listo para mostrar. Los atributos que
empiezan por ``_`` no se exponen a JavaScript.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
import sys
import threading
import webbrowser
from typing import Any, Callable

from . import APP_NAME, CURRENT_PHASE, __version__, sysinfo
from .audio.devices import HOSTAPI_LABELS, DeviceInfo, DeviceManager
from .audio.engine import ROUTE_NAMES, AudioEngine, EngineConfig, EngineError
from .audio import effects
from .config import Settings, SettingsError
from .profiles import ProfileError, ProfileStore
from . import paths

log = logging.getLogger(__name__)

EXTERNAL_LINKS = {
    "vbcable": "https://vb-audio.com/Cable/",
}


def _dev(d: DeviceInfo) -> dict:
    return {
        "name": d.name,
        "kind": d.kind,
        "inputs": d.inputs,
        "outputs": d.outputs,
        "default": d.is_default_input or d.is_default_output,
    }


class Api:
    def __init__(self, settings: Settings, devices: DeviceManager, engine: AudioEngine,
                 sysinfo_fn: Callable[[], dict] = sysinfo.collect, profiles: ProfileStore | None = None):
        self._settings = settings
        self._profiles = profiles or ProfileStore()
        self._window = None  # ventana de pywebview (diálogos de archivo)
        self._devices = devices
        self._engine = engine
        self._sysinfo_fn = sysinfo_fn
        self._sysinfo: dict | None = None
        self._sysinfo_lock = threading.Lock()
        self._on_quit: Callable[[], None] | None = None
        self._ui_ready = threading.Event()

    # --------------------------------------------------------- utilidades
    @staticmethod
    def _ok(**kw: Any) -> dict:
        return {"ok": True, **kw}

    @staticmethod
    def _fail(message: str, **kw: Any) -> dict:
        return {"ok": False, "error": message, **kw}

    def _engine_config(self) -> EngineConfig:
        snap = self._settings.snapshot()
        return EngineConfig.from_settings(snap["audio"], snap["voice"])

    def _devices_payload(self) -> dict:
        dm = self._devices
        if not dm.available:
            return {"available": False, "error": dm.error, "hostapis": [], "hostapi": None,
                    "inputs": [], "outputs": [], "virtual": {}, "defaults": {}}
        hostapi = dm.resolve_hostapi(self._settings.get("audio", "hostapi"))
        cable_out = dm.virtual_cable_output(hostapi)
        cable_rec = dm.virtual_cable_record(hostapi)
        default_in = dm.default_input(hostapi)
        default_out = dm.default_output(hostapi)
        return {
            "available": True,
            "error": None,
            "hostapis": [{"name": n, "label": HOSTAPI_LABELS.get(n, n)} for n in dm.hostapi_names()],
            "hostapi": hostapi,
            "inputs": [_dev(d) for d in dm.inputs(hostapi)],
            "outputs": [_dev(d) for d in dm.outputs(hostapi)],
            "virtual": {
                "cable_output": cable_out.name if cable_out else None,
                "cable_record": cable_rec.name if cable_rec else None,
                "is_vbcable": bool(cable_out and cable_out.kind == "vbcable_playback"),
                "renamed": bool(cable_rec and "voicelab" in cable_rec.name.lower()),
            },
            "defaults": {
                "input": default_in.name if default_in else None,
                "monitor": default_out.name if default_out else None,
                "cable": cable_out.name if cable_out else None,
            },
            "portaudio": dm.portaudio_version(),
        }

    def _reset_missing_devices(self) -> dict:
        audio = self._settings.audio()
        hostapi = self._devices.resolve_hostapi(audio.get("hostapi"))
        reset = {}
        for key, direction in (("input_device", "input"), ("cable_device", "output"),
                               ("monitor_device", "output"), ("aux_device", "output")):
            name = audio.get(key)
            if name and self._devices.find(hostapi, name, direction) is None:
                reset[key] = None
        if reset:
            self._settings.update({"audio": reset})
        return reset

    def _system(self) -> dict:
        with self._sysinfo_lock:
            if self._sysinfo is None:
                try:
                    self._sysinfo = self._sysinfo_fn()
                except Exception as exc:  # pragma: no cover
                    log.exception("Información del sistema no disponible")
                    self._sysinfo = {"error": str(exc)}
            return self._sysinfo

    # ------------------------------------------------------------ consultas
    def ui_ready(self, ms: float = 0) -> dict:
        """La interfaz avisa de que ya está dibujada (sirve para medir el arranque)."""
        log.info("Interfaz lista en %.1f s", float(ms or 0) / 1000)
        self._ui_ready.set()
        return self._ok()

    def get_initial_state(self) -> dict:
        return self._ok(
            app={"name": APP_NAME, "version": __version__, "phase": CURRENT_PHASE,
                 "platform": sys.platform},
            settings=self._settings.snapshot(),
            devices=self._devices_payload(),
            status=self._engine.status(),
            system=self._system(),
        )

    def get_status(self) -> dict:
        return {"ok": True, **self._engine.status()}

    def get_devices(self) -> dict:
        return self._ok(devices=self._devices_payload())

    def get_system_info(self) -> dict:
        return self._ok(system=self._system())

    # ------------------------------------------------------------- ajustes
    def update_settings(self, patch: dict) -> dict:
        try:
            changed = self._settings.update(patch)
        except SettingsError as exc:
            return self._fail(str(exc), settings=self._settings.snapshot())
        if "hostapi" in changed.get("audio", {}):
            # Cada controlador nombra los dispositivos a su manera (MME corta
            # los nombres): los que no existan en el nuevo vuelven a
            # «predeterminado» para no dejar el motor apuntando a la nada.
            changed["audio"].update(self._reset_missing_devices())
        result: dict[str, Any] = {"changed": changed}
        if "audio" in changed or "voice" in changed:
            if "hostapi" in changed.get("audio", {}):
                result["devices"] = self._devices_payload()
            if self._engine.running:
                try:
                    self._engine.apply(self._engine_config())
                except EngineError as exc:
                    return self._fail(str(exc), settings=self._settings.snapshot(),
                                      status=self._engine.status(), **result)
        return self._ok(settings=self._settings.snapshot(), status=self._engine.status(), **result)

    # --------------------------------------------------------------- motor
    def start_engine(self) -> dict:
        try:
            self._engine.start(self._engine_config())
        except EngineError as exc:
            log.warning("No se pudo iniciar el motor: %s", exc)
            return self._fail(str(exc), status=self._engine.status())
        except Exception as exc:  # pragma: no cover - errores inesperados
            log.exception("Fallo inesperado al iniciar el motor")
            return self._fail(f"Error inesperado al iniciar el audio: {exc}", status=self._engine.status())
        return self._ok(status=self._engine.status())

    def stop_engine(self) -> dict:
        self._engine.stop()
        return self._ok(status=self._engine.status())

    def toggle_engine(self) -> dict:
        if self._engine.running:
            return self.stop_engine()
        return self.start_engine()

    def refresh_devices(self) -> dict:
        was_running = self._engine.running
        if was_running:
            self._engine.stop()
        self._devices.refresh()
        result = self._ok(devices=self._devices_payload())
        if was_running:
            restarted = self.start_engine()
            if not restarted["ok"]:
                return self._fail("Lista actualizada, pero no se pudo reanudar el audio: "
                                  + restarted["error"], devices=result["devices"],
                                  status=restarted.get("status"))
        result["status"] = self._engine.status()
        return result

    def play_test_tone(self, route: str) -> dict:
        if route not in ROUTE_NAMES:
            return self._fail("Salida desconocida")
        try:
            device = self._engine._resolve_route_device(route, self._engine_config())  # noqa: SLF001
            self._engine.play_test_tone(device, self._settings.get("audio", "sample_rate"))
        except EngineError as exc:
            return self._fail(str(exc))
        if route == "cable":
            hint = ("El tono se envía al micrófono virtual: no lo oirás por tus altavoces. Compruébalo en el "
                    "medidor de «CABLE Output» del panel de Sonido de Windows o con «Probar micrófono» en Discord.")
        else:
            hint = f"Reproduciendo un tono de prueba por «{device.name}»."
        return self._ok(device=device.name, hint=hint)

    # ------------------------------------------------------------- sistema
    def open_sound_panel(self, tab: str = "recording") -> dict:
        if sys.platform != "win32":
            return self._fail("El panel de Sonido solo existe en Windows.")
        index = "1" if tab == "recording" else "0"
        try:
            subprocess.Popen(["control.exe", f"mmsys.cpl,,{index}"],  # noqa: S603,S607
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            return self._fail(f"No se pudo abrir el panel de Sonido: {exc}")
        return self._ok()

    def open_external(self, key: str) -> dict:
        url = EXTERNAL_LINKS.get(key)
        if url is None:
            return self._fail("Enlace no permitido")
        webbrowser.open(url)
        return self._ok(url=url)

    def check_updates(self) -> dict:
        """Opcional: lee un manifiesto JSON {"version": "x.y.z", "url": "..."} de la dirección configurada."""
        import json as _json
        import ssl
        import urllib.request
        url = self._settings.get("ui", "updates_url")
        if not url:
            return self._fail("No hay dirección de actualizaciones configurada.")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "VoiceLabAI"})
            with urllib.request.urlopen(req, timeout=10, context=ssl.create_default_context()) as r:  # noqa: S310
                data = _json.loads(r.read(65536).decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            return self._fail(f"No se pudo comprobar: {exc}")
        def ver(v):
            return tuple(int(x) for x in str(v).split(".")[:3] if x.isdigit())
        newer = ver(data.get("version", "0")) > ver(__version__)
        return self._ok(current=__version__, latest=data.get("version"), newer=newer,
                        url=data.get("url") if str(data.get("url", "")).startswith("https://") else None)

    def quit_app(self) -> dict:
        if self._on_quit is not None:
            threading.Timer(0.2, self._on_quit).start()
        return self._ok()

    # ================================================================ voz (Fase 2)
    def _apply_voice(self, params: dict, preset: str | None, profile_id: str | None) -> dict:
        res = self.update_settings({"voice": {"params": effects.sanitize(params), "preset": preset,
                                              "profile_id": profile_id}})
        return res

    def get_effects_schema(self) -> dict:
        schema = {k: {"default": d, "min": lo, "max": hi} for k, (d, lo, hi) in effects.PARAMS.items()}
        presets = [{"id": k, "label": v["label"], "params": effects.sanitize(v["params"])}
                   for k, v in effects.PRESETS.items()]
        return self._ok(schema=schema, presets=presets, eq_freqs=list(effects.EQ_FREQS))

    def set_voice_params(self, partial: dict) -> dict:
        if not isinstance(partial, dict):
            return self._fail("Parámetros no válidos")
        voice = self._settings.snapshot()["voice"]
        merged = {**voice["params"], **partial}
        return self._apply_voice(merged, voice.get("preset"), voice.get("profile_id"))

    def apply_preset(self, preset_id: str) -> dict:
        preset = effects.PRESETS.get(preset_id)
        if preset is None:
            return self._fail("Preajuste desconocido")
        return self._apply_voice(preset["params"], preset_id, None)

    def reset_voice(self) -> dict:
        return self._apply_voice({}, None, None)

    # ============================================================ perfiles
    def _profile_call(self, fn, *args) -> dict:
        try:
            result = fn(*args)
        except ProfileError as exc:
            return self._fail(str(exc))
        except OSError as exc:
            return self._fail(f"Error de archivo: {exc}")
        return self._ok(result=result, profiles=self._profiles.list(), folders=self._profiles.folders())

    def list_profiles(self) -> dict:
        return self._ok(profiles=self._profiles.list(), folders=self._profiles.folders(),
                        active=self._settings.get("voice", "profile_id"))

    def create_profile(self, data: dict) -> dict:
        data = data or {}
        params = self._settings.get("voice", "params") if data.get("use_current", True) else {}
        return self._profile_call(self._profiles.create, data.get("name", ""), "effects",
                                  data.get("description", ""), data.get("folder", ""), params)

    def update_profile(self, pid: str, patch: dict) -> dict:
        return self._profile_call(self._profiles.update, pid, patch)

    def save_voice_to_profile(self, pid: str) -> dict:
        res = self._profile_call(self._profiles.update, pid, {"effects": self._settings.get("voice", "params")})
        if res["ok"]:
            self._settings.update({"voice": {"profile_id": pid, "preset": None}})
        return res

    def duplicate_profile(self, pid: str) -> dict:
        return self._profile_call(self._profiles.duplicate, pid)

    def delete_profile(self, pid: str) -> dict:
        res = self._profile_call(self._profiles.delete, pid)
        if res["ok"] and self._settings.get("voice", "profile_id") == pid:
            self._settings.update({"voice": {"profile_id": None}})
        return res

    def set_profile_avatar(self, pid: str, data_url: str | None) -> dict:
        return self._profile_call(self._profiles.set_avatar, pid, data_url)

    def activate_profile(self, pid: str) -> dict:
        try:
            prof = self._profiles.get(pid)
        except ProfileError as exc:
            return self._fail(str(exc))
        res = self._apply_voice(prof.get("effects") or {}, None, pid)
        res["profile"] = prof
        return res

    def export_profile(self, pid: str) -> dict:
        try:
            name = self._profiles.get(pid)["name"]
            dest = self._save_dialog(f"{name}.vlprofile", "Perfil de VoiceLab AI (*.vlprofile)")
            out = self._profiles.export(pid, Path(dest) if dest else paths.documents_dir() / "Perfiles exportados")
        except ProfileError as exc:
            return self._fail(str(exc))
        return self._ok(path=str(out))

    def import_profile(self, name: str | None = None, b64: str | None = None) -> dict:
        """Con ventana nativa abre un diálogo; en modo navegador recibe el archivo en base64."""
        import base64
        import tempfile
        if b64:
            tmp = Path(tempfile.mkdtemp()) / "import.vlprofile"
            tmp.write_bytes(base64.b64decode(b64.split(",", 1)[-1]))
            src = tmp
        else:
            picked = self._open_dialog("Perfil de VoiceLab AI (*.vlprofile;*.zip)")
            if picked is None:
                return self._fail("upload", needs_upload=True) if self._window is None else self._ok(cancelled=True)
            src = Path(picked)
        return self._profile_call(self._profiles.import_file, src)

    def backup_profiles(self) -> dict:
        try:
            out = self._profiles.backup(paths.documents_dir() / "Copias de seguridad")
        except OSError as exc:
            return self._fail(f"No se pudo crear la copia: {exc}")
        return self._ok(path=str(out))

    def reveal_path(self, path: str) -> dict:
        p = Path(path)
        allowed = (paths.documents_dir().resolve(), paths.data_dir().resolve())
        try:
            rp = p.resolve()
        except OSError:
            return self._fail("Ruta no válida")
        if not any(a == rp or a in rp.parents for a in allowed):
            return self._fail("Solo se pueden abrir carpetas de VoiceLab AI")
        if sys.platform != "win32":
            return self._fail("Solo disponible en Windows")
        target = rp if rp.is_dir() else rp.parent
        subprocess.Popen(["explorer.exe", str(target)])  # noqa: S603,S607
        return self._ok()

    # ------------------------------------------------- diálogos de archivo
    def _dialog(self, kind: str, file_types: tuple, save_name: str | None = None):
        if self._window is None:
            return None
        import webview
        fd = getattr(webview, "FileDialog", None)
        mode = getattr(fd, kind.upper(), None) if fd else getattr(webview, f"{kind.upper()}_DIALOG")
        kwargs = {"file_types": file_types}
        if save_name:
            kwargs["save_filename"] = save_name
        res = self._window.create_file_dialog(mode, **kwargs)
        if not res:
            return None
        return res if isinstance(res, str) else res[0]

    def _open_dialog(self, file_type: str):
        return self._dialog("open", (file_type, "Todos los archivos (*.*)"))

    def _save_dialog(self, name: str, file_type: str):
        return self._dialog("save", (file_type,), name)


class MediaApiMixin:
    """Fase 3 y 6: importar, grabar, editar, analizar, exportar y crear perfiles de voz."""

    _uploads: dict = {}

    def _ws(self):
        if getattr(self, "_workspace", None) is None:
            from .workspace import Jobs, Player, Recorder, Workspace
            self._workspace, self._jobs = Workspace(), Jobs()
            self._player, self._recorder = Player(self._devices.sd), Recorder(self._devices.sd)
        return self._workspace

    def _job(self, label, fn) -> dict:
        self._ws()
        return self._ok(job=self._jobs.run(label, fn))

    def get_job(self, jid: str) -> dict:
        self._ws()
        job = self._jobs.get(jid)
        return self._ok(job=job) if job else self._fail("Tarea desconocida")

    # ----------------------------------------------------------- importar
    def _import_path(self, path: Path, name: str | None = None) -> dict:
        from .audio import mediaio
        from .workspace import SR

        def work(progress):
            progress(0.05)
            info = mediaio.probe(path)
            if not info.get("audio", True):
                raise mediaio.MediaError(f"«{path.name}» no tiene pista de audio.")
            progress(0.2)
            audio = mediaio.load_audio(path, SR)
            progress(0.85)
            meta = self._ws().create(audio, name or path.stem, "import", path.name)
            meta["was_video"] = bool(info.get("video"))
            return meta
        return self._job("Importando " + path.name, work)

    def import_media(self) -> dict:
        from .audio import mediaio
        ext = ";".join("*" + e for e in mediaio.INPUT_FORMATS)
        picked = self._open_dialog(f"Audio y vídeo ({ext})")
        if picked is None:
            return self._fail("upload", needs_upload=True) if self._window is None else self._ok(cancelled=True)
        return self._import_path(Path(picked))

    def upload_begin(self, name: str, size: int) -> dict:
        import tempfile
        from .audio import mediaio
        if Path(name).suffix.lower() not in mediaio.INPUT_FORMATS:
            return self._fail("Formato no admitido. Usa MP3, WAV, FLAC, M4A, AAC, OGG, MP4, MKV, MOV o WEBM.")
        if int(size) > 4 * 1024 ** 3:
            return self._fail("El archivo supera 4 GB.")
        uid = uuid4_hex()
        tmp = Path(tempfile.mkdtemp(prefix="voicelab-up-")) / Path(name).name
        self._uploads[uid] = {"path": tmp, "name": name, "fh": open(tmp, "wb")}  # noqa: SIM115
        return self._ok(upload=uid)

    def upload_chunk(self, uid: str, b64: str) -> dict:
        import base64
        up = self._uploads.get(uid)
        if not up:
            return self._fail("Subida desconocida")
        up["fh"].write(base64.b64decode(b64))
        return self._ok()

    def upload_finish(self, uid: str) -> dict:
        up = self._uploads.pop(uid, None)
        if not up:
            return self._fail("Subida desconocida")
        up["fh"].close()
        return self._import_path(up["path"], Path(up["name"]).stem)

    # ------------------------------------------------------------ elementos
    def list_items(self) -> dict:
        return self._ok(items=self._ws().list())

    def get_item(self, iid: str, points: int = 1600) -> dict:
        from .audio import analysis
        from .workspace import WorkspaceError
        try:
            ws = self._ws()
            meta = ws.meta(iid)
            return self._ok(item=meta, wave=analysis.waveform(ws.load(iid), int(points)))
        except WorkspaceError as exc:
            return self._fail(str(exc))

    def edit_item(self, iid: str, op: str, args: dict | None = None) -> dict:
        ws = self._ws()
        args = args or {}
        if op == "undo":
            return self._job("Deshacer", lambda p: ws.undo(iid))
        if op == "rename":
            return self._job("Renombrar", lambda p: ws.rename(iid, args.get("name", "")))
        if op == "delete_item":
            return self._job("Eliminar", lambda p: ws.delete(iid))
        if op == "split":
            return self._job("Dividir", lambda p: ws.split(iid, args.get("at", 0)))
        if op == "duplicate":
            return self._job("Duplicar", lambda p: ws.create(ws.load(iid), ws.meta(iid)["name"] + " (copia)", "edit", iid))
        labels = {"effects": "Aplicando efectos", "denoise": "Eliminando ruido", "tempo": "Cambiando el tempo",
                  "remove_silences": "Eliminando silencios"}
        return self._job(labels.get(op, "Editando"), lambda p: ws.apply(iid, op, args, p))

    def join_items(self, ids: list, name: str | None = None) -> dict:
        ws = self._ws()
        return self._job("Uniendo audios", lambda p: ws.join(list(ids), name))

    def analyze_item(self, iid: str, start=None, end=None) -> dict:
        from .audio import analysis
        from .workspace import SR
        ws = self._ws()

        def work(progress):
            x = ws.load(iid)
            i, j = ws.span(x, start, end)
            return analysis.analyze(x[i:j] if j > i else x, SR)
        return self._job("Analizando la voz", work)

    def export_item(self, iid: str, fmt: str, start=None, end=None) -> dict:
        from .audio import mediaio
        from .workspace import SR
        ws = self._ws()
        meta = ws.meta(iid)
        safe = "".join(c if c.isalnum() or c in " -_()" else "_" for c in meta["name"]).strip() or "audio"
        dest = self._save_dialog(f"{safe}.{fmt}", f"{fmt.upper()} (*.{fmt})")
        target = Path(dest) if dest else paths.documents_dir() / "Exportaciones" / f"{safe}.{fmt}"
        target.parent.mkdir(parents=True, exist_ok=True)

        def work(progress):
            x = ws.load(iid)
            i, j = ws.span(x, start, end)
            out = mediaio.export(target, x[i:j] if j > i else x, SR, fmt)
            return {"path": str(out)}
        return self._job(f"Exportando a {fmt.upper()}", work)

    # ------------------------------------------------- reproducir / grabar
    def _output_device(self):
        a = self._settings.audio()
        hostapi = self._devices.resolve_hostapi(a.get("hostapi"))
        dev = self._devices.find(hostapi, a.get("monitor_device"), "output") or self._devices.default_output(hostapi)
        return dev

    def play_item(self, iid: str, start=None, end=None) -> dict:
        from .workspace import SR, WorkspaceError
        try:
            ws = self._ws()
            x = ws.load(iid)
            i, j = ws.span(x, start, end)
            if j <= i:
                j = x.shape[0]
            dev = self._output_device()
            self._player.play(x[i:j], dev.index if dev else None, max(1, min(2, dev.outputs)) if dev else 2, i / SR)
        except (WorkspaceError, Exception) as exc:  # noqa: BLE001
            return self._fail(f"No se pudo reproducir: {exc}")
        return self._ok()

    def stop_playback(self) -> dict:
        self._ws()
        self._player.stop()
        return self._ok()

    def playback_status(self) -> dict:
        self._ws()
        return self._ok(player=self._player.status(), recorder=self._recorder.status())

    def start_recording(self) -> dict:
        from .audio.engine import _extra_settings
        self._ws()
        a = self._settings.audio()
        hostapi = self._devices.resolve_hostapi(a.get("hostapi"))
        dev = self._devices.find(hostapi, a.get("input_device"), "input") or self._devices.default_input(hostapi)
        if dev is None:
            return self._fail("No hay ningún micrófono disponible.")
        try:
            self._recorder.start(dev.index, max(1, min(2, dev.inputs)), _extra_settings(self._devices.sd, hostapi))
        except Exception as exc:  # noqa: BLE001
            return self._fail(f"No se pudo empezar a grabar con «{dev.name}»: {exc}")
        return self._ok(device=dev.name)

    def stop_recording(self, name: str | None = None) -> dict:
        self._ws()
        audio = self._recorder.stop()
        if audio.shape[0] < 4800:
            return self._fail("La grabación es demasiado corta.")
        meta = self._ws().create(audio, name or time_label("Grabación"), "recording")
        return self._ok(item=meta)

    # ------------------------------------------------ crear perfil de voz IA
    def create_voice_profile(self, data: dict) -> dict:
        """Crea un perfil de IA instantánea a partir de un fragmento (Fase 3)."""
        from .audio import analysis, mediaio
        from .workspace import SR
        data = data or {}
        if not (data.get("consent_own") or data.get("consent_authorized")):
            return self._fail("Confirma que la voz es tuya o que tienes autorización de la persona.")
        if not str(data.get("name", "")).strip():
            return self._fail("Escribe un nombre para el perfil.")
        ws = self._ws()

        def work(progress):
            x = ws.load(data["item_id"])
            i, j = ws.span(x, data.get("start"), data.get("end"))
            part = x[i:j] if j - i > SR else x
            progress(0.1)
            cleaned = analysis.clean_for_cloning(part, SR, 0.6 if data.get("clean", True) else 0.0,
                                                 trim=bool(data.get("clean", True)))
            progress(0.6)
            info = analysis.analyze(cleaned, SR)
            if info["tier"] == "insufficient":
                raise ValueError(f"Solo hay {info['speech_s']:.0f} s de voz útil: hacen falta al menos 10 s.")
            a, b = analysis.best_segment(cleaned, SR, 20.0)
            meta = ws.meta(data["item_id"])
            prof = self._profiles.create(
                data["name"], "instant", data.get("description", ""), data.get("folder", ""), {},
                {"method": "zero-shot (Chatterbox Multilingual)", "language": data.get("language", "es"),
                 "source": meta.get("source") or meta["name"], "segment": [round(i / SR, 2), round(j / SR, 2)],
                 "analysis": info, "consent": "own" if data.get("consent_own") else "authorized",
                 "created_with": "VoiceLab AI"})
            d = self._profiles.path(prof["id"])
            mediaio.save_wav(d / "reference.wav", cleaned[a:b], SR)
            if info["tier"] in ("rvc_basic", "rvc_good"):
                mediaio.save_wav(d / "material.wav", cleaned, SR)   # material para entrenar RVC
            if data.get("avatar"):
                self._profiles.set_avatar(prof["id"], data["avatar"])
            progress(1.0)
            return self._profiles.get(prof["id"])
        return self._job("Creando el perfil de voz", work)


class AIApiMixin:
    """Fases 4 y 5: motor de IA, modelos, texto a voz y conversión RVC."""

    def ai_status(self) -> dict:
        from .ai import models, runtime, tts
        from .ai import meanvc
        st = {"runtime": runtime.available(), "packages": runtime.packages(), "models": models.status(),
              "languages": tts.LANGUAGES, "providers": [], "live": meanvc.status()}
        if st["runtime"]:
            try:
                st["providers"] = runtime.providers()
            except Exception as exc:  # noqa: BLE001
                st["runtime_error"] = str(exc)
        return self._ok(ai=st)

    def ai_install_runtime(self) -> dict:
        from .ai import runtime
        return self._job("Instalando el motor de IA", runtime.install)

    def ai_install_model(self, key: str) -> dict:
        from .ai import models
        if key not in models.CATALOG:
            return self._fail("Modelo desconocido")
        if models.CATALOG[key]["task"] == "vc_live":
            return self.ai_install_live()
        return self._job("Descargando " + models.CATALOG[key]["name"], lambda p: models.install(key, p))

    def ai_remove_model(self, key: str) -> dict:
        from .ai import meanvc, models, tts
        if key == meanvc.MODEL_KEY:
            return self.ai_remove_live()
        tts.unload()
        models.remove(key)
        return self.ai_status()

    # ----------------------------------------------------------- texto a voz
    def tts_generate(self, data: dict) -> dict:
        from .ai import tts
        from .audio.mediaio import resample
        from .workspace import SR
        data = data or {}
        try:
            prof = self._profiles.get(data.get("profile_id", ""))
        except ProfileError as exc:
            return self._fail(str(exc))
        ref = self._profiles.path(prof["id"]) / "reference.wav"
        if not ref.exists():
            return self._fail("Ese perfil no tiene audio de referencia. Crea uno en «Clonar voz».")
        text = str(data.get("text", "")).strip()
        if not text:
            return self._fail("Escribe el texto que quieres convertir en voz.")
        if len(text) > 20000:
            return self._fail("El texto supera 20 000 caracteres; divídelo en varias generaciones.")
        model_key = self._settings.get("ai", "tts_model")
        gpu = self._settings.get("ai", "tts_device") == "gpu"
        lang = data.get("language") or prof.get("cloning", {}).get("language") or "es"
        args = (text, ref, lang, float(data.get("expressivity", 0.5)), float(data.get("stability", 1.0)),
                float(data.get("speed", 1.0)))

        def work(progress):
            stage = getattr(progress, "stage", lambda _t: None)
            wav, info = tts.service().synthesize(model_key, gpu, args, progress, stage)
            if info.get("fallback"):
                log.warning("Texto a voz: la GPU falló (%s); se usa la CPU desde ahora", info["fallback"])
                self._settings.update({"ai": {"tts_device": "cpu"}})
            name = f"{prof['name']}: {text[:40]}" + ("…" if len(text) > 40 else "")
            meta = self._ws().create(resample(wav, tts.SR, SR), name, "tts", prof["id"])
            meta["text"] = text
            meta["device"] = info["device"]
            meta["fallback"] = info.get("fallback")
            return meta
        return self._job("Generando voz", work)

    def tts_preload(self) -> dict:
        """Empieza a cargar el modelo en segundo plano (tarda 1–3 min por sesión de la app)."""
        from .ai import models, runtime, tts
        key = self._settings.get("ai", "tts_model")
        if runtime.available() and models.installed(key):
            tts.service().preload(key, self._settings.get("ai", "tts_device") == "gpu")
        return self.tts_status()

    def tts_status(self) -> dict:
        from .ai import tts
        return self._ok(tts=tts.service().status())

    def tts_cancel(self) -> dict:
        from .ai import tts
        tts.service().cancel()
        return self._ok()

    # ------------------------------------------------------------------ RVC
    def import_rvc_model(self, name: str, b64: str | None = None, filename: str | None = None) -> dict:
        import base64
        import json as _json
        import shutil
        import tempfile
        from .ai import rvc
        if b64:
            src = Path(tempfile.mkdtemp()) / (Path(filename or "modelo.onnx").name)
            src.write_bytes(base64.b64decode(b64.split(",", 1)[-1]))
        else:
            picked = self._open_dialog("Modelo RVC en ONNX (*.onnx)")
            if picked is None:
                return self._fail("upload", needs_upload=True) if self._window is None else self._ok(cancelled=True)
            src = Path(picked)
        if src.suffix.lower() != ".onnx":
            return self._fail("Solo se admiten modelos RVC exportados a ONNX (.onnx). Los .pth se pueden exportar con RVC-WebUI o Applio.")

        def work(progress):
            progress(0.2)
            gpu = self._settings.get("ai", "rvc_device") == "gpu"
            model = rvc.RemoteRVC(src, "file", gpu, getattr(progress, "stage", None))   # valida y detecta la frecuencia
            model.close()
            prof = self._profiles.create(name or src.stem, "rvc", "", "", {})
            d = self._profiles.path(prof["id"]) / "model"
            d.mkdir()
            shutil.copyfile(src, d / "model.onnx")
            (d / "rvc.json").write_text(_json.dumps({"file": "model.onnx", "sr": model.sr, "style": model.style,
                                                     "source": src.name}), encoding="utf-8")
            return self._profiles.update(prof["id"], {"model": {"kind": "rvc", "sr": model.sr, "source": src.name}})
        return self._job("Importando el modelo RVC", work)

    # -------------------------------------------- voz por IA en el modulador
    def _live_kind(self, prof: dict | None) -> str | None:
        """Qué conversión en directo corresponde al perfil: «rvc», «instant» o ninguna."""
        if not prof:
            return None
        if prof.get("type") == "rvc":
            return "rvc"
        if prof.get("type") == "instant" and self._settings.get("voice", "instant_live"):
            from .ai import meanvc
            if meanvc.installed() and (self._profiles.path(prof["id"]) / "reference.wav").exists():
                return "instant"
        return None

    def _clear_ai(self) -> None:
        self._ai_gen = getattr(self, "_ai_gen", 0) + 1
        self._engine.set_ai(None)

    def _set_ai_for_profile(self, prof: dict | None, gen: int | None = None, on_stage=None) -> None:
        """Carga (en el hilo de una tarea) la conversión por IA del perfil y la activa."""
        kind = self._live_kind(prof)
        if kind is None:
            self._clear_ai()
            return
        if not self._engine.running:
            return
        if gen is None:
            self._ai_gen = gen = getattr(self, "_ai_gen", 0) + 1
        sr = self._settings.get("audio", "sample_rate")
        pdir = self._profiles.path(prof["id"])
        if kind == "rvc":
            from .ai import rvc
            v = self._settings.snapshot()["voice"]
            model = rvc.RemoteRVC(pdir, "profile", self._settings.get("ai", "rvc_device") == "gpu", on_stage)
            if model.fallback:
                self._settings.update({"ai": {"rvc_device": "cpu"}})
            proc = rvc.RealtimeRVC(model, sr, semitones=v["rvc_pitch"])     # bloque automático (desde 0,1 s)
        else:
            from .ai import meanvc
            variant = self._settings.get("ai", "meanvc_variant")
            # Alta definición: solo en «Calidad» y si este PC la aguanta (medido al instalar).
            hd = bool(self._settings.get("ai", "meanvc_hd")) and meanvc.hd_allowed(variant)
            cur = self._engine.ai
            inner = getattr(cur, "inner", cur)
            if (isinstance(inner, meanvc.RealtimeMeanVC) and inner.variant == variant and inner.sr == sr
                    and (inner.out_sr > 16000) == hd and inner.error is None and inner.w.alive):
                emb = meanvc.profile_embedding(inner.w, pdir)     # mismo proceso: solo cambia la voz
                if gen == self._ai_gen:
                    inner.set_embedding(emb)
                    self._engine.set_ai(self._finish(inner, sr), close_old=False)   # por si cambió el acabado
                return
            worker = meanvc.MeanVCWorker(meanvc.worker_command(variant, threads=2 if hd else 1, hd=hd), realtime=True)
            try:
                worker.set_embedding(meanvc.profile_embedding(worker, pdir))
            except Exception:
                worker.close()
                raise
            proc = meanvc.RealtimeMeanVC(worker, sr, variant)
        if gen != self._ai_gen or not self._engine.running:   # el usuario ya eligió otra cosa
            proc.close()
            return
        self._engine.set_ai(self._finish(proc, sr))

    def _finish(self, proc, sr: int):
        """Limpieza de entrada y acabado de estudio alrededor de la voz de IA (si están activados)."""
        from .audio.polish import PolishedAI
        v = self._settings.snapshot()["voice"]
        if not (v["ai_polish"] or v["ai_clean_input"]):
            return proc
        hd = getattr(proc, "out_sr", 16000) >= 32000 or getattr(proc, "kind", "") == "rvc"
        return PolishedAI(proc, sr, clean_input=v["ai_clean_input"], polish=v["ai_polish"], air=hd)

    def _ai_job(self, prof: dict) -> str:
        self._ws()
        self._ai_gen = gen = getattr(self, "_ai_gen", 0) + 1
        label = "Cargando la voz RVC" if prof.get("type") == "rvc" else "Preparando la voz instantánea en directo"
        return self._jobs.run(label, lambda p: self._set_ai_for_profile(prof, gen, getattr(p, "stage", None))
                              or {"ai": True})

    def _apply_voice(self, params: dict, preset: str | None, profile_id: str | None) -> dict:
        res = super()._apply_voice(params, preset, profile_id)
        if res.get("ok") and profile_id is None:
            self._clear_ai()                    # preajuste o «voz original»: fuera la IA (y se anulan cargas en curso)
        return res

    def activate_profile(self, pid: str) -> dict:
        res = super().activate_profile(pid)
        if not res.get("ok"):
            return res
        prof = res.get("profile")
        if self._live_kind(prof) is None:
            self._clear_ai()
        elif self._engine.running:
            res["job"] = self._ai_job(prof)
        return res

    def delete_profile(self, pid: str) -> dict:
        active = self._settings.get("voice", "profile_id") == pid
        res = super().delete_profile(pid)
        if res.get("ok") and active:
            self._clear_ai()
        return res

    def start_engine(self) -> dict:
        res = super().start_engine()
        pid = self._settings.get("voice", "profile_id")
        if res.get("ok") and pid:
            try:
                prof = self._profiles.get(pid)
            except ProfileError:
                return res
            if self._live_kind(prof) is not None:
                res["job"] = self._ai_job(prof)
        return res

    def stop_engine(self) -> dict:
        res = super().stop_engine()
        self._clear_ai()                        # libera la memoria (y el proceso de la voz instantánea)
        return res

    def update_settings(self, patch: dict) -> dict:
        """Además de guardar, mantiene coherente la voz de IA del modulador."""
        res = super().update_settings(patch)
        if not res.get("ok"):
            return res
        ch = res.get("changed") or {}
        v, a, au = ch.get("voice", {}), ch.get("ai", {}), ch.get("audio", {})
        pid = self._settings.get("voice", "profile_id")
        try:
            prof = self._profiles.get(pid) if pid else None
        except ProfileError:
            prof = None
        typ = prof.get("type") if prof else None
        if self._live_kind(prof) is None:
            if "profile_id" in v or "instant_live" in v:
                self._clear_ai()
            return res
        if not self._engine.running or "profile_id" in v:      # de eso se encarga activate_profile
            return res
        reload = (("sample_rate" in au and self._engine.ai is None)
                  or (typ == "rvc" and ("rvc_pitch" in v or "rvc_block" in v))
                  or (typ == "instant" and ("instant_live" in v or "meanvc_variant" in a or "meanvc_hd" in a))
                  or "ai_polish" in v or "ai_clean_input" in v)
        if reload:
            res["job"] = self._ai_job(prof)
        return res

    # ------------------------------------------ voz instantánea en directo
    def ai_install_live(self) -> dict:
        from .ai import meanvc

        def work(progress):
            res = meanvc.install(progress)
            # El modo que mejor va en este PC: baja latencia si la CPU sobra, si no calidad.
            self._settings.update({"ai": {"meanvc_variant": res.get("variant") or "120ms"}})
            return res
        return self._job("Instalando la voz instantánea en directo", work)

    def ai_install_hd(self) -> dict:
        from .ai import meanvc
        return self._job("Descargando la alta definición (48 kHz)", meanvc.install_hd)

    def ai_remove_live(self) -> dict:
        from .ai import meanvc
        proc = self._engine.ai
        if getattr(proc, "kind", None) == "instant":
            self._clear_ai()
            proc.w.close()                      # esperar a que el proceso suelte sus archivos
        try:
            meanvc.remove()
        except RuntimeError as exc:
            return self._fail(str(exc))
        return self.ai_status()

    def convert_item_rvc(self, iid: str, pid: str, semitones: float = 0.0) -> dict:
        from .ai import rvc
        from .workspace import SR
        ws = self._ws()

        def work(progress):
            model = rvc.RemoteRVC(self._profiles.path(pid), "profile", self._settings.get("ai", "rvc_device") == "gpu",
                                  getattr(progress, "stage", None))
            try:
                out = model.convert(ws.load(iid), SR, float(semitones), progress)
            finally:
                model.close()
            return ws.create(out, ws.meta(iid)["name"] + " (voz convertida)", "edit", iid)
        return self._job("Convirtiendo la voz con IA", work)


def uuid4_hex() -> str:
    import uuid
    return uuid.uuid4().hex


def time_label(prefix: str) -> str:
    import time
    return time.strftime(f"{prefix} %d-%m-%Y %H.%M")


# La API final combina la base con la parte de medios.
_BaseApi = Api


class Api(AIApiMixin, MediaApiMixin, _BaseApi):  # type: ignore[no-redef]
    pass
