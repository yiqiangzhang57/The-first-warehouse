Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
If fso.FileExists(folder & "\悬浮小助手.exe") Then
    command = """" & folder & "\悬浮小助手.exe"""
Else
    command = "pythonw """ & folder & "\assistant.py"""
End If
shell.Run command, 0, False
