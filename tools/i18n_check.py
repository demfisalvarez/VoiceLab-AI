"""Recorre la interfaz en cada idioma y lista los textos que siguen en español.

Uso: python tools/i18n_check.py [en fr …]   (capturas en ui_shots/i18n-<idioma>-<página>.png)
"""
import json
import sys

from playwright.sync_api import sync_playwright

from i18n_extract import extract, load_locale
from ui_common import OUT, app, open_page

PAGES = ["home", "modulator", "library", "clone", "create", "tts", "editor", "settings"]
LANGS = sys.argv[1:] or ["en", "fr", "it", "pt", "ru", "zh", "ja"]

# Nodos de texto visibles que parecen español (palabras frecuentes o acentos propios).
COLLECT = r"""() => {
  const re = /[áéíóúñ¿¡]|\b(de|la|el|los|las|con|para|una|del|que|por|sin|tu|tus|Ajustes|Voz|voz)\b/;
  const out = new Set();
  const tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = tw.nextNode())) {
    const el = n.parentElement;
    if (!el || el.closest('script,style,textarea,[translate="no"]')) continue;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height || getComputedStyle(el).visibility === 'hidden') continue;
    const t = n.data.replace(/\s+/g, ' ').trim();
    if (t && re.test(t)) out.add(t);
  }
  for (const el of document.querySelectorAll('[title],[placeholder],[aria-label]')) {
    for (const a of ['title', 'placeholder', 'aria-label']) {
      const v = el.getAttribute(a);
      if (v && re.test(v)) out.add('@' + a + ': ' + v);
    }
  }
  return [...out];
}"""


SPANISH_KEYS = set(extract())


def main():
    report = {}
    with app() as (url, _data), sync_playwright() as p:
        for lang in LANGS:
            errors = []
            page = open_page(p, url, errors, lang=lang)
            left = set()
            for name in PAGES:
                page.click(f'.nav-item[data-page="{name}"]')
                page.wait_for_timeout(500)
                left.update(page.evaluate(COLLECT))
                page.screenshot(path=str(OUT / f"i18n-{lang}-{name}.png"))
            # Lo que sigue en español: una clave tal cual, o un texto que no es ninguna traducción.
            values = {" ".join(v.split()) for v in load_locale(lang).values()}
            def text(t):
                return t.split(": ", 1)[1] if t.startswith("@") else t
            left = {t for t in left if text(t) not in values and (text(t) in SPANISH_KEYS or not any(c.isdigit() for c in t))}
            report[lang] = sorted(left)
            print(f"{lang}: {len(left)} textos en español · errores JS: {len(errors)}")
            for t in sorted(left):
                print("   ", t[:160])
            for e in errors[:5]:
                print("   JS:", e[:200])
            page.context.browser.close()
    (OUT / "i18n-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
