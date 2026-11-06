"""Extrae los textos visibles de la interfaz (HTML, JS y mensajes de Python).

Los idiomas de la app se guardan en voicelab/ui/locales/<idioma>.js como un
diccionario cuya clave es el texto original en español. Este script devuelve
esas claves:

* Texto y atributos visibles (placeholder, title, aria-label) de index.html.
* Cadenas de los .js de la interfaz. Las concatenaciones ('a' + x + 'b') se
  convierten en patrones «a{}b»: i18n.js los reconoce en tiempo de ejecución
  y traduce también lo que va dentro de cada {} si lo conoce.
* Mensajes de Python que acaban en la interfaz (avisos, errores, fases de
  trabajo); los f-strings también se convierten en patrones.

Uso:
    python tools/i18n_extract.py            # lista de claves (JSON) en stdout
    python tools/i18n_extract.py --missing  # claves sin traducir por idioma
"""
from __future__ import annotations

import ast
import html
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "voicelab" / "ui"
PY = ROOT / "voicelab"
LANGS = ("en", "fr", "it", "pt", "ru", "zh", "ja")

# Archivos de Python cuyos textos nunca llegan a la interfaz.
PY_SKIP = {"selftest.py", "meanvc_worker.py", "rvc_trainer.py", "__main__.py", "devserver.py", "app.py"}
# Textos que no se traducen (nombres propios, teclas, restos de código).
NO_KEY = {"VoiceLab", "AI", "VoiceLab AI", "Ctrl", "Escape", "CABLE Output", "CABLE Input", "Hz", "MB", "GB",
          "no such device", "matches no streams", "Chorus",
          "Output file #0 does not contain"}
# Frase con mayúscula inicial y alguna palabra en minúsculas: «Aplicando efectos», «Tono (pitch)».
PHRASE = re.compile(r"^[A-ZÁÉÍÓÚ¿¡][^\s]*( .*)?\s.*\b[a-záéíóúñ]{3,}\b|^[A-ZÁÉÍÓÚ¿¡]\S* [a-záéíóúñ]{3,}")
LETTERS = re.compile(r"[A-Za-zÁÉÍÓÚÜáéíóúüñÑ]{2}")
SPANISH = re.compile(r"[áéíóúñ¿¡]|\b(de|la|el|en|y|con|para|tu|tus|no|se|que|los|las|un|una|del|al|es|por|sin)\b", re.I)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def useful(s: str) -> bool:
    if s in NO_KEY or "%." in s or "[data-" in s or re.match(r"^\[[\w-]+\]$", s):
        return False
    if re.match(r"^(/|inset\(|calc\()", s) or re.fullmatch(r"[a-z][a-z-]*\{\}", s) or s == "toast {}":
        return False          # selectores, rutas de la API y clases CSS con un hueco
    core = s.replace("{}", "")
    if not LETTERS.search(core):
        return False
    letters = len(re.findall(r"[A-Za-zÁÉÍÓÚÜáéíóúüñÑ]", core))
    if "{}" in s and letters < 4:
        return False
    if re.fullmatch(r"[\w.\-#/:=]+", s) and not re.search(r"[áéíóúñ¿¡]", s) and not s[:1].isupper():
        return False          # identificadores, rutas, clases CSS
    if re.search(r"^(https?:|data:|#|\.[\w-]+$|\w+\.(js|json|wav|onnx|css|svg|png)$)", s):
        return False
    return True


class _Html(HTMLParser):
    ATTRS = ("placeholder", "title", "aria-label", "alt", "data-title", "data-subtitle")

    def __init__(self, out: dict, src: str):
        super().__init__(convert_charrefs=True)
        self.out, self.src, self.skip = out, src, 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "svg"):
            self.skip += 1
        for k, v in attrs:
            if k in self.ATTRS and v:
                self.add(v)

    def handle_endtag(self, tag):
        if tag in ("script", "style", "svg"):
            self.skip = max(0, self.skip - 1)

    def handle_data(self, d):
        if not self.skip:
            self.add(d)

    def add(self, s):
        s = norm(s)
        if useful(s):
            self.out.setdefault(s, set()).add(self.src)


# ---------------------------------------------------------------- JS
_TOKEN = re.compile(r"""
    (?P<comment>//[^\n]*|/\*.*?\*/)
  | (?P<str>'(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*"|`(?:[^`\\]|\\.)*`)
  | (?P<word>[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)
  | (?P<num>\d+(?:\.\d+)?)
  | (?P<op>=>|===|!==|==|!=|<=|>=|&&|\|\||\?\?|\+\+|--|\+=|[-+*/%<>=!?:;,.(){}\[\]&|^~])
  | (?P<ws>\s+)
""", re.S | re.X)

_OPEN, _CLOSE = "([{", ")]}"
_DELIM = {",", ";", "?", ":", "=", "=>", "&&", "||", "??", "+=", "return", "(", "[", "{", ")", "]", "}",
          "===", "!==", "==", "!=", "<", ">", "<=", ">=", "!"}


