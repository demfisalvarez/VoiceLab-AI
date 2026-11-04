#Requires -Version 5.1
<#
  Instalador de VoiceLab AI (Fase 1)
  - Descarga un Python 3.12 privado para la app (con «uv», de Astral) dentro de
    su propia carpeta: no necesita que tengas Python instalado ni lo modifica.
  - Copia la aplicación en %LOCALAPPDATA%\Programs\VoiceLab AI
  - Crea un entorno aislado con sus dependencias.
  - Crea accesos directos (escritorio y menú Inicio) que abren la app sin consola.
  - La registra en «Aplicaciones instaladas» para poder desinstalarla.
  No necesita permisos de administrador.
#>

$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'   # las barras de progreso hacen las descargas 10x más lentas
$AppName  = 'VoiceLab AI'
$AppId    = 'VoiceLabAI'
$Version  = '0.7.0'
$Source   = Split-Path -Parent $PSScriptRoot
$Target   = Join-Path $env:LOCALAPPDATA 'Programs\VoiceLab AI'
$Runtime  = Join-Path $Target 'runtime'
$RPy      = Join-Path $Runtime 'Scripts\python.exe'
$RPyw     = Join-Path $Runtime 'Scripts\pythonw.exe'
$ToolsDir = Join-Path $Target 'bin'
$Uv       = Join-Path $ToolsDir 'uv.exe'
$UvUrls   = @('https://github.com/astral-sh/uv/releases/download/0.13.7/uv-x86_64-pc-windows-msvc.zip',
              'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip')

function Write-Step([string]$t) { Write-Host ''; Write-Host "==> $t" -ForegroundColor Cyan }
function Write-Ok([string]$t)   { Write-Host "    $t" -ForegroundColor Green }
function Write-Warn2([string]$t){ Write-Host "    $t" -ForegroundColor Yellow }
function Fail([string]$t) {
    Write-Host ''
    Write-Host "ERROR: $t" -ForegroundColor Red
    if ($script:Diag.Count) {
        Write-Host ''
        Write-Host '  Detalles para el diagnóstico:' -ForegroundColor Yellow
        $script:Diag | ForEach-Object { Write-Host "   - $_" }
    }
    Write-Host ''
    Write-Host "  Registro completo: $LogFile"
    try { Stop-Transcript | Out-Null } catch { }
    exit 1
}

# Ejecuta un programa externo sin que su salida de error detenga el script.
function Invoke-Native([string]$exe, [string[]]$arguments) {
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $all = & $exe @arguments 2>&1
        $code = $LASTEXITCODE
        $stdout = ($all | Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] } | Out-String).Trim()
        $stderr = ($all | Where-Object { $_ -is [System.Management.Automation.ErrorRecord] } | ForEach-Object { "$_" } | Out-String).Trim()
        return @{ Code = $code; Out = $stdout; Err = $stderr; All = ($stdout + "`n" + $stderr).Trim() }
    } catch {
        return @{ Code = -1; Out = ''; Err = "$_"; All = "$_" }
    } finally { $ErrorActionPreference = $old }
}

# Windows PowerShell 5.1 no escapa las comillas dobles al pasar argumentos a
# otros programas, así que el código de Python nunca se pasa con -c: se escribe
# en un archivo temporal y se ejecuta.
function Invoke-PyCode([string]$exe, [string]$code) {
    $file = Join-Path $env:TEMP ('voicelab-' + [guid]::NewGuid().ToString('N') + '.py')
    [IO.File]::WriteAllText($file, $code, (New-Object System.Text.UTF8Encoding($false)))
    try { return Invoke-Native $exe @('-I', $file) }   # -I: no importa nada de la carpeta temporal
    finally { Remove-Item -Force $file -ErrorAction SilentlyContinue }
}

function Test-PythonExe([string]$exe) {
    if (-not $exe -or -not (Test-Path $exe)) { return $false }
    if ($exe -like '*\WindowsApps\*') { return $false }   # alias de la Microsoft Store, no es Python real
    $r = Invoke-PyCode $exe 'import sys, struct; print("%d.%d-%d" % (sys.version_info[0], sys.version_info[1], struct.calcsize("P") * 8))'
    if ($r.Code -ne 0) { $script:Diag += "Python no válido: $exe -> $($r.All)"; return $false }
    if (@('3.10-64', '3.11-64', '3.12-64', '3.13-64') -contains $r.Out.Trim()) { return $true }
    $script:Diag += "Versión no compatible: $exe -> $($r.Out.Trim())"
    return $false
}

