# Ejecuta el .exe (ventana, sin consola) con un tiempo máximo. Si no termina:
# captura la pantalla (por si hay un cuadro de error), muestra los registros y lo cierra.
param(
    [Parameter(Mandatory)] [string] $Exe,
    [string[]] $Arguments = @(),
    [int] $TimeoutSec = 180,
    [string] $DataDir = "$PWD\exe-datos",
    [string] $Shot = "$PWD\captura.png"
)
$ErrorActionPreference = 'Stop'
$env:VOICELAB_DATA_DIR = $DataDir
$p = Start-Process -FilePath $Exe -ArgumentList $Arguments -PassThru
$done = $p.WaitForExit($TimeoutSec * 1000)
if (-not $done) {
    Add-Type -AssemblyName System.Windows.Forms, System.Drawing
    $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
    [System.Drawing.Graphics]::FromImage($bmp).CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
    $bmp.Save($Shot)
    Write-Host "No terminó en $TimeoutSec s. Ventanas abiertas:"
    Get-Process | Where-Object { $_.MainWindowTitle } | Format-Table Id, ProcessName, MainWindowTitle -AutoSize | Out-String | Write-Host
    Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -like "*VoiceLab*" } |
        Format-Table ProcessId, ParentProcessId, CommandLine -AutoSize | Out-String -Width 400 | Write-Host
    # Texto de las ventanas de la app (p. ej. un cuadro de error), leído con UI Automation.
    try {
        Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
        $ids = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -like "*VoiceLab*" } | ForEach-Object { [int]$_.ProcessId })
        $root = [System.Windows.Automation.AutomationElement]::RootElement
        $wins = $root.FindAll([System.Windows.Automation.TreeScope]::Children, [System.Windows.Automation.Condition]::TrueCondition)
        foreach ($w in $wins) {
            if ($ids -contains $w.Current.ProcessId) {
                Write-Host "=== Ventana: '$($w.Current.Name)' (pid $($w.Current.ProcessId))"
                $all = $w.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
                foreach ($e in $all) { if ($e.Current.Name) { Write-Host ("   " + $e.Current.Name) } }
            }
        }
    } catch { Write-Host "UI Automation no disponible: $_" }
}
foreach ($f in Get-ChildItem "$DataDir\logs" -File -ErrorAction SilentlyContinue) {
    Write-Host "----- $($f.Name)"
    Get-Content $f.FullName -Tail 80 | Write-Host
}
if (-not $done) {
    Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -like "*VoiceLab*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    exit 124
}
Write-Host "Código de salida: $($p.ExitCode)"
exit $p.ExitCode
