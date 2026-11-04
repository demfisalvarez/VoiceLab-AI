#!/bin/sh
# Compila «VoiceLab AI.exe» (desde Linux o Windows con Go ≥ 1.21).
set -e
cd "$(dirname "$0")"
rsrc -ico ../assets/icon.ico -manifest launcher.manifest -arch amd64 -o rsrc_windows_amd64.syso
GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -ldflags "-H=windowsgui -s -w" -o "../VoiceLab AI.exe" .
