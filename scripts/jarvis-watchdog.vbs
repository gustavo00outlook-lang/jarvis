' Sem janela. Chamado pelo agendador de tarefas.
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("Wscript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
sh.Run "powershell.exe -NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File """ & root & "\jarvis-watchdog.ps1""", 0, False
