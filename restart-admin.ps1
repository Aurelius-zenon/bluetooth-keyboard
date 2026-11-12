# Elevated restart: kill whatever owns 8888/8889, then start the bridge hidden.
$ErrorActionPreference = 'SilentlyContinue'

$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $dir) { $dir = 'F:\keyboard\bluetooth-keyboard' }

# 1. Kill processes listening on the bridge ports
$owners = @()
foreach ($port in 8888, 8889) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) { if ($owners -notcontains $c.OwningProcess) { $owners += $c.OwningProcess } }
}
# 2. Also kill any stray bridge processes
$procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*bridge.py*' }
foreach ($p in $procs) { if ($owners -notcontains $p.ProcessId) { $owners += $p.ProcessId } }

foreach ($id in $owners) { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 900

# 3. Start fresh
$argLine = '"' + $dir + '\bridge.py" --tls'
Start-Process -FilePath 'pythonw.exe' -ArgumentList $argLine -WorkingDirectory $dir -WindowStyle Hidden
