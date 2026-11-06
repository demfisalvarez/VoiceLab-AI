"""Capturas del manual (``docs/manual/img``) con la app real en Chromium.

Prepara un espacio de datos de demostración (perfiles de ejemplo, voz en directo
simulada, dispositivos con nombres normales) y recorre todas las páginas.
Uso: python tools/manual_shots.py [idioma]   (es → img/*.png; otro → img/<idioma>/*.webp)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(__file__))
from ui_common import ROOT, app  # noqa: E402

sys.path.insert(0, str(ROOT))
IMG = ROOT / "docs" / "manual" / "img"
SR = 48000
LANG = (sys.argv[1] if len(sys.argv) > 1 else "es").lower()

# Datos de demostración en cada idioma: nombres de dispositivos como los pone Windows,
# perfiles de ejemplo y el texto de «Texto a voz».
DEMO = {
    "es": ("Micrófono", "Auriculares", ["Robot de ciencia ficción", "Voz metálica para partidas y streams.", "Juegos",
           "Locutor de radio", "Voz grave con compresión, como en la radio.", "Directos",
           "Narradora", "Voz clonada de una narradora (con autorización).", "Clonadas", "Mi voz"],
           "Hola a todos. Bienvenidos al directo de hoy: vamos a probar la nueva actualización y a responder a vuestras preguntas."),
    "en": ("Microphone", "Headphones", ["Sci-fi robot", "Metallic voice for games and streams.", "Games",
           "Radio host", "Deep voice with compression, like on the radio.", "Streams",
           "Narrator", "Voice cloned from a narrator (with permission).", "Cloned", "My voice"],
           "Hi everyone. Welcome to today's stream: we're going to try the new update and answer your questions."),
    "fr": ("Microphone", "Casque", ["Robot de science-fiction", "Voix métallique pour les parties et les streams.", "Jeux",
           "Animateur radio", "Voix grave compressée, comme à la radio.", "Directs",
           "Narratrice", "Voix clonée d'une narratrice (avec autorisation).", "Clonées", "Ma voix"],
           "Bonjour à tous. Bienvenue dans le direct du jour : on va tester la nouvelle mise à jour et répondre à vos questions."),
    "it": ("Microfono", "Cuffie", ["Robot fantascientifico", "Voce metallica per partite e stream.", "Giochi",
           "Speaker radiofonico", "Voce grave con compressione, come alla radio.", "Dirette",
           "Narratrice", "Voce clonata da una narratrice (con autorizzazione).", "Clonate", "La mia voce"],
           "Ciao a tutti. Benvenuti alla diretta di oggi: proviamo il nuovo aggiornamento e rispondiamo alle vostre domande."),
    "pt": ("Microfone", "Fones de ouvido", ["Robô de ficção científica", "Voz metálica para partidas e lives.", "Jogos",
           "Locutor de rádio", "Voz grave com compressão, como no rádio.", "Lives",
           "Narradora", "Voz clonada de uma narradora (com autorização).", "Clonadas", "Minha voz"],
           "Olá a todos. Bem-vindos à live de hoje: vamos testar a nova atualização e responder às suas perguntas."),
    "ru": ("Микрофон", "Наушники", ["Робот из фантастики", "Металлический голос для игр и стримов.", "Игры",
           "Радиоведущий", "Низкий голос с компрессией, как на радио.", "Стримы",
           "Рассказчица", "Голос рассказчицы (с её разрешения).", "Клонированные", "Мой голос"],
           "Всем привет! Добро пожаловать на сегодняшний стрим: попробуем новое обновление и ответим на ваши вопросы."),
    "zh": ("麦克风", "耳机", ["科幻机器人", "适合游戏和直播的金属质感声音。", "游戏",
           "电台主播", "带压缩的低沉声音，像电台一样。", "直播",
           "旁白女声", "克隆自一位旁白的声音（已获授权）。", "克隆", "我的声音"],
           "大家好，欢迎来到今天的直播：我们来试试新版本，并回答大家的问题。"),
    "ja": ("マイク", "ヘッドホン", ["SFロボット", "ゲームや配信向けの金属的な声。", "ゲーム",
           "ラジオDJ", "ラジオのような圧縮の効いた低い声。", "配信",
           "ナレーター", "ナレーターからクローンした声（許可済み）。", "クローン", "自分の声"],
           "みなさん、こんにちは。今日の配信へようこそ。新しいアップデートを試して、質問にお答えします。"),
}
MIC_WORD, PHONES_WORD, NAMES, TTS_TEXT = DEMO[LANG]
MIC = f"{MIC_WORD} (Realtek(R) Audio)"
PHONES = f"{PHONES_WORD} (Realtek(R) Audio)"
OUT = IMG if LANG == "es" else IMG / LANG

ASOUNDRC = """
pcm.vl_mic_raw { type file; slave.pcm "null"; file "/dev/null"; infile "%(mic)s"; format "raw"; }
pcm."%(mic_name)s" {
    type plug
    slave { pcm "vl_mic_raw"; format S16_LE; rate 48000; channels 1; }
    hint { show on; description "mic"; }
}
pcm.vl_cable_raw { type file; slave.pcm "null"; file "%(cable)s"; format "raw"; }
pcm."CABLE Input (VB-Audio Virtual Cable)" {
    type plug
    slave { pcm "vl_cable_raw"; format FLOAT_LE; rate 48000; channels 2; }
    hint { show on; description "cable"; }
}
pcm.vl_mon_raw { type file; slave.pcm "null"; file "%(mon)s"; format "raw"; }
pcm."%(phones_name)s" {
    type plug
    slave { pcm "vl_mon_raw"; format FLOAT_LE; rate 48000; channels 2; }
    hint { show on; description "monitor"; }
}
"""


def voiceish(seconds: float, f0: float = 150.0, seed: int = 1) -> np.ndarray:
    """Señal parecida a la voz (vocales con armónicos y sílabas), para medidores y ondas."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * SR)) / SR
    pitch = f0 * (1 + 0.12 * np.sin(2 * np.pi * 0.4 * t) + 0.05 * np.sin(2 * np.pi * 1.7 * t))
    ph = 2 * np.pi * np.cumsum(pitch) / SR
    x = sum(np.sin(k * ph) / k ** 1.2 for k in range(1, 12))
    syll = (np.sin(2 * np.pi * 3.1 * t) > -0.3) * ((t % 4.0) < 3.2)
    env = np.convolve(syll.astype(float), np.ones(800) / 800, "same")
    x = x * env * (0.6 + 0.4 * rng.random(t.shape[0]) ** 0.1)
    return (0.25 * x / np.max(np.abs(x))).astype(np.float32)


