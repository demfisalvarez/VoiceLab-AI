"""Rutas de la aplicación y de los datos del usuario."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_ID

PACKAGE_DIR = Path(__file__).resolve().parent
UI_DIR = PACKAGE_DIR / "ui"
PROJECT_DIR = PACKAGE_DIR.parent
ASSETS_DIR = PROJECT_DIR / "assets"


def data_dir() -> Path:
    """Carpeta de datos del usuario (ajustes, perfiles, registros).

    Windows: %APPDATA%\\VoiceLabAI
    Otros:   $XDG_CONFIG_HOME/VoiceLabAI o ~/.config/VoiceLabAI

    Se puede forzar con la variable de entorno VOICELAB_DATA_DIR (útil para
    pruebas o instalaciones portables).
    """
    override = os.environ.get("VOICELAB_DATA_DIR")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_ID
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_ID
    base.mkdir(parents=True, exist_ok=True)
    return base


def logs_dir() -> Path:
    d = data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def settings_file() -> Path:
    return data_dir() / "settings.json"


def icon_file() -> Path | None:
    p = ASSETS_DIR / "icon.ico"
    return p if p.exists() else None


def documents_dir() -> Path:
    """Carpeta «Documentos\\VoiceLab AI» (respeta la redirección a OneDrive)."""
    base = None
    if sys.platform == "win32":
        try:
            import winreg
            key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                base = Path(os.path.expandvars(winreg.QueryValueEx(k, "Personal")[0]))
        except OSError:
            base = None
    if base is None or not base.exists():
        base = Path.home() / "Documents"
    d = base / "VoiceLab AI"
    d.mkdir(parents=True, exist_ok=True)
    return d


def recordings_dir() -> Path:
    d = data_dir() / "recordings"
    d.mkdir(parents=True, exist_ok=True)
    return d


def models_dir() -> Path:
    d = data_dir() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d
