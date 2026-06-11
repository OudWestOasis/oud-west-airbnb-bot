' Start run_laptop.ps1 volledig vensterloos (geen flikkerend scherm).
' Wordt elke minuut door de Taakplanner aangeroepen via wscript.exe.
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = dir
' 0 = verborgen venster, False = niet wachten
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & dir & "\run_laptop.ps1""", 0, False
