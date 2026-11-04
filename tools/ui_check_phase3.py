"""Fase 3/6 de punta a punta: importar vídeo, analizar, crear perfil, grabar y editar."""
import os
import subprocess
import sys
import tempfile

from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(__file__))
from ui_common import OUT, app, open_page  # noqa: E402


def make_video(path):
    # 40 s de «voz» sintética (tono con sílabas) + vídeo de prueba
    expr = "0.25*sin(2*PI*(150+40*sin(2*PI*0.3*t))*t)*gt(sin(2*PI*2.3*t),-0.2)*lt(mod(t,3),2.4)"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=5:duration=40",
                    "-f", "lavfi", "-i", f"aevalsrc='{expr}':s=44100:d=40", "-shortest", "-c:v", "mpeg4", "-c:a", "aac", path], check=True)


def main():
    errors = []
    video = os.path.join(tempfile.mkdtemp(), "entrevista.mp4")
    make_video(video)
    with app(8767) as (url, data), sync_playwright() as p:
        page = open_page(p, url, errors, int(os.environ.get("VL_SCALE", "1")))
        page.click('.nav-item[data-page="clone"]')
        with page.expect_file_chooser() as fc:
            page.click('[data-import="clone"]')
        fc.value.set_files(video)                          # se sube por trozos, como al arrastrar
        page.wait_for_selector("#clone-step2:not([hidden])", timeout=30000)
        page.wait_for_timeout(800)
        box = page.locator('[data-wave="clone"]').bounding_box()
        page.mouse.move(box["x"] + box["width"] * 0.05, box["y"] + 60)
        page.mouse.down(); page.mouse.move(box["x"] + box["width"] * 0.85, box["y"] + 60, steps=8); page.mouse.up()
        print("selección:", page.inner_text('[data-wave-info="clone"]'))
        page.click("#clone-analyze")
        page.wait_for_selector("#clone-analysis .analysis", timeout=30000)
        print("análisis:", page.inner_text("#clone-analysis .notice").strip())
        page.fill("#clone-name", "Entrevistada")
        page.check('input[name="consent"][value="authorized"]')
        page.screenshot(path=str(OUT / "20_clonar.png"), full_page=False)
        page.click("#clone-create")
        page.wait_for_selector("#page-modulator.active #ai-voice .notice", timeout=30000)
        print("tras clonar (modulador):", page.inner_text("#ai-voice")[:160].replace("\n", " "))
        page.click('.nav-item[data-page="library"]')
        page.wait_for_selector("#page-library.active .lib-card", timeout=30000)
        print("biblioteca:", page.locator(".lib-card .lib-name").all_inner_texts(), page.locator(".lib-card .badge").all_inner_texts())
        # Grabar
        page.click('.nav-item[data-page="create"]')
        page.click("#rec-btn"); page.wait_for_timeout(1500); page.click("#rec-btn")
        page.wait_for_selector(".rec-row", timeout=10000)
        print("grabaciones:", page.locator(".rec-row b").all_inner_texts())
        page.screenshot(path=str(OUT / "21_grabar.png"))
        # Editor
        page.click('.nav-item[data-page="editor"]')
        page.wait_for_selector(".ed-item")
        page.locator(".ed-item").last.click()
        page.wait_for_selector("#ed-work:not([hidden])")
        page.wait_for_timeout(500)
        before = page.inner_text("#ed-dur")
        box = page.locator('[data-wave="editor"]').bounding_box()
        page.mouse.move(box["x"] + box["width"] * 0.25, box["y"] + 80)
        page.mouse.down(); page.mouse.move(box["x"] + box["width"] * 0.5, box["y"] + 80, steps=5); page.mouse.up()
        page.click('[data-op="crop"]'); page.wait_for_timeout(1500)
        print("recortar:", before, "->", page.inner_text("#ed-dur"))
        page.select_option("#ed-fx", "preset:radio")
        page.click('[data-op="effects"]'); page.wait_for_timeout(2500)
        page.click('[data-op="undo"]'); page.wait_for_timeout(1000)
        page.fill("#ed-rate", "0.8"); page.click('[data-op="tempo"]'); page.wait_for_timeout(3000)
        print("tempo 0.8:", page.inner_text("#ed-dur"))
        page.select_option("#ed-fmt", "mp3"); page.click("#ed-export"); page.wait_for_timeout(2500)
        page.screenshot(path=str(OUT / "22_editor.png"))
        toasts = page.locator(".toast div").all_inner_texts()
        print("avisos:", [t[:70] for t in toasts])
    print("errores de consola:", errors or "ninguno")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
