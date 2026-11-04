@echo off
setlocal
title Instalar VoiceLab AI
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\install.ps1"
if errorlevel 1 (
  echo.
  echo La instalacion no se ha completado. Revisa los mensajes de arriba.
)
echo.
pause