def paced_fifos(tmp: Path, mic: np.ndarray) -> dict:
    """Tuberías que van al ritmo real: el «micrófono» entrega audio a 48 kHz y las salidas
    lo consumen al mismo ritmo (los dispositivos «null» de ALSA no llevan reloj y darían
    cortes que no existen en un equipo de verdad)."""
    import threading
    import time
    paths = {k: tmp / f"{k}.fifo" for k in ("mic", "cable", "mon")}
    for f in paths.values():
        os.mkfifo(f)

    def writer(f, data: bytes, rate: int):
        fd = os.open(f, os.O_RDWR)                       # no bloquea ni da EOF
        t0, sent, chunk = time.monotonic(), 0, rate // 100
        while True:
            for i in range(0, len(data), chunk):
                os.write(fd, data[i:i + chunk])
                sent += chunk
                wait = t0 + sent / rate - time.monotonic()
                if wait > 0:
                    time.sleep(wait)

    def reader(f, rate: int):
        import fcntl
        fd = os.open(f, os.O_RDWR)
        fcntl.fcntl(fd, 1031, 4096)                      # F_SETPIPE_SZ: sin ráfagas de 170 ms
        t0, got = time.monotonic(), 0
        while True:
            got += len(os.read(fd, rate // 400))
            wait = t0 + got / rate - time.monotonic()
            if wait > 0:
                time.sleep(wait)

    pcm = (np.clip(mic, -1, 1) * 32767).astype("<i2").tobytes()
    threading.Thread(target=writer, args=(paths["mic"], pcm, SR * 2), daemon=True).start()
    for k in ("cable", "mon"):
        threading.Thread(target=reader, args=(paths[k], SR * 2 * 4), daemon=True).start()
    return {k: str(v) for k, v in paths.items()}


def prepare(data: Path) -> None:
    os.environ["VOICELAB_DATA_DIR"] = str(data)
    from voicelab.audio import mediaio
    from voicelab.profiles import ProfileStore
    store = ProfileStore(data / "profiles")
    from voicelab.audio.effects import PRESETS
    # Efectos
    n = NAMES
    store.create(n[0], "effects", n[1], n[2], dict(PRESETS["robot"]["params"], pitch=-2))
    store.create(n[3], "effects", n[4], n[5],
                 {"pitch": -3, "formant": -1, "bass": 3, "comp_enabled": True, "comp_threshold": -20, "comp_ratio": 3})
    # Voz instantánea con material para entrenar (12 min de voz)
    prof = store.create(n[6], "instant", n[7], n[8],
                        cloning={"analysis": {"speech_s": 742, "tier": "rvc_good"}, "language": LANG})
    pdir = store.path(prof["id"])
    mediaio.save_wav(pdir / "reference.wav", voiceish(10, 210), SR)
    mediaio.save_wav(pdir / "material.wav", voiceish(20, 210), SR)
    # Voz instantánea en directo «instalada» (proceso simulado de las pruebas)
    w = data / "models" / "meanvc2"
    w.mkdir(parents=True)
    (w / ".complete").write_text("{}")
    (w / "bench.json").write_text(json.dumps({"variant": "120ms", "ms_per_chunk": 48.0, "chunk_ms": 160.0, "rtf": 0.3}))
    (w / "bench_40ms.json").write_text(json.dumps({"variant": "40ms", "ms_per_chunk": 41.0, "chunk_ms": 80.0, "rtf": 0.51}))
    (data / "settings.json").write_text(json.dumps({
        "voice": {"profile_id": prof["id"]},
        "ai": {"meanvc_variant": "40ms"},
        "audio": {"monitor_device": PHONES}}), encoding="utf-8")


def shot(page, name: str, scroll: str | None = None, top: bool = True, height: int | None = None) -> None:
    if scroll:
        page.evaluate(f"document.querySelector({scroll!r}).scrollIntoView({{block: 'start'}})")
        page.evaluate("document.getElementById('content').scrollBy(0, -16)")
    elif top:
        page.evaluate("document.getElementById('content').scrollTop = 0")
    page.wait_for_timeout(350)
    page.evaluate("document.querySelectorAll('.toast').forEach(t => t.remove())")
    clip = {"x": 0, "y": 0, "width": 1440, "height": height} if height else None
    if LANG == "es":
        page.screenshot(path=str(OUT / f"{name}.png"), clip=clip)
    else:                                   # WebP: la cuarta parte de tamaño, GitHub lo muestra igual
        from io import BytesIO

        from PIL import Image
        Image.open(BytesIO(page.screenshot(clip=clip))).save(OUT / f"{name}.webp", "WEBP", quality=88, method=6)
    print("captura:", name, flush=True)
    if LANG in ("en", "ru", "zh", "ja"):      # idiomas sin palabras en común con el español: avisa de restos
        left = page.evaluate(SPANISH_LEFT)
        for t in left:
            print("   ¿sin traducir?", t[:140], flush=True)


SPANISH_LEFT = r"""() => {
  const re = /[áéíóúñ¿¡]|\b(de|la|el|los|las|con|para|una|del|que|por|sin|tu|voz|Voz|hora|horas|Ajustes)\b/;
  const out = new Set();
  const tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = tw.nextNode())) {
    const el = n.parentElement;
    if (!el || el.closest('script,style,textarea,[translate="no"]')) continue;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    const t = n.data.replace(/\s+/g, ' ').trim();
    if (t && re.test(t) && !/Realtek|VB-Audio|CABLE|\.wav|\.m4a/.test(t)) out.add(t);
  }
  document.querySelectorAll('select option:checked').forEach(o => { if (re.test(o.text)) out.add('[opción] ' + o.text); });
  return [...out];
}"""


def go(page, name: str) -> None:
    page.click(f'.nav-item[data-page="{name}"]')
    page.wait_for_timeout(700)


def pick(page, select: str, starts: str) -> None:
    """Elige en un desplegable la opción que empieza por ``starts`` (las etiquetas cambian con el idioma)."""
    value = page.eval_on_selector(select, "(s, t) => [...s.options].find(o => o.text.startsWith(t)).value", starts)
    page.select_option(select, value)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    tmp = Path(tempfile.mkdtemp(prefix="vl-manual-"))
    fifos = paced_fifos(tmp, voiceish(120))
    home = tmp / "home"
    home.mkdir()
    (home / ".asoundrc").write_text(ASOUNDRC % dict(fifos, mic_name=MIC, phones_name=PHONES), encoding="utf-8")
    rt = tmp / "vc-runtime"
    (rt / "bin").mkdir(parents=True)
    (rt / "bin" / "python").symlink_to(sys.executable)
    (rt / ".complete").write_text("{}")
    env = {"HOME": str(home), "VOICELAB_VC_RUNTIME": str(rt), "FAKE_MVC_STEADY": "1", "FAKE_MVC_WORK_MS": "45",
           "VOICELAB_MEANVC_WORKER": str(ROOT / "tests" / "fake_meanvc_worker.py")}
    video = tmp / ("entrevista.mp4" if LANG == "es" else "interview.mp4")
    clip = tmp / ("voz.wav" if LANG == "es" else "sample.wav")
    from voicelab.audio import mediaio
    mediaio.save_wav(clip, voiceish(95, 190, 3), SR)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(clip), str(video.with_suffix(".m4a"))],
                   check=True)
    with app(8781, prepare, env) as (url, data), sync_playwright() as p:
        page = p.chromium.launch().new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1,
                                            locale="es-ES")
        url += "&lang=" + LANG
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("dialog", lambda d: d.accept())
        page.goto(url)
        page.wait_for_selector("#boot.hide", timeout=15000)
        page.wait_for_timeout(800)
        shot(page, "01-inicio", height=470)          # sin «Tu equipo» (es el PC Linux de las capturas)

        # ---- modulador
        go(page, "modulator")
        pick(page, "#profile-quick", NAMES[0] + " · ")
        page.wait_for_timeout(500)
        page.click("#mod-power")
        page.wait_for_selector("#mod-power.on", timeout=8000)
        page.wait_for_timeout(2500)
        shot(page, "02-modulador")
        # Los dispositivos de prueba de Linux no llevan el reloj de una tarjeta de sonido y dan
        # «cortes» que no existen en Windows: las salidas se capturan con el modulador parado.
        page.click("#mod-power")
        page.wait_for_timeout(800)
        shot(page, "03-salidas", scroll="#routes")
        shot(page, "04-efectos", scroll="#fx-card")
        page.click("#mod-power")
        page.wait_for_selector("#mod-power.on", timeout=8000)

        # ---- voz instantánea en directo
        pick(page, "#profile-quick", NAMES[6] + " · ")
        page.wait_for_selector("#live-on", timeout=10000)
        if not page.is_checked("#live-on"):
            page.check("#live-on")
        page.wait_for_selector("#live-status .notice.ok", timeout=30000)
        page.wait_for_timeout(2500)
        shot(page, "05-voz-en-directo", scroll="#ai-voice")
        page.click("#mod-power")
        page.wait_for_timeout(800)
        page.wait_for_selector("#train-box .card, #train-box .notice", timeout=10000)
        page.wait_for_timeout(600)
        shot(page, "06-entrenar-voz-fiel", scroll="#train-box")

        # ---- biblioteca
        go(page, "library")
        shot(page, "07-biblioteca")

        # ---- clonar
        go(page, "clone")
        shot(page, "08-clonar-subir")
        with page.expect_file_chooser() as fc:
            page.click('[data-import="clone"]')
        fc.value.set_files(str(video.with_suffix(".m4a")))
        page.wait_for_selector("#clone-step2:not([hidden])", timeout=60000)
        page.wait_for_timeout(800)
        shot(page, "09-clonar-seleccion", scroll="#clone-step2")
        page.click("#clone-analyze")
        page.wait_for_selector("#clone-analysis .analysis", timeout=60000)
        page.fill("#clone-name", NAMES[9])
        page.check('input[name="consent"][value="own"]')
        page.wait_for_timeout(500)
        shot(page, "10-clonar-crear", scroll="#clone-analysis")

        # ---- crear voz (grabar)
        go(page, "create")
        page.click("#rec-btn")
        page.wait_for_timeout(2500)
        shot(page, "11-grabar")
        page.click("#rec-btn")
        page.wait_for_timeout(1500)

        # ---- texto a voz
        go(page, "tts")
        page.fill("#tts-text", TTS_TEXT)
        page.wait_for_timeout(500)
        shot(page, "12-texto-a-voz")

        # ---- editor
        go(page, "editor")
        with page.expect_file_chooser() as fc:
            page.click('[data-import="editor"]')
        fc.value.set_files(str(clip))
        page.wait_for_selector("#ed-work:not([hidden])", timeout=60000)
        page.wait_for_timeout(1200)
        shot(page, "13-editor")

        # ---- ajustes
        go(page, "settings")
        shot(page, "14-ajustes")
        page.wait_for_selector("#ai-panel .model-row", timeout=15000)
        shot(page, "15-modelos-ia", scroll="#ai-card")
    print("errores de consola:", errors or "ninguno")
    return 0


if __name__ == "__main__":
    sys.exit(main())
