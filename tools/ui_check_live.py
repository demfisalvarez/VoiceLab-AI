"""Voz instantánea en directo: panel de Ajustes y controles del modulador.

Sin PyTorch ni pesos reales: se usa el proceso simulado de las pruebas
(``VOICELAB_MEANVC_WORKER``) y un entorno «instalado» falso.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(__file__))
from ui_common import OUT, ROOT, app, open_page  # noqa: E402

sys.path.insert(0, str(ROOT))


def prepare(data: Path) -> None:
    os.environ["VOICELAB_DATA_DIR"] = str(data)
    from voicelab.audio import mediaio
    from voicelab.profiles import ProfileStore
    store = ProfileStore(data / "profiles")
    prof = store.create("Narradora (30 s)", "instant", "Voz clonada para la prueba")
    t = np.arange(48000 * 8) / 48000
    mediaio.save_wav(store.path(prof["id"]) / "reference.wav", (0.3 * np.sin(2 * np.pi * 180 * t)).astype(np.float32), 48000)
    w = data / "models" / "meanvc2"
    w.mkdir(parents=True)
    (w / ".complete").write_text("{}")
    (w / "bench.json").write_text(json.dumps({"variant": "120ms", "ms_per_chunk": 71.5, "chunk_ms": 160.0, "rtf": 0.447}))


def main():
    errors = []
    rt = Path(tempfile.mkdtemp(prefix="vl-vcrt-"))
    (rt / "bin").mkdir()
    (rt / "bin" / "python").symlink_to(sys.executable)
    (rt / ".complete").write_text("{}")
    env = {"VOICELAB_VC_RUNTIME": str(rt), "VOICELAB_MEANVC_WORKER": str(ROOT / "tests" / "fake_meanvc_worker.py")}
    with app(8771, prepare, env) as (url, data), sync_playwright() as p:
        page = open_page(p, url, errors, int(os.environ.get("VL_SCALE", "1")))
        page.click('.nav-item[data-page="settings"]')
        page.wait_for_selector("#live-remove")
        page.wait_for_timeout(1000)
        page.evaluate("document.querySelector('#live-remove').scrollIntoView({block: 'center'})")
        print("panel:", page.locator("#ai-panel .model-row").last.inner_text().replace("\n", " ")[:260])
        page.screenshot(path=str(OUT / "40_voz_directo_ajustes.png"))

        page.click('.nav-item[data-page="modulator"]')
        page.wait_for_timeout(500)
        val = page.eval_on_selector("#profile-quick", "s => [...s.options].find(o => o.text.includes('Narradora')).value")
        page.select_option("#profile-quick", val)
        page.wait_for_selector("#live-on")
        print("casilla marcada:", page.is_checked("#live-on"), "| modos:", page.locator("#live-variant option").all_inner_texts())
        print("estado apagado:", page.inner_text("#live-status"))
        page.click("#mod-power")
        page.wait_for_function("() => (document.querySelector('#live-status') || {}).innerText?.includes('activa')", timeout=20000)
        page.wait_for_timeout(1500)
        print("estado encendido:", page.inner_text("#live-status"))
        page.evaluate("document.querySelector('#ai-voice').scrollIntoView({block: 'center'})")
        page.screenshot(path=str(OUT / "41_voz_directo_modulador.png"))
        page.select_option("#live-variant", "40ms")
        page.wait_for_function("() => (document.querySelector('#live-status') || {}).innerText?.includes('activa')", timeout=20000)
        page.uncheck("#live-on")
        page.wait_for_timeout(800)
        print("tras desactivar:", repr(page.inner_text("#live-status")), "| ai:", page.evaluate("VL.S.status.ai"))
        page.click("#mod-power")
        page.wait_for_timeout(500)
    print("errores de consola:", errors or "ninguno")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
