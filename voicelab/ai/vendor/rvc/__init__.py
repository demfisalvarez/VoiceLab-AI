"""Modelos y pérdidas de RVC v2 (Retrieval-based-Voice-Conversion-WebUI, MIT).

Copia de ``infer/module`` y ``train/{losses,mel_processing}.py`` del commit
81eed5e8f68b6bed1789f682fe78cdd324495afc (agosto de 2026). Cambios de VoiceLab:
importaciones relativas, sin ``scipy`` y banco mel de torchaudio en vez de librosa
(el entorno de PyTorch de la app no los incluye). Licencia: ``LICENSE-MIT.txt``.
"""