# Python ya instalado en el sistema (solo como plan B si falla la descarga).
function Find-SystemPython {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in '3.12', '3.11', '3.13', '3.10') {
            $r = Invoke-Native 'py' @("-$v", '-c', 'import sys; print(sys.executable)')   # sin comillas: seguro
            if ($r.Code -eq 0 -and (Test-PythonExe $r.Out.Trim())) { return $r.Out.Trim() }
        }
    }
    foreach ($c in @("$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
                     "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
                     "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
                     "$env:ProgramFiles\Python312\python.exe")) {
        if (Test-PythonExe $c) { return $c }
    }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and (Test-PythonExe $cmd.Source)) { return $cmd.Source }
    return $null
}

function Get-Uv {
    if (Test-Path $Uv) { return $true }
    try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch { }
    New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null
    $zip = Join-Path $env:TEMP 'voicelab-uv.zip'
    $tmp = Join-Path $env:TEMP 'voicelab-uv'
    foreach ($url in $UvUrls) {
        try {
            Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
            if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
            Expand-Archive -Path $zip -DestinationPath $tmp -Force
            $exe = Get-ChildItem -Path $tmp -Recurse -Filter 'uv.exe' | Select-Object -First 1
            if ($exe) {
                Copy-Item -Force $exe.FullName $Uv
                Remove-Item -Force $zip -ErrorAction SilentlyContinue
                Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
                return $true
            }
        } catch {
            Write-Warn2 "No se pudo descargar desde $url ($($_.Exception.Message))"
            $script:Diag += "Descarga de uv: $url -> $($_.Exception.Message)"
        }
    }
    return $false
}

$script:Diag = @()
$LogFile = Join-Path $env:TEMP 'voicelab-install.log'
try { Start-Transcript -Path $LogFile -Force | Out-Null } catch { }

Write-Host ''
Write-Host "  $AppName $Version — instalación" -ForegroundColor White
Write-Host "  PowerShell $($PSVersionTable.PSVersion) · $([Environment]::OSVersion.VersionString)"
Write-Host '  ---------------------------------------------'

# ------------------------------------------------- 1. Cerrar la app si está abierta
$running = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { ($_.CommandLine -and $_.CommandLine -like '*-m voicelab*') -or
                   ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($Target, [StringComparison]::OrdinalIgnoreCase)) }
if ($running) {
    Write-Step "Cerrando $AppName para actualizarlo"
    $running | ForEach-Object { Invoke-CimMethod -InputObject $_ -MethodName Terminate | Out-Null }
    Start-Sleep -Seconds 1
}

