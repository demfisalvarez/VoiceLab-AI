#Requires -Version 5.1
<#
  Desinstalador de VoiceLab AI.
  Se copia a la carpeta temporal antes de borrar la carpeta de instalación.
#>
param([string]$InstallDir)

$ErrorActionPreference = 'Stop'
$AppName = 'VoiceLab AI'
$AppId   = 'VoiceLabAI'

if (-not $InstallDir) {
    $InstallDir = Split-Path -Parent $PSScriptRoot
    # Se relanza desde %TEMP% para poder borrar su propia carpeta.
    $tmp = Join-Path $env:TEMP 'voicelab-uninstall.ps1'
    Copy-Item -Force $PSCommandPath $tmp
    Start-Process powershell.exe -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$tmp`"", '-InstallDir', "`"$InstallDir`"")
    exit 0
}

Write-Host ''
Write-Host "  Desinstalar $AppName" -ForegroundColor White
Write-Host "  Carpeta: $InstallDir"
$ans = Read-Host '  ¿Continuar? [s/N]'
if ($ans -notmatch '^[sSyY]') { Write-Host '  Cancelado.'; Start-Sleep 2; exit 0 }

# Cerrar la app si está abierta
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { ($_.CommandLine -and $_.CommandLine -like '*-m voicelab*') -or
                   ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($InstallDir, [StringComparison]::OrdinalIgnoreCase)) } |
    ForEach-Object { Invoke-CimMethod -InputObject $_ -MethodName Terminate | Out-Null }
Start-Sleep -Seconds 1

foreach ($dir in [Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs')) {
    $lnk = Join-Path $dir "$AppName.lnk"
    if (Test-Path $lnk) { Remove-Item -Force $lnk }
}
Remove-Item -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$AppId" -Recurse -Force -ErrorAction SilentlyContinue

# Comprobación de seguridad: solo se borra una carpeta que contenga la app.
if ((Test-Path (Join-Path $InstallDir 'voicelab\__init__.py')) -and ($InstallDir -like '*VoiceLab AI*')) {
    Remove-Item -Recurse -Force $InstallDir -ErrorAction SilentlyContinue
}

Remove-Item -Recurse -Force (Join-Path $env:TEMP 'voicelab-uv-cache') -ErrorAction SilentlyContinue

$data = Join-Path $env:APPDATA $AppId
if (Test-Path $data) {
    $ans = Read-Host '  ¿Borrar también tus ajustes y perfiles de voz? [s/N]'
    if ($ans -match '^[sSyY]') { Remove-Item -Recurse -Force $data -ErrorAction SilentlyContinue }
    else { Write-Host "  Se conservan en $data" }
}

Write-Host ''
Write-Host "  $AppName se ha desinstalado." -ForegroundColor Green
Write-Host '  VB-CABLE no se toca: si quieres quitarlo, desinstálalo desde su propio instalador.'
Start-Sleep -Seconds 4
