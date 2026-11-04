"""Crea dist/VoiceLabAI.zip listo para Windows.

- .bat y .ps1 con finales de línea CRLF.
- .ps1 en UTF-8 con BOM (Windows PowerShell 5.1 lo necesita para leer tildes).
"""

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
TOP = "VoiceLab AI"
INCLUDE = ["Instalar VoiceLab AI.bat", "VoiceLab AI.exe", "README.md", "ARQUITECTURA.md", "requirements.txt",
           "voicelab", "assets", "installer", "tests", "tools", "build", ".github", "launcher"]
SKIP_DIRS = {"__pycache__", ".pytest_cache", "ui_shots", "dist"}
SKIP_SUFFIX = {".syso"}


def files():
    for item in INCLUDE:
        p = ROOT / item
        if p.is_file():
            yield p
        else:
            for f in sorted(p.rglob("*")):
                if f.is_file() and not (set(f.relative_to(ROOT).parts) & SKIP_DIRS) and f.suffix not in (".pyc", ".syso"):
                    yield f


def content(f: Path) -> bytes:
    data = f.read_bytes()
    if f.suffix in (".bat", ".ps1", ".iss"):
        text = data.decode("utf-8-sig").replace("\r\n", "\n").replace("\n", "\r\n")
        if f.suffix == ".bat":
            text.encode("ascii")  # los .bat deben ser ASCII puro
            return text.encode("ascii")
        return "﻿".encode("utf-8") + text.encode("utf-8")
    return data


def main():
    DIST.mkdir(exist_ok=True)
    out = DIST / "VoiceLabAI.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files():
            z.writestr(f"{TOP}/{f.relative_to(ROOT).as_posix()}", content(f))
    print(out, round(out.stat().st_size / 1024), "KB")


if __name__ == "__main__":
    main()
