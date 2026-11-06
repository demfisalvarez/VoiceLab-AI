"""Idiomas de la interfaz: diccionarios completos, huecos coherentes y traducción en tiempo real."""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import i18n_extract  # noqa: E402

from voicelab import i18n  # noqa: E402
from voicelab.config import Settings  # noqa: E402

KEYS = list(i18n_extract.extract())


def holes(text: str) -> list[str]:
    return re.findall(r"\{(\d*)\}", text)


@pytest.mark.parametrize("lang", i18n_extract.LANGS)
def test_dictionary_complete(lang):
    d = i18n_extract.load_locale(lang)
    missing = [k for k in KEYS if k not in d]
    assert not missing, f"{lang}: faltan {len(missing)} textos, p. ej. {missing[:3]}"
    for k, v in d.items():
        assert v.strip(), (lang, k)
        n = k.count("{}")
        got = holes(v)
        if any(got):                       # {1}, {2}…: reordenados, todos los huecos usados
            assert sorted(int(i) for i in got) == list(range(1, n + 1)), (lang, k, v)
        else:
            assert len(got) == n, (lang, k, v)


def test_extraction_finds_dynamic_texts():
    assert "Cálculo {} ms por bloque de {} ms · latencia añadida ≈ {} ms{}" in KEYS     # concatenación en JS
    assert "Hay {} s de voz: hace falta al menos 1 minuto (mejor 10 min o más)." in KEYS  # f-string en Python
    assert "Voz aguda" in KEYS                                                         # etiqueta de preajuste
    assert not any(k.startswith("[data-") or k.startswith("/api") for k in KEYS)


def test_python_dialog_translation():
    assert i18n.translate("Todos los archivos (*.*)", "en") == "All files (*.*)"
    assert i18n.translate("Audio y vídeo (*.mp3;*.wav)", "fr") == "Audio et vidéo (*.mp3;*.wav)"
    assert i18n.translate("Texto desconocido", "ja") == "Texto desconocido"
    assert i18n.translate("Todos los archivos (*.*)", "es") == "Todos los archivos (*.*)"
    assert i18n.resolve("ru") == "ru" and i18n.resolve("auto") in i18n.SUPPORTED


def test_language_setting(tmp_path):
    s = Settings(tmp_path / "settings.json")
    assert s.get("ui", "language") == "auto"
    s.update({"ui": {"language": "ja"}})
    assert s.get("ui", "language") == "ja"
    with pytest.raises(Exception):
        s.update({"ui": {"language": "klingon"}})


JS_HARNESS = r"""
const fs = require('fs');
const store = {};
global.window = global;
global.localStorage = { getItem: k => store[k] ?? null, setItem: (k, v) => { store[k] = v; } };
Object.defineProperty(globalThis, 'navigator', {
  value: { languages: ['%(nav)s'], language: '%(nav)s' }, configurable: true });
global.location = { search: '' };
global.document = { documentElement: { style: {}, lang: '' }, write() {}, addEventListener() {} };
global.setTimeout = () => 0;
eval(fs.readFileSync(%(i18n)s, 'utf8'));
eval(fs.readFileSync(%(locale)s, 'utf8'));
const t = window.VL_I18N.t;
const cases = %(cases)s;
console.log(JSON.stringify({ lang: window.VL_I18N.lang, out: cases.map(c => t(c)) }));
"""


def run_js(nav, locale, cases):
    node = shutil.which("node")
    if not node:
        pytest.skip("node no está instalado")
    ui = ROOT / "voicelab" / "ui"
    code = JS_HARNESS % {"nav": nav, "i18n": json.dumps(str(ui / "i18n.js")),
                         "locale": json.dumps(str(ui / "locales" / f"{locale}.js")), "cases": json.dumps(cases)}
    res = subprocess.run([node, "-e", code], capture_output=True, text=True, timeout=30, encoding="utf-8")
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def test_js_runtime_patterns_and_nesting():
    r = run_js("en-US", "en", [
        "Ajustes",
        "  Detenido ",                                                   # conserva los espacios
        "Cálculo 62 ms por bloque de 80 ms · latencia añadida ≈ 250 ms · 3 cortes",
        "No se pudo preparar el motor: El modelo de texto a voz no está descargado. Instálalo en Ajustes → Motor de IA.",
        "El micrófono «USB Mic» no admite 44100 Hz. Prueba con otra frecuencia de muestreo en Ajustes o usa el controlador WASAPI.",
        "Hay una versión nueva: 1.2.0",
        "Mi perfil favorito",                                              # texto del usuario: igual
    ])
    assert r["lang"] == "en"
    out = r["out"]
    assert out[0] == "Settings"
    assert out[1] == "  Stopped "
    assert out[2] == "Compute 62 ms per 80 ms block · added latency ≈ 250 ms · 3 dropouts"
    assert out[3] == ("Could not prepare the engine: The text-to-speech model is not downloaded. "
                      "Install it in Settings → AI engine.")
    assert out[4].startswith("The microphone «USB Mic» does not support 44100 Hz.")
    assert out[5] == "A new version is available: 1.2.0"
    assert out[6] == "Mi perfil favorito"


def test_js_runtime_reordered_holes():
    r = run_js("ja-JP", "ja", ["Prueba en este equipo: 62 ms de cálculo por cada bloque de 80 ms (78 % de un núcleo)"])
    assert r["lang"] == "ja"
    assert r["out"][0] == "このPCでのテスト：80 ms のブロックごとに計算 62 ms（1コアの 78 %）"


def test_js_auto_language_falls_back_to_english():
    assert run_js("de-DE", "en", ["Ajustes"])["out"] == ["Settings"]
    assert run_js("es-ES", "en", ["Ajustes"])["lang"] == "es"
