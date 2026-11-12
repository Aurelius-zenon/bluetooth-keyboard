# Watchdog: keeps the bridge process alive.
# Single instance + backoff. A bridge that had been healthy is restarted immediately
# (e.g. manual kill); only repeated startup failures (port taken) back off exponentially.
$ErrorActionPreference = 'SilentlyContinue'

$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $dir) { $dir = 'F:\keyboard\bluetooth-keyboard' }
$argLine = '"' + $dir + '\bridge.py" --tls'

# Only one watchdog may run; the .vbs launchers can be double-clicked.
$mutex = New-Object System.Threading.Mutex($false, 'Global\TouchKeyboardBridgeWatchdog')
if (-not $mutex.WaitOne(0)) { exit }

function Get-Bridge {
    @(Get-CimInstance Win32_Process |
        Where-Object { $_.Name -eq 'pythonw.exe' -and $_.CommandLine -like '*bridge.py*' })
}

$backoff = 10
$healthy = $false

while ($true) {
    $alive = Get-Bridge
    if ($alive.Count -gt 0) {
        $healthy = $true
        Start-Sleep -Seconds 10
        continue
    }

    # Was running fine until now (manual kill / crash after a long run): no penalty.
    if ($healthy) { $backoff = 10; $healthy = $false }

    Start-Process -FilePath 'pythonw.exe' -ArgumentList $argLine -WorkingDirectory $dir -WindowStyle Hidden
    Start-Sleep -Seconds 12

    if ((Get-Bridge).Count -eq 0) {
        $backoff = [Math]::Min(300, $backoff * 2)
        Start-Sleep -Seconds $backoff
    } else {
        $healthy = $true
        Start-Sleep -Seconds 10
    }
}
