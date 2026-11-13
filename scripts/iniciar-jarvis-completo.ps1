# Um clique: clone Thomas + backend + frontend + UMA janela Edge.
# Nao mata o clone se ja estiver no ar. Som do PC ligado (JARVIS_PLAY_SYSTEM=1).
param(
    [switch]$NoBrowser
)

$ErrorActionPreference = "Continue"
$Root = Split-Path $PSScriptRoot -Parent
$env:JARVIS_PLAY_SYSTEM = "1"
$env:JARVIS_VOICE_PRIMARY = "local"
$env:JARVIS_LOCAL_CLONE_PREFER = "xtts"
$env:JARVIS_LLM_PROVIDER = "ollama"
$env:JARVIS_SKIP_XAI = "1"

function Test-Url {
    param([string]$Url, [int]$TimeoutSec = 4)
    try {
        $r = Invoke-WebRequest $Url -UseBasicParsing -TimeoutSec $TimeoutSec
        return ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500)
    } catch {
        return $false
    }
}

function Wait-Url {
    param([string]$Url, [int]$TimeoutSec, [string]$Label)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-Url -Url $Url -TimeoutSec 4) {
            Write-Host "OK $Label"
            return $true
        }
        Start-Sleep -Seconds 2
    }
    Write-Host "TIMEOUT $Label ($Url)"
    return $false
}

function Get-EdgeExe {
    $pf86 = ${env:ProgramFiles(x86)}
    $cands = @(
        (Join-Path $pf86 "Microsoft\Edge\Application\msedge.exe"),
        (Join-Path $env:ProgramFiles "Microsoft\Edge\Application\msedge.exe")
    )
    foreach ($p in $cands) {
        if (Test-Path $p) { return $p }
    }
    return "msedge"
}

Write-Host "============================================================"
Write-Host "  JARVIS - subir tudo (clone + cerebro + orbe + 1 janela)"
Write-Host "============================================================"

if (Test-Url -Url "http://127.0.0.1:8787/status" -TimeoutSec 3) {
    Write-Host "[1/4] Clone :8787 ja no ar"
} else {
    Write-Host "[1/4] Subindo clone Thomas master.wav :8787..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "iniciar-voice-clone.ps1")
    if (-not (Wait-Url -Url "http://127.0.0.1:8787/status" -TimeoutSec 90 -Label "clone :8787")) {
        Write-Host "AVISO: clone ainda aquecendo. A voz pode demorar no 1o audio."
    }
}

if (Test-Url -Url "http://127.0.0.1:8000/health/live" -TimeoutSec 3) {
    Write-Host "[2/4] Backend :8000 ja no ar"
} else {
    Write-Host "[2/4] Subindo backend :8000..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "iniciar-backend.ps1")
    if (-not (Wait-Url -Url "http://127.0.0.1:8000/health/live" -TimeoutSec 90 -Label "backend :8000")) {
        Write-Host "ERRO: backend nao subiu. Veja logs\backend.err.log"
        exit 1
    }
}

if (Test-Url -Url "http://127.0.0.1:3000" -TimeoutSec 4) {
    Write-Host "[3/4] Frontend :3000 ja no ar"
} else {
    Write-Host "[3/4] Subindo frontend :3000..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "iniciar-frontend.ps1") -Stable
    if (-not (Wait-Url -Url "http://127.0.0.1:3000" -TimeoutSec 90 -Label "frontend :3000")) {
        Write-Host "ERRO: frontend nao subiu. Veja logs\frontend-start.err.log"
        exit 1
    }
}

try {
    schtasks /Run /TN "JARVIS-Watchdog-Every5Min" | Out-Null
} catch {}

if (-not $NoBrowser) {
    Write-Host "[4/4] Uma janela so - fechando JARVIS antigo no Edge..."
    Get-Process -Name msedge -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowTitle -like "*J.A.R.V.I.S*" } |
        ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 600
    $edge = Get-EdgeExe
    $url = "http://127.0.0.1:3000"
    Start-Process -FilePath $edge -ArgumentList @(
        "--app=$url",
        "--new-window",
        "--start-maximized",
        "--autoplay-policy=no-user-gesture-required"
    )
    Write-Host "Aberto: $url"
}

Write-Host ""
Write-Host "Pronto. Clique em Digite..., escreva ola, Enter."
Write-Host "Texto sai na hora. Voz Thomas (master.wav) demora no CPU."
exit 0
