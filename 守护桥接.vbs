' Start the bridge watchdog (silent): restarts the bridge if it dies.
Option Explicit

Dim fso, dir, ps
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
ps = dir & "\watchdog.ps1"

If Not fso.FileExists(ps) Then
    MsgBox "watchdog.ps1 not found next to this script.", 48, "Touch Keyboard"
    WScript.Quit 1
End If

CreateObject("WScript.Shell").Run _
    "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & ps & """", _
    0, False
