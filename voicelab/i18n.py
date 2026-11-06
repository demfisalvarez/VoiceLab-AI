"""Idioma de los textos que Python muestra fuera de la página (diálogos de archivo de Windows).

La interfaz se traduce en el navegador (ui/i18n.js); aquí se reutilizan los mismos
diccionarios de ui/locales/<idioma>.js para lo poco que no pasa por la página.
"""
from __future__ import annotations

import json
import locale
import re
from functools import lru_cache

from . import paths

SUPPORTED = ("es", "en", "fr", "it", "pt", "ru", "zh", "ja")


def system_language() -> str:
    """Idioma de la interfaz de Windows (o del sistema), si la app lo tiene; si no, inglés."""
    name = ""
    try:
        import ctypes
        name = locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage(), "")
    except Exception:  # noqa: BLE001 - fuera de Windows
        try:
            name = locale.getlocale()[0] or ""
        except Exception:  # noqa: BLE001
            name = ""
    base = re.split(r"[-_.]", name.lower())[0] if name else ""
    return base if base in SUPPORTED else "en"


def resolve(pref: str | None) -> str:
    return pref if pref in SUPPORTED else system_language()


@lru_cache(maxsize=None)
def _dictionary(lang: str) -> tuple[dict, tuple]:
    try:
        text = (paths.UI_DIR / "locales" / f"{lang}.js").read_text(encoding="utf-8")
        start = text.index("register(")
        data = json.loads(text[text.index("{", start): text.rindex("}") + 1])
    except (OSError, ValueError):
        data = {}
    patterns = []
    for k, v in data.items():
        if "{}" in k:
            rx = re.compile("(.*?)".join(re.escape(p) for p in k.split("{}")) + r"\Z", re.S)
            patterns.append((len(k.replace("{}", "")), rx, v))
    patterns.sort(key=lambda p: -p[0])
    return data, tuple((rx, v) for _, rx, v in patterns)


def _fill(out: str, args: tuple) -> str:
    it = iter(args)

    def rep(m):
        if m.group(1):
            i = int(m.group(1)) - 1
            return args[i] if 0 <= i < len(args) else ""
        return next(it, "")
    return re.sub(r"\{(\d*)\}", rep, out)


def translate(text: str, lang: str) -> str:
    """Traduce un texto en español al idioma dado; si no lo conoce, lo devuelve igual."""
    if not text or lang == "es":
        return text
    data, patterns = _dictionary(lang)
    if text in data:
        return data[text]
    for rx, out in patterns:
        m = rx.match(text)
        if m:
            return _fill(out, tuple(data.get(a, a) for a in m.groups()))
    return text
