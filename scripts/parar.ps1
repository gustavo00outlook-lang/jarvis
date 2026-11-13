# Para todos os servicos JARVIS (backend, frontend, app).
$ErrorActionPreference = "SilentlyContinue"
$Root = Split-Path $PSScriptRoot -Parent

Write-Host "Parando JARVIS..."
& (Join-Path $PSScriptRoot "kill-jarvis-backend.ps1") | Out-Null
Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
& (Join-Path $PSScriptRoot "kill-jarvis-app.ps1") | Out-Null
Start-Sleep -Seconds 2
Write-Host "JARVIS parado."
exit 0