# --------------------------------------------------------------- 2. Archivos
Write-Step "Copiando la aplicación en $Target"
New-Item -ItemType Directory -Force -Path $Target | Out-Null
if ((Resolve-Path $Source).Path.TrimEnd('\') -ne (Resolve-Path $Target).Path.TrimEnd('\')) {
    foreach ($dir in 'voicelab', 'assets', 'installer') {
        $dst = Join-Path $Target $dir
        if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
        Copy-Item -Recurse -Force (Join-Path $Source $dir) $dst
    }
    foreach ($f in 'requirements.txt', 'README.md', 'ARQUITECTURA.md', 'VoiceLab AI.exe') {
        if (Test-Path (Join-Path $Source $f)) { Copy-Item -Force (Join-Path $Source $f) $Target }
    }
    foreach ($dir in 'voicelab', 'assets', 'installer') {
        Get-ChildItem -Path (Join-Path $Target $dir) -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
    }
}
Write-Ok 'Archivos copiados'

# ------------------------------------------------- 3. Python privado + dependencias
Write-Step 'Preparando Python y las dependencias (la primera vez descarga ~60 MB y tarda 1–3 minutos)'
$requirements = Join-Path $Target 'requirements.txt'
$ready = Test-PythonExe $RPy
$depsDone = $false

if (-not $ready -and (Get-Uv)) {
    Write-Ok 'Gestor de Python «uv» listo'
    # Todo queda dentro de la carpeta de la app: se borra al desinstalar.
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $Target 'python'
    $env:UV_CACHE_DIR          = Join-Path $env:TEMP 'voicelab-uv-cache'
    $env:UV_PYTHON_PREFERENCE  = 'only-managed'
    if (Test-Path $Runtime) { Remove-Item -Recurse -Force $Runtime }
    $r = Invoke-Native $Uv @('venv', '--no-config', '--python', '3.12', $Runtime)
    if ($r.Code -ne 0) { Write-Warn2 'uv no pudo crear el entorno de Python.'; $script:Diag += "uv venv -> $($r.All)" }
    $ready = Test-PythonExe $RPy
    if ($ready) {
        Write-Ok 'Python 3.12 privado instalado'
        $r = Invoke-Native $Uv @('pip', 'install', '--no-config', '--python', $RPy, '-r', $requirements)
        if ($r.Code -ne 0) { Fail "No se pudieron instalar las dependencias. ¿Hay conexión a Internet?`n$($r.All)" }
        $depsDone = $true
    }
}

if (-not $ready) {
    # Plan B: un Python 3.10–3.13 de 64 bits ya instalado en el sistema.
    $Py = Find-SystemPython
    if (-not $Py) {
        Fail ("No se pudo descargar Python automáticamente y no hay un Python 3.10–3.13 de 64 bits instalado.`n" +
              "       Comprueba la conexión a Internet (y que el antivirus no bloquee github.com) y vuelve a intentarlo,`n" +
              "       o instala Python 3.12 de 64 bits desde https://www.python.org/downloads/windows/")
    }
    Write-Warn2 "Usando el Python del sistema: $Py"
    if (Test-Path $Runtime) { Remove-Item -Recurse -Force $Runtime }
    $r = Invoke-Native $Py @('-m', 'venv', $Runtime)
    if ($r.Code -ne 0 -or -not (Test-PythonExe $RPy)) { Fail "No se pudo crear el entorno de Python:`n$($r.All)" }
    $r = Invoke-Native $RPy @('-m', 'pip', 'install', '--disable-pip-version-check', '-r', $requirements)
    if ($r.Code -ne 0) { Fail "No se pudieron instalar las dependencias. ¿Hay conexión a Internet?`n$($r.All)" }
} elseif (-not $depsDone) {
    # Reinstalación/actualización: el entorno ya existe; se ponen al día las dependencias.
    if (Test-Path $Uv) {
        $env:UV_CACHE_DIR = Join-Path $env:TEMP 'voicelab-uv-cache'
        $r = Invoke-Native $Uv @('pip', 'install', '--no-config', '--python', $RPy, '-r', $requirements)
    } else {
        $r = Invoke-Native $RPy @('-m', 'pip', 'install', '--disable-pip-version-check', '-r', $requirements)
    }
    if ($r.Code -ne 0) { Fail "No se pudieron instalar las dependencias. ¿Hay conexión a Internet?`n$($r.All)" }
}
Write-Ok 'Dependencias instaladas'

# El paquete se registra en el entorno para poder lanzarlo desde cualquier carpeta.
$site = (Invoke-PyCode $RPy 'import sysconfig; print(sysconfig.get_paths()["purelib"])').Out.Trim()
if (-not $site -or -not (Test-Path $site)) { $site = Join-Path $Runtime 'Lib\site-packages' }
[IO.File]::WriteAllText((Join-Path $site 'voicelab.pth'), $Target + "`r`n", (New-Object System.Text.UTF8Encoding($false)))

$check = Invoke-PyCode $RPy 'import voicelab, sounddevice; print("VoiceLab", voicelab.__version__, "-", sounddevice.get_portaudio_version()[1])'
if ($check.Code -ne 0) { Fail "La comprobación final ha fallado:`n$($check.All)" }
Write-Ok $check.Out
$wv = Invoke-PyCode $RPy 'import webview'
if ($wv.Code -ne 0) { Write-Warn2 'La ventana nativa no está disponible: la app se abrirá en una ventana de Edge.' }
if (-not (Test-Path $RPyw)) { Fail "Falta $RPyw en el entorno de Python." }

# --------------------------------------------------------- 4. Accesos directos
Write-Step 'Creando accesos directos'
$Launcher = Join-Path $Target 'VoiceLab AI.exe'
$shell = New-Object -ComObject WScript.Shell
$links = @()
foreach ($dir in [Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs')) {
    $path = Join-Path $dir "$AppName.lnk"
    $lnk = $shell.CreateShortcut($path)
    if (Test-Path $Launcher) {
        # Lanzador nativo: se abre como cualquier programa, sin consola.
        $lnk.TargetPath   = $Launcher
        $lnk.Arguments    = ''
        $lnk.IconLocation = "$Launcher,0"
    } else {
        $lnk.TargetPath   = $RPyw
        $lnk.Arguments    = '-m voicelab'
        $lnk.IconLocation = (Join-Path $Target 'assets\icon.ico') + ',0'
    }
    $lnk.WorkingDirectory = $Target
    $lnk.Description      = 'Estudio de voz: modulador, clonación y texto a voz'
    $lnk.Save()
    $links += $path
}
# Misma identidad (AppUserModelID) que la ventana: el icono anclado a la barra
# de tareas se ilumina con la app abierta en lugar de duplicarse.
try {
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
[ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IPropertyStore {
    void GetCount(out uint count);
    void GetAt(uint index, out PropertyKey key);
    void GetValue(ref PropertyKey key, out PropVariant value);
    void SetValue(ref PropertyKey key, ref PropVariant value);
    void Commit();
}
[ComImport, Guid("0000010b-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IPersistFile {
    void GetClassID(out Guid classId);
    [PreserveSig] int IsDirty();
    void Load([MarshalAs(UnmanagedType.LPWStr)] string file, uint mode);
    void Save([MarshalAs(UnmanagedType.LPWStr)] string file, [MarshalAs(UnmanagedType.Bool)] bool remember);
    void SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string file);
    void GetCurFile(out IntPtr file);
}
[StructLayout(LayoutKind.Sequential, Pack = 4)]
public struct PropertyKey { public Guid FormatId; public uint PropertyId; }
[StructLayout(LayoutKind.Explicit, Size = 24)]
public struct PropVariant { [FieldOffset(0)] public ushort vt; [FieldOffset(8)] public IntPtr pointer; }
[ComImport, Guid("00021401-0000-0000-C000-000000000046")]
class CShellLink { }
public static class VoiceLabShortcut {
    public static void SetAppId(string lnk, string appId) {
        object link = new CShellLink();
        ((IPersistFile)link).Load(lnk, 2);
        PropertyKey key = new PropertyKey { FormatId = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), PropertyId = 5 };
        PropVariant value = new PropVariant { vt = 31, pointer = Marshal.StringToCoTaskMemUni(appId) };
        try {
            IPropertyStore store = (IPropertyStore)link;
            store.SetValue(ref key, ref value);
            store.Commit();
            ((IPersistFile)link).Save(lnk, true);
        } finally { Marshal.FreeCoTaskMem(value.pointer); }
    }
}
"@ -ErrorAction Stop
    foreach ($l in $links) { [VoiceLabShortcut]::SetAppId($l, 'VoiceLabAI.Studio') }
} catch {
    $script:Diag += "AppUserModelID del acceso directo: $($_.Exception.Message)"
}
Write-Ok 'Escritorio y menú Inicio (se pueden anclar a la barra de tareas)'

# ---------------------------------------------- 5. Aplicaciones instaladas
$key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$AppId"
New-Item -Path $key -Force | Out-Null
$size = [int]((Get-ChildItem $Target -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum / 1KB)
$uninstall = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$Target\installer\uninstall.ps1`""
Set-ItemProperty -Path $key -Name DisplayName     -Value $AppName
Set-ItemProperty -Path $key -Name DisplayVersion  -Value $Version
Set-ItemProperty -Path $key -Name Publisher       -Value 'VoiceLab AI'
Set-ItemProperty -Path $key -Name DisplayIcon     -Value $(if (Test-Path (Join-Path $Target 'VoiceLab AI.exe')) { Join-Path $Target 'VoiceLab AI.exe' } else { Join-Path $Target 'assets\icon.ico' })
Set-ItemProperty -Path $key -Name InstallLocation -Value $Target
Set-ItemProperty -Path $key -Name UninstallString -Value $uninstall
New-ItemProperty -Path $key -Name NoModify      -Value 1 -PropertyType DWord -Force | Out-Null
New-ItemProperty -Path $key -Name NoRepair      -Value 1 -PropertyType DWord -Force | Out-Null
New-ItemProperty -Path $key -Name EstimatedSize -Value $size -PropertyType DWord -Force | Out-Null
Write-Ok 'Registrada en Configuración → Aplicaciones (para desinstalar)'

# ------------------------------------------------------------ 6. VB-CABLE
Write-Step 'Comprobando el micrófono virtual (VB-CABLE)'
$cable = $null
try { $cable = Get-PnpDevice -FriendlyName '*VB-Audio Virtual Cable*' -ErrorAction SilentlyContinue } catch { }
if ($cable) {
    Write-Ok 'VB-CABLE está instalado.'
} else {
    Write-Warn2 'VB-CABLE no está instalado. Sin él, otras apps (Discord, Steam...) no pueden recibir tu voz.'
    Write-Warn2 'Es gratuito y está firmado por Microsoft. Descarga el ZIP, extráelo y ejecuta'
    Write-Warn2 'VBCABLE_Setup_x64.exe como administrador; después reinicia Windows.'
    $ans = Read-Host '    ¿Abrir ahora la página oficial de VB-CABLE? [S/n]'
    if ($ans -notmatch '^[nN]') { Start-Process 'https://vb-audio.com/Cable/' }
}

# -------------------------------------------------------------------- fin
Write-Host ''
Write-Host "  $AppName se ha instalado correctamente." -ForegroundColor Green
Write-Host '  Ábrelo desde el icono del escritorio o desde el menú Inicio.'
$ans = Read-Host '  ¿Abrirlo ahora? [S/n]'
try { Stop-Transcript | Out-Null } catch { }
if ($ans -notmatch '^[nN]') {
    if (Test-Path $Launcher) { Start-Process -FilePath $Launcher -WorkingDirectory $Target }
    else { Start-Process -FilePath $RPyw -ArgumentList '-m', 'voicelab' -WorkingDirectory $Target }
}
exit 0
