# PyInstaller: genera dist\VoiceLab AI\VoiceLab AI.exe (carpeta, arranque rápido).
# Uso en Windows:  pyinstaller build\VoiceLabAI.spec --noconfirm
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [
    ("../voicelab/ui", "voicelab/ui"),
    ("../assets", "assets"),
    # La voz en directo se ejecuta con otro Python (el de PyTorch): necesita los archivos reales.
    ("../voicelab/ai/vendor", "voicelab/ai/vendor"),
    ("../voicelab/ai/meanvc_worker.py", "voicelab/ai"),
]
binaries = []
hidden = collect_submodules("voicelab", filter=lambda name: ".vendor" not in name) + [
    "webview.platforms.edgechromium", "webview.platforms.winforms", "clr_loader", "pythonnet",
    "scipy.signal", "scipy.ndimage", "scipy.fft",
]
for pkg in ("webview", "pythonnet", "clr_loader", "sounddevice", "_sounddevice_data", "imageio_ffmpeg",
            "onnxruntime", "tokenizers"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hidden += h
    except Exception as exc:  # noqa: BLE001
        print("Aviso: no se pudo recoger", pkg, exc)

a = Analysis(["entry.py"], pathex=[".."], binaries=binaries, datas=datas, hiddenimports=hidden,
             excludes=["tkinter", "matplotlib", "torch", "IPython", "pytest"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="VoiceLab AI", icon="../assets/icon.ico",
          console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="VoiceLab AI")
