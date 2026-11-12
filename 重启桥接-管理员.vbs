' Restart the bridge with admin rights (kills old instances first).
Option Explicit

Dim fso, dir, ps
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
ps = dir & "\restart-admin.ps1"

If Not fso.FileExists(ps) Then
    MsgBox "restart-admin.ps1 not found next to this script.", 48, "Touch Keyboard"
    WScript.Quit 1
End If

CreateObject("Shell.Application").ShellExecute _
    "powershell.exe", _
    "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & ps & """", _
    dir, "runas", 0
