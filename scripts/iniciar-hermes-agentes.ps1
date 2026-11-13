# Abre Hermes Gateway + warmup hermes3 + agentes AIOS/Xquads numa CMD visivel.
$ErrorActionPreference = "Continue"
$HermesHome = Join-Path $env:LOCALAPPDATA "hermes"
$HermesAgent = Join-Path $HermesHome "hermes-agent"
$HermesPy = Join-Path $HermesAgent "venv\Scripts\python.exe"
$JarvisRoot = Split-Path $PSScriptRoot -Parent
$JarvisPy = Join-Path $JarvisRoot ".venv\Scripts\python.exe"
$Backend = Join-Path $JarvisRoot "backend"
$LogDir = Join-Path $JarvisRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

Write-Host "=== [1/4] Encerrando gateway Hermes oculto (vamos abrir visivel) ==="
Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and ($_.CommandLine -match "hermes_cli.main gateway run")
} | ForEach-Object {
    Write-Host "  kill PID $($_.ProcessId)"
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 1

Write-Host "=== [2/4] Warmup Ollama hermes3 ==="
try {
    $body = @{
        model = "hermes3"
        prompt = "ok"
        stream = $false
        keep_alive = "24h"
        options = @{ num_ctx = 4096; num_predict = 8 }
    } | ConvertTo-Json -Depth 5
    Invoke-RestMethod "http://127.0.0.1:11434/api/generate" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 180 | Out-Null
    Write-Host "  OK hermes3 em memoria"
} catch {
    Write-Host "  WARN warmup: $($_.Exception.Message)"
}

Write-Host "=== [3/4] Carregando 166 agentes AIOS+Xquads ==="
try {
    $env:PYTHONPATH = $Backend
    if (-not $env:JARVIS_XQUADS_PATH) { $env:JARVIS_XQUADS_PATH = Join-Path $env:USERPROFILE "xquads-squads" }
    if (-not $env:JARVIS_AIOS_PATH) { $env:JARVIS_AIOS_PATH = Join-Path $env:USERPROFILE "aios-core" }
    & $JarvisPy -c "from agent_orchestrator import get_orchestrator; o=get_orchestrator(); o.ensure_loaded(); print('  OK', len(o._agents), 'agentes')"
} catch {
    Write-Host "  WARN agentes: $($_.Exception.Message)"
}

Write-Host "=== [4/4] Hermes gateway hidden (sem CMD) ==="
$HermesPyw = Join-Path $HermesAgent "venv\Scripts\pythonw.exe"
if (-not (Test-Path $HermesPyw)) { $HermesPyw = $HermesPy }
Start-Process -FilePath $HermesPyw -ArgumentList @("-m", "hermes_cli.main", "gateway", "run") -WorkingDirectory $HermesHome -WindowStyle Hidden | Out-Null
Write-Host "Hermes gateway hidden"
exit 0
