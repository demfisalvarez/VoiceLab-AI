@echo off
setlocal
rem Compila VoiceLab AI.exe y el instalador. Requiere Python 3.12 (64 bits) e Inno Setup 6.
cd /d "%~dp0.."
py -3.12 -m venv build\.venv || goto :error
call build\.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt onnxruntime-directml tokenizers pyinstaller || goto :error
pyinstaller build\VoiceLabAI.spec --noconfirm --distpath dist --workpath build\work || goto :error
for /f %%v in ('python -c "import voicelab; print(voicelab.__version__)"') do set VL_VERSION=%%v
"%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" build\installer.iss || goto :error
echo.
echo Listo: dist\VoiceLabAI-Setup-%VL_VERSION%.exe
exit /b 0
:error
echo La compilacion ha fallado.
exit /b 1
