"""Fases 4 y 5: panel del motor de IA, texto a voz e importación RVC (sin modelos reales)."""
import os
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(__file__))
from ui_common import OUT, app, open_page  # noqa: E402


def main():
    errors = []
    with app(8768) as (url, data), sync_playwright() as p:
        page = open_page(p, url, errors, int(os.environ.get("VL_SCALE", "1")))
        page.click('.nav-item[data-page="settings"]')
        page.wait_for_selector("#ai-panel .model-row")
        print("motor:", page.inner_text("#ai-panel .notice")[:90])
        print("modelos:", page.locator(".model-row b").all_inner_texts())
        page.locator("#ai-card").scroll_into_view_if_needed()
        page.screenshot(path=str(OUT / "30_motor_ia.png"))
        page.click('.nav-item[data-page="tts"]')
        page.wait_for_timeout(600)
        page.fill("#tts-text", "Hola, esto es una prueba de texto a voz. Tiene dos frases.")
        print("aviso TTS:", page.inner_text("#tts-engine-note")[:100], "| botón activo:", page.is_enabled("#tts-go"))
        print("idiomas:", page.locator("#tts-lang option").count())
        page.screenshot(path=str(OUT / "31_texto_a_voz.png"))
        page.click('.nav-item[data-page="library"]')
        page.click("#lib-import-rvc")
        page.wait_for_timeout(400)
        print("aviso RVC:", page.locator(".toast div").last.inner_text()[:90])
    print("errores de consola:", errors or "ninguno")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