def _js_tokens(src: str):
    toks = []
    for m in _TOKEN.finditer(src):
        kind = m.lastgroup
        if kind in ("comment", "ws"):
            continue
        toks.append((kind, m.group()))
    return toks


def _unquote(lit: str) -> str:
    body = lit[1:-1]
    if lit[0] == "`":
        body = re.sub(r"\$\{[^}]*\}", "{}", body)
    try:
        return json.loads('"' + body.replace('"', '\\"').replace("\\'", "'").replace("\\`", "`") + '"')
    except Exception:
        return body


def _operand_back(toks, i):
    """Índice del inicio del operando que termina en i (incluido)."""
    depth = 0
    j = i
    while j >= 0:
        k, v = toks[j]
        if v in _CLOSE:
            depth += 1
        elif v in _OPEN:
            if depth == 0:
                return j + 1
            depth -= 1
            if depth == 0:
                # llamada: f(...) → incluye el nombre
                if j > 0 and toks[j - 1][0] == "word":
                    j -= 1
                if j > 0 and toks[j - 1][1] in ("!", "typeof"):
                    j -= 1
                if j > 0 and toks[j - 1][1] == "." and False:
                    j -= 1
                # ¿sigue el operando hacia atrás (a.b(c).d)?
                if j > 0 and toks[j - 1][1] == ".":
                    j -= 1
                    continue
                return j
        elif depth == 0 and (v in _DELIM or v == "+" or k == "word" and v in ("return", "case", "typeof", "new")):
            return j + 1
        elif depth == 0 and k in ("word", "num", "str") and j > 0 and toks[j - 1][1] not in (".",) \
                and toks[j - 1][0] in ("word", "num", "str"):
            return j
        j -= 1
    return 0


def _operand_fwd(toks, i):
    """Índice del final (incluido) del operando que empieza en i."""
    depth = 0
    j = i
    n = len(toks)
    while j < n:
        k, v = toks[j]
        if v in _OPEN:
            depth += 1
        elif v in _CLOSE:
            if depth == 0:
                return j - 1
            depth -= 1
        elif depth == 0 and (v in _DELIM or v == "+"):
            return j - 1
        j += 1
    return n - 1


def _is_htmlish(ops) -> bool:
    text = " ".join(v for _, v in ops)
    return bool(re.search(r"(icon|svg|html|chip|badge|avatar)", text, re.I)) or any(
        k == "str" and re.search(r"<[a-z/]", v) for k, v in ops)


def _chains(toks):
    """Concatenaciones de cadenas: lista de (texto, contiene_tag_dinamico)."""
    seen = set()
    out = []
    for i, (k, v) in enumerate(toks):
        if k != "str" or i in seen:
            continue
        # retrocede por los '+'
        start = i
        while True:
            if start > 0 and toks[start - 1][1] == "+":
                s = _operand_back(toks, start - 2)
                if s > start - 1:
                    break
                start = s
            else:
                break
        parts = []
        j = start
        while True:
            end = _operand_fwd(toks, j)
            ops = toks[j:end + 1]
            if len(ops) == 1 and ops[0][0] == "str":
                seen.add(j)
                parts.append(("s", _unquote(ops[0][1])))
            elif not ops:
                break
            else:
                parts.append(("h" if _is_htmlish(ops) else "x", None))
            if end + 1 < len(toks) and toks[end + 1][1] == "+":
                j = end + 2
                continue
            break
        if not any(p[0] == "s" for p in parts):
            continue
        text = "".join(p[1] if p[0] == "s" else ("<i></i>" if p[0] == "h" else "{}") for p in parts)
        out.append(text)
    return out


def _add_js(out: dict, text: str, src: str):
    if "<" in text and re.search(r"<[a-zA-Z/!]", text):
        p = _Html(out, src)
        p.feed(text)
        p.close()
        return
    attrs = re.findall(r'\b(?:title|placeholder|aria-label)="([^"]*)"', text)
    if attrs or re.match(r'\s*\w[\w-]*="', text):
        for a in attrs:
            a = norm(a)
            if useful(a):
                out.setdefault(a, set()).add(src + "@attr")
        return
    raw = text.strip()
    s = norm(raw)
    if not useful(s):
        return
    if not (SPANISH.search(s) or "{}" in s or PHRASE.match(s) or re.fullmatch(r"[A-ZÁÉÍÓÚ¿¡][a-záéíóúñ]+( [a-záéíóúñ]+)*[.…:]?", s)):
        return
    if "\n" in raw.strip("\n "):
        out.setdefault(raw, set()).add(src + "@raw")      # confirm()/prompt(): conserva los saltos de línea
    out.setdefault(s, set()).add(src)


