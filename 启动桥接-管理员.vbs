' Launch the bridge with administrator rights (UAC prompt, then fully silent).
Option Explicit

Dim fso, dir, ps
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
ps = dir & "\start-admin.ps1"

If Not fso.FileExists(ps) Then
    MsgBox "start-admin.ps1 not found next to this script.", 48, "Touch Keyboard"
    WScript.Quit 1
End If

' "runas" triggers the UAC prompt; window style 0 keeps everything hidden
CreateObject("Shell.Application").ShellExecute _
    "powershell.exe", _
    "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & ps & """", _
    dir, "runas", 0
