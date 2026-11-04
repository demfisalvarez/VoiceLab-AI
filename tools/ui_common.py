"""Arranca VoiceLab AI en modo navegador para pruebas con Playwright."""
import os
import re
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "ui_shots"
OUT.mkdir(exist_ok=True)


@contextmanager
def app(port=8766, prepare=None, extra_env=None):
    env = dict(os.environ, VOICELAB_DATA_DIR=tempfile.mkdtemp(prefix="vl-ui-"), **(extra_env or {}))
    if prepare:
        prepare(Path(env["VOICELAB_DATA_DIR"]))
    proc = subprocess.Popen([sys.executable, "-m", "voicelab", "--no-window", "--port", str(port)], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    url = None
    t0 = time.time()
    while time.time() - t0 < 20 and not url:
        m = re.search(r"(http://127\.0\.0\.1:\d+/\?token=\S+)", proc.stdout.readline())
        url = m.group(1) if m else None
    try:
        yield url, env["VOICELAB_DATA_DIR"]
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()


def open_page(p, url, errors, scale=1):
    page = p.chromium.launch().new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=scale)
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("dialog", lambda d: d.accept())
    page.goto(url)
    page.wait_for_selector("#boot.hide", timeout=10000)
    page.wait_for_timeout(400)
    return page