def extract_ui() -> dict:
    out: dict = {}
    p = _Html(out, "index.html")
    p.feed((UI / "index.html").read_text(encoding="utf-8"))
    for f in sorted(UI.glob("*.js")):
        if f.name in ("icons.js", "i18n.js"):
            continue
        for text in _chains(_js_tokens(f.read_text(encoding="utf-8"))):
            _add_js(out, text, f.name)
    return out


# ---------------------------------------------------------------- Python
LABEL_KEYS = {"label", "title", "hint", "desc", "description"}
_LOGGERS = {"debug", "info", "warning", "error", "exception", "critical"}


def _fstring(node) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                parts.append(str(v.value))
            else:
                parts.append("{}")
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        a, b = _fstring(node.left), _fstring(node.right)
        return (a if a is not None else "{}") + (b if b is not None else "{}") if (a or b) else None
    return None


def extract_py() -> dict:
    out: dict = {}
    for f in sorted(PY.rglob("*.py")):
        rel = f.relative_to(PY).as_posix()
        if "vendor/" in rel or f.name in PY_SKIP:
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"))
        skip = set()
        for node in ast.walk(tree):
            # docstrings
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                    skip.add(id(first.value))
            # llamadas a log.* y a funciones de depuración
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                owner = getattr(fn.value, "id", "") if isinstance(fn, ast.Attribute) else ""
                if (name in _LOGGERS and owner in ("log", "logger", "logging", "_log")) or name in (
                        "getLogger", "add_argument", "ArgumentParser", "environ", "getenv", "setdefault"):
                    for sub in ast.walk(node):
                        skip.add(id(sub))
            if isinstance(node, ast.Subscript):
                for sub in ast.walk(node.slice):
                    skip.add(id(sub))
        labels = set()
        for node in ast.walk(tree):
            # HOSTAPI_LABELS = {...}: diccionarios de etiquetas visibles
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict) and any(
                    isinstance(t, ast.Name) and t.id.isupper() for t in node.targets) and node.value.values and all(
                    isinstance(v, ast.Constant) and isinstance(v.value, str) for v in node.value.values):
                for v in node.value.values:
                    if isinstance(v, ast.Constant) and isinstance(v.value, str):
                        labels.add(id(v))
            # {"label": "Voz aguda", …}: textos visibles aunque no «parezcan» frases
            if isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values):
                    if isinstance(k, ast.Constant) and k.value in LABEL_KEYS and isinstance(v, ast.Constant) \
                            and isinstance(v.value, str):
                        labels.add(id(v))
        for node in ast.walk(tree):
            if id(node) in skip:
                continue
            if id(node) in labels and useful(norm(node.value)):
                out.setdefault(norm(node.value), set()).add(rel)
                continue
            if isinstance(node, ast.JoinedStr):
                for v in node.values:
                    skip.add(id(v))
            if isinstance(node, (ast.Constant, ast.JoinedStr)):
                s = _fstring(node)
                if not s or not isinstance(s, str):
                    continue
                s = norm(s)
                if " " not in s and not re.fullmatch(r"[A-ZÁÉÍÓÚ][a-záéíóúñ]+", s):
                    continue
                if not useful(s) or not (SPANISH.search(s) or PHRASE.match(s)):
                    continue
                if re.search(r"[{}]\w|%[sd]|\\\\|\bimport\b|\bdef\b|==|\w\(\)", s):
                    continue
                out.setdefault(s, set()).add(rel)
    return out


# Claves que no salen de la extracción automática (texto sueltos entre etiquetas).
EXTRA = {"o": "index.html", "abierta": "app.js", "cerrada": "app.js", "desactivada": "app.js",
         "(recomendado)": "app.js", "{} bloque · {} ms{}": "app.js", "{} bloques · {} ms{}": "app.js",
         "{} · {} hilos": "app.js", "Nombre «VoiceLab AI Microphone»": "app.js", "Solo CPU": "sysinfo.py",
         "(copia)": "api.py", "(fiel)": "api.py", "(voz convertida)": "api.py",
         "{}: la voz se entrecorta y suena robótica. {}": "ai.js"}


def extract() -> dict:
    keys = extract_ui()
    for k, src in EXTRA.items():
        keys.setdefault(k, set()).add(src)
    for k, v in extract_py().items():
        keys.setdefault(k, set()).update(v)
    return keys


def load_locale(lang: str) -> dict:
    text = (UI / "locales" / f"{lang}.js").read_text(encoding="utf-8")
    start = text.index("register(")
    body = text[text.index("{", start): text.rindex("}") + 1]
    return json.loads(body)


def main():
    keys = extract()
    if "--missing" in sys.argv:
        bad = 0
        for lang in LANGS:
            have = load_locale(lang)
            miss = [k for k in keys if k not in have]
            bad += len(miss)
            print(f"{lang}: {len(miss)} sin traducir")
            for k in miss[:20]:
                print("   ", k)
        sys.exit(1 if bad else 0)
    json.dump({k: sorted(v) for k, v in keys.items()}, sys.stdout, ensure_ascii=False, indent=0)


if __name__ == "__main__":
    main()
