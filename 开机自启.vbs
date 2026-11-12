' Add the bridge to Windows startup (runs silently at login).
Option Explicit

Dim fso, sh, dir, startup, lnk, f, launcher
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")

dir = fso.GetParentFolderName(WScript.ScriptFullName)

' Find the launcher script (any .vbs except this one)
launcher = ""
For Each f In fso.GetFolder(dir).Files
    If LCase(fso.GetExtensionName(f.Name)) = "vbs" Then
        If LCase(f.Name) <> LCase(WScript.ScriptName) Then
            launcher = f.Path
        End If
    End If
Next

If launcher = "" Then
    MsgBox "Launcher .vbs not found in this folder.", 48, "Touch Keyboard"
    WScript.Quit 1
End If

startup = sh.SpecialFolders("Startup")
Set lnk = sh.CreateShortcut(startup & "\TouchKeyboard Bridge.lnk")
lnk.TargetPath = "wscript.exe"
lnk.Arguments = """" & launcher & """"
lnk.WorkingDirectory = dir
lnk.WindowStyle = 7
lnk.Description = "Touch screen keyboard bridge (silent)"
lnk.Save

MsgBox "Done. The bridge will start silently when you log in." & vbCrLf & vbCrLf & _
       "Shortcut: " & startup & "\TouchKeyboard Bridge.lnk", 64, "Touch Keyboard"
