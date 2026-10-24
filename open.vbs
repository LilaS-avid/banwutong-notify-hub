Option Explicit

Dim shell, fileSystem, projectRoot, launcher
Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")

projectRoot = fileSystem.GetParentFolderName(WScript.ScriptFullName)
launcher = fileSystem.BuildPath(projectRoot, "scripts\launcher.ps1")

If Not fileSystem.FileExists(launcher) Then
  MsgBox "Launcher not found: " & launcher, 16, "Banwutong"
  WScript.Quit 1
End If

shell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & launcher & """", 0, False

