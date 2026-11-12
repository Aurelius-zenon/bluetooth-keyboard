# Elevated launcher body: kill previous bridge instances, then start pythonw hidden.
$ErrorActionPreference = 'SilentlyContinue'

$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $dir) { $dir = 'F:\keyboard\bluetooth-keyboard' }

$old = Get-CimInstance Win32_Process |
    Where-Object { $_.Name -eq 'pythonw.exe' -and $_.CommandLine -like '*bridge.py*' }
foreach ($p in $old) { Stop-Process -Id $p.ProcessId -Force }

Start-Sleep -Milliseconds 600

$argLine = '"' + $dir + '\bridge.py" --tls'
Start-Process -FilePath 'pythonw.exe' -ArgumentList $argLine -WorkingDirectory $dir -WindowStyle Hidden
