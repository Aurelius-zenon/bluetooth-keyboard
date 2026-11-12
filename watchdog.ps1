# Watchdog: keeps the bridge process alive.
$ErrorActionPreference = 'SilentlyContinue'

$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $dir) { $dir = 'F:\keyboard\bluetooth-keyboard' }
$argLine = '"' + $dir + '\bridge.py" --tls'

while ($true) {
    $alive = Get-CimInstance Win32_Process |
        Where-Object { $_.Name -eq 'pythonw.exe' -and $_.CommandLine -like '*bridge.py*' }
    if (-not $alive) {
        Start-Process -FilePath 'pythonw.exe' -ArgumentList $argLine -WorkingDirectory $dir -WindowStyle Hidden
        Start-Sleep -Seconds 3
    }
    Start-Sleep -Seconds 15
}
