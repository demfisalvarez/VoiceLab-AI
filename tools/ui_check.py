"""Prueba de punta a punta de la interfaz en Chromium (Playwright).

Arranca VoiceLab AI en modo navegador con el motor real, recorre las páginas,
activa el modulador, mueve controles y guarda capturas en ``ui_shots/``.
Uso: python tools/ui_check.py
"""

import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "ui_shots"
OUT.mkdir(exist_ok=True)


def main() -> int:
    env = dict(os.environ, VOICELAB_DATA_DIR=tempfile.mkdtemp(prefix="vl-ui-"))
    proc = subprocess.Popen([sys.executable, "-m", "voicelab", "--no-window", "--port", "8765"],
                            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    url = None
    t0 = time.time()
    while time.time() - t0 < 20:
        line = proc.stdout.readline()
        m = re.search(r"(http://127\.0\.0\.1:\d+/\?token=\S+)", line)
        if m:
            url = m.group(1)
            break
    if not url:
        proc.kill()
        print("La app no arrancó")
        return 1

    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=int(os.environ.get("VL_SCALE", "1")),
                                    locale="es-ES")
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url)
            page.wait_for_selector("#boot.hide", timeout=10000)
            page.wait_for_timeout(500)
            page.screenshot(path=str(OUT / "01_inicio.png"))

            page.click('.nav-item[data-page="modulator"]')
            page.click("#mod-power")
            page.wait_for_selector("#mod-power.on", timeout=5000)
            page.wait_for_timeout(1200)
            lat = page.inner_text("#chip-latency-v")
            state = page.inner_text("#chip-state-t")
            print("estado:", state, "latencia:", lat, "entrada:", page.inner_text("#in-db"))
            assert state == "Activo", state
            assert lat.endswith("ms"), lat
            page.evaluate("document.getElementById('content').scrollTop = 0")
            page.wait_for_timeout(100)
            page.screenshot(path=str(OUT / "02_modulador_activo.png"))

            # Ganancia con el campo numérico → la API la aplica en vivo
            num = page.locator('[data-range="audio.input_gain_db"] input[type=number]')
            num.fill("-12")
            num.dispatch_event("change")
            page.wait_for_timeout(800)
            print("entrada tras −12 dB:", page.inner_text("#in-db"))

            # Monitorización: aviso de acople al activar sin auriculares
            page.click('[data-switch="audio.monitor_enabled"]')
            page.wait_for_selector("#modal.open", timeout=3000)
            page.screenshot(path=str(OUT / "03_aviso_monitor.png"))
            page.click("#modal-ok")
            page.wait_for_timeout(900)
            badge = page.inner_text('[data-route="monitor"] [data-r="badge"]')
            print("monitor:", badge)
            page.locator("#routes").scroll_into_view_if_needed()
            page.screenshot(path=str(OUT / "04_salidas.png"), full_page=False)

            page.click('.nav-item[data-page="home"]')
            page.wait_for_timeout(700)
            page.screenshot(path=str(OUT / "05_inicio_activo.png"))

            page.click('.nav-item[data-page="settings"]')
            page.wait_for_timeout(400)
            page.screenshot(path=str(OUT / "06_ajustes.png"))
            page.select_option('select[data-select="audio.block_size"]', "512")
            page.wait_for_timeout(1000)
            print("tras bloque 512:", page.inner_text("#chip-state-t"), page.inner_text("#chip-latency-v"))

            page.click('.nav-item[data-page="clone"]')
            page.wait_for_timeout(300)
            page.screenshot(path=str(OUT / "07_clonar_fase3.png"))

            page.keyboard.press("Control+m")
            page.wait_for_timeout(600)
            print("tras Ctrl+M:", page.inner_text("#chip-state-t"))

            # Recarga: los ajustes persisten
            page.reload()
            page.wait_for_selector("#boot.hide", timeout=10000)
            gain = page.input_value('[data-range="audio.input_gain_db"] input[type=number]')
            print("página tras recargar:", page.inner_text("#page-title"), "ganancia:", gain)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
    print("errores de consola:", errors or "ninguno")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
