# Cria atalho JARVIS na Area de Trabalho (app principal)
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Target = Join-Path $Root "INICIAR-JARVIS.vbs"
$Desktop = [Environment]::GetFolderPath("Desktop")
$LinkPath = Join-Path $Desktop "JARVIS.lnk"
$Icon = Join-Path $Root "public\favicon.ico"

$Wsh = New-Object -ComObject WScript.Shell
$Shortcut = $Wsh.CreateShortcut($LinkPath)
$Shortcut.TargetPath = "wscript.exe"
$Shortcut.Arguments = "//B //nologo `"$Target`""
$Shortcut.WorkingDirectory = $Root
$Shortcut.WindowStyle = 7
$Shortcut.Description = "JARVIS Pro - App Desktop (interface principal)"
if (Test-Path $Icon) { $Shortcut.IconLocation = "$Icon,0" }
$Shortcut.Save()

Write-Host "Atalho criado: $LinkPath"
Write-Host "Alvo: $Target"