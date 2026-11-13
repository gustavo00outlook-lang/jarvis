# Aguarda backend :8000/health e frontend :3000 com UI pronta (orb).
param(
    [int]$TimeoutSec = 120
)

$ErrorActionPreference = "SilentlyContinue"
$deadline = (Get-Date).AddSeconds($TimeoutSec)
$lastMsg = ""

function Test-JarvisHealth {
    $be = $false
    $fe = $false
    $feReady = $false
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health/live" -TimeoutSec 4
        $be = $r.ok -eq $true
    } catch {}
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:3000" -UseBasicParsing -TimeoutSec 8
        $fe = $r.StatusCode -ge 200 -and $r.StatusCode -lt 500
        if ($fe -and $r.Content) {
            $feReady = $r.Content -match "wa-v22-huw" -and $r.Content -notmatch "webpack_modules|Runtime TypeError"
        }
    } catch {}
    return @{
        ok = ($be -and $feReady)
        backend = $be
        frontend = $fe
        ui = $feReady
    }
}

while ((Get-Date) -lt $deadline) {
    $h = Test-JarvisHealth
    if ($h.ok) {
        Write-Host "OK: backend + frontend + orb prontos."
        exit 0
    }
    $msg = "aguardando"
    if (-not $h.backend) { $msg = "backend :8000" }
    elseif (-not $h.frontend) { $msg = "frontend :3000 (compilando...)" }
    elseif (-not $h.ui) { $msg = "frontend :3000 (UI ainda carregando...)" }
    if ($msg -ne $lastMsg) {
        $elapsed = [int]((Get-Date) - ($deadline.AddSeconds(-$TimeoutSec))).TotalSeconds
        Write-Host "  [$elapsed s] $msg"
        $lastMsg = $msg
    }
    Start-Sleep -Seconds 2
}

Write-Host "ERRO: health check timeout (${TimeoutSec}s) - backend/frontend nao ficaram prontos."
exit 1