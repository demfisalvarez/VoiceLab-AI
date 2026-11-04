"""Fase 2 de punta a punta: preajustes, efectos, perfiles y biblioteca."""
import os
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(__file__))
from ui_common import OUT, app, open_page  # noqa: E402


def main():
    errors = []
    scale = int(os.environ.get("VL_SCALE", "1"))
    with app() as (url, data), sync_playwright() as p:
        page = open_page(p, url, errors, scale)
        page.click('.nav-item[data-page="modulator"]')
        page.click("#mod-power")
        page.wait_for_selector("#mod-power.on")
        page.click('[data-preset="monstruo"]')
        page.wait_for_timeout(500)
        print("voz:", page.inner_text("#voice-name"))
        assert page.inner_text("#voice-name") == "Voz de monstruo"
        num = page.locator('[data-fx="pitch"] input[type=number]')
        num.fill("-10"); num.dispatch_event("change")
        page.wait_for_timeout(500)
        print("tras tocar el tono:", page.inner_text("#voice-name"))
        eq = page.locator('[data-fx="eq5"] input[type=number]')
        eq.fill("6"); eq.dispatch_event("change")
        page.wait_for_timeout(400)
        page.click('[data-fxs="robot"]')
        page.wait_for_timeout(600)
        print("latencia con efectos:", page.inner_text("#chip-latency-v"))
        page.locator("#fx-card").scroll_into_view_if_needed()
        page.screenshot(path=str(OUT / "10_efectos.png"))
        # Guardar como perfil
        page.evaluate("document.getElementById('content').scrollTop = 0")
        page.click("#voice-save-new")
        page.fill("#pm-name", "Ogro de la cueva")
        page.fill("#pm-folder", "Juegos")
        page.fill("#pm-desc", "Voz grave y distorsionada para personajes.")
        page.click("#pm-ok")
        page.wait_for_timeout(700)
        print("perfil activo:", page.inner_text("#voice-name"))
        # Cambiar en caliente al original y volver al perfil
        page.click("#voice-reset"); page.wait_for_timeout(400)
        page.select_option("#profile-quick", label="Ogro de la cueva · Efectos")
        page.wait_for_timeout(500)
        print("tras volver al perfil:", page.inner_text("#voice-name"), "| motor:", page.inner_text("#chip-state-t"))
        # Biblioteca
        page.click('.nav-item[data-page="library"]')
        page.wait_for_selector(".lib-card")
        page.click('.lib-card [data-act="dup"]'); page.wait_for_timeout(500)
        page.click('.lib-card [data-act="fav"]'); page.wait_for_timeout(500)
        cards = page.locator(".lib-card .lib-name").all_inner_texts()
        print("biblioteca:", cards)
        page.fill("#lib-search", "copia"); page.wait_for_timeout(200)
        print("búsqueda 'copia':", page.locator(".lib-card .lib-name").all_inner_texts())
        page.fill("#lib-search", "")
        page.select_option("#lib-folder", "Juegos"); page.wait_for_timeout(200)
        page.screenshot(path=str(OUT / "11_biblioteca.png"))
        r = page.evaluate("VL.call('export_profile', document.querySelector('.lib-card').dataset.id)")
        print("exportado:", r.get("ok"), os.path.basename(r.get("path", "")))
        r = page.evaluate("VL.call('backup_profiles')")
        print("copia:", r.get("ok"), os.path.basename(r.get("path", "")))
        page.locator('.lib-card [data-act="del"]').last.click(); page.wait_for_timeout(500)
        print("tras eliminar:", page.locator(".lib-card .lib-name").all_inner_texts())
    print("errores de consola:", errors or "ninguno")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
