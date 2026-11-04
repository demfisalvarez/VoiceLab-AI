# PyInstaller: genera dist\VoiceLab AI\VoiceLab AI.exe (carpeta, arranque rápido).
# Uso en Windows (desde la raíz del proyecto):  pyinstaller build\VoiceLabAI.spec --noconfirm
import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # noqa: F821 - SPECPATH lo define PyInstaller
import sys  # noqa: E402

sys.path.insert(0, ROOT)          # para que collect_submodules encuentre el paquete «voicelab»


def r(*p):
    return os.path.join(ROOT, *p)


datas = [
    (r("voicelab", "ui"), "voicelab/ui"),
    (r("assets"), "assets"),
    # La voz en directo se ejecuta con otro Python (el de PyTorch): necesita los archivos reales.
    (r("voicelab", "ai", "vendor"), "voicelab/ai/vendor"),
    (r("voicelab", "ai", "meanvc_worker.py"), "voicelab/ai"),
]
binaries = []
hidden = collect_submodules("voicelab", filter=lambda name: ".vendor" not in name) + [
    "webview.platforms.edgechromium", "webview.platforms.winforms", "clr_loader", "pythonnet",
    "scipy.signal", "scipy.ndimage", "scipy.fft",
]
print("Módulos de VoiceLab:", len([h for h in hidden if h.startswith("voicelab")]))
for pkg in ("webview", "pythonnet", "clr_loader", "sounddevice", "_sounddevice_data", "imageio_ffmpeg",
            "onnxruntime", "tokenizers"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hidden += h
    except Exception as exc:  # noqa: BLE001
        print("Aviso: no se pudo recoger", pkg, exc)

a = Analysis([r("build", "entry.py")], pathex=[ROOT], binaries=binaries, datas=datas, hiddenimports=hidden,
             excludes=["tkinter", "matplotlib", "torch", "IPython", "pytest", "onnxruntime.quantization",
                       "onnxruntime.transformers", "webview.platforms.android"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="VoiceLab AI", icon=r("assets", "icon.ico"),
          console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="VoiceLab AI")
