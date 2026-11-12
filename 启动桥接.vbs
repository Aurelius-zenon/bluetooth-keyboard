' Silent launcher for the touch-keyboard bridge.
' Double-click: starts bridge.py with --tls in the background (no console window).
Option Explicit

Dim fso, sh, dir, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")

dir = fso.GetParentFolderName(WScript.ScriptFullName)

If Not fso.FileExists(dir & "\bridge.py") Then
    MsgBox "bridge.py not found next to this script.", 48, "Touch Keyboard"
    WScript.Quit 1
End If

On Error Resume Next
cmd = "pythonw.exe """ & dir & "\bridge.py"" --tls"
sh.CurrentDirectory = dir
sh.Run cmd, 0, False
If Err.Number <> 0 Then
    Err.Clear
    cmd = "python.exe """ & dir & "\bridge.py"" --tls"
    sh.Run cmd, 0, False
End If
If Err.Number <> 0 Then
    MsgBox "Python not found. Install Python or add it to PATH.", 48, "Touch Keyboard"
End If
On Error Goto 0
