# REPARAR JARVIS - Windows only (npm install com binarios corretos)
# Uso: REPARAR_JARVIS.bat ou npm run reparar
$ErrorActionPreference = "Continue"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

Write-Host ""
Write-Host "=== JARVIS REPARAR (1 clique) ===" -ForegroundColor Cyan
Write-Host "Maquina: Windows | Pasta: $Root" -ForegroundColor DarkGray
Write-Host ""

# [1] Parar servicos e app
Write-Host "[1/5] Parando backend, frontend e app.exe..." -ForegroundColor Yellow
& "$Root\scripts\kill-jarvis-backend.ps1" 2>$null | Out-Null
Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Stop-Process -Name "app" -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

# [2] Limpar cache Next corrompido
Write-Host "[2/5] Limpando cache .next..." -ForegroundColor Yellow
if (Test-Path "$Root\.next") {
    Remove-Item -Recurse -Force "$Root\.next"
    Write-Host "    .next removido."
} else {
    Write-Host "    .next ja limpo."
}

# [3] Reinstalar dependencias (Next + todo o projeto) — SO Windows local
Write-Host "[3/5] npm install (reinstala Next e deps - aguarde)..." -ForegroundColor Yellow
npm install --legacy-peer-deps
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "ERRO: npm install falhou (codigo $LASTEXITCODE)" -ForegroundColor Red
    exit 1
}
Write-Host "    npm install OK." -ForegroundColor Green

# [4] Verificar Next
Write-Host "[4/5] Verificando Next.js..." -ForegroundColor Yellow
$nextVer = (npm list next --depth=0 2>$null | Select-String "next@")
if ($nextVer) { Write-Host "    $nextVer" } else { Write-Host "    next instalado." }

Write-Host "[5/5] Reparo concluido - pronto para subir o JARVIS." -ForegroundColor Green
Write-Host ""
exit 0