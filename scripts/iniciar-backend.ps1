# Sobe backend JARVIS de forma DURAVEL no Windows, SEM janela CMD visivel.
param(
    [switch]$Foreground
)

$ErrorActionPreference = "Continue"
$Root = Split-Path $PSScriptRoot -Parent
$Backend = Join-Path $Root "backend"
. (Join-Path $PSScriptRoot "get-jarvis-python.ps1")

$LogDir = Join-Path $Root "logs"
$PidFile = Join-Path $LogDir "backend.pid"
$LogOut = Join-Path $LogDir "backend.out.log"
$LogErr = Join-Path $LogDir "backend.err.log"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$py = Get-JarvisPython
if (-not (Test-JarvisPythonReady $py)) {
    Write-Host "Python do JARVIS ausente/incompleto - reparando venv..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "ensure-jarvis-venv.ps1")
    . (Join-Path $PSScriptRoot "get-jarvis-python.ps1")
    $py = Get-JarvisPython
}
if (-not (Test-JarvisPythonReady $py)) {
    Write-Host "ERRO: venv JARVIS sem uvicorn/httpx/fastapi. Rode scripts\ensure-jarvis-venv.ps1"
    exit 1
}

# Garante voice-clone-app (XTTS Thomas) na :8787 — sem janela.
try {
    $cloneUp = $false
    try {
        $r = Invoke-RestMethod "http://127.0.0.1:8787/status" -TimeoutSec 2
        $cloneUp = ($r.ok -eq $true)
    } catch {}
    if (-not $cloneUp) {
        $cloneDir = Join-Path $Root "voice-clone-app"
        $cloneServer = Join-Path $cloneDir "server.py"
        if (Test-Path $cloneServer) {
            $clonePy = Join-Path $cloneDir ".venv\Scripts\python.exe"
            if (-not (Test-Path $clonePy)) { $clonePy = $py }
            $env:COQUI_TOS_AGREED = "1"
            $env:CUDA_VISIBLE_DEVICES = ""
            Start-Process -FilePath $clonePy -ArgumentList @($cloneServer) -WorkingDirectory $cloneDir -WindowStyle Hidden | Out-Null
        }
    }
} catch {}

function Test-BackendLive {
    try {
        $r = Invoke-RestMethod "http://127.0.0.1:8000/health/live" -TimeoutSec 4
        return ($r.ok -eq $true)
    } catch {
        return $false
    }
}

function Get-Port8000Pids {
    $pids = @()
    netstat -aon 2>$null | Select-String ":8000\s+.*LISTENING" | ForEach-Object {
        $parts = ($_.ToString() -replace '\s+', ' ').Trim().Split(' ')
        $id = 0
        if ([int]::TryParse($parts[-1], [ref]$id) -and $id -gt 0) {
            $pids += $id
        }
    }
    return @($pids | Select-Object -Unique)
}

if (Test-BackendLive) {
    $pids = Get-Port8000Pids
    if ($pids -and $pids.Count -gt 0) {
        $pids[0] | Out-File -FilePath $PidFile -Encoding ascii -Force
    }
    Write-Host "Backend ja online"
    exit 0
}

& (Join-Path $PSScriptRoot "kill-jarvis-backend.ps1") | Out-Null
Start-Sleep -Seconds 1

# Carrega .env.local no processo (garante voz Thomas, Ollama, timeouts, etc.)
$envLocal = Join-Path $Root ".env.local"
if (Test-Path $envLocal) {
    Get-Content $envLocal -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or ($line -notmatch "=")) { return }
        $k, $v = $line.Split("=", 2)
        $k = $k.Trim()
        $v = $v.Trim().Trim("'").Trim('"')
        if ($k) { Set-Item -Path "Env:$k" -Value $v }
    }
    Write-Host "env.local carregado"
}

if (-not $env:JARVIS_ALWAYS_ROUTE_AGENTS) { $env:JARVIS_ALWAYS_ROUTE_AGENTS = "1" }
if (-not $env:JARVIS_AGENT_ORCHESTRATOR) { $env:JARVIS_AGENT_ORCHESTRATOR = "1" }
if (-not $env:JARVIS_ORCHESTRATOR_LAZY) { $env:JARVIS_ORCHESTRATOR_LAZY = "0" }
$env:PYTHONUNBUFFERED = "1"
if (-not $env:JARVIS_SKIP_XAI) { $env:JARVIS_SKIP_XAI = "0" }
$env:JARVIS_XQUADS_PATH = "C:\Users\Micro\xquads-squads"
$env:JARVIS_AIOS_PATH = "C:\Users\Micro\aios-core"

if ($Foreground) {
    Set-Location $Backend
    & $py -m uvicorn main:app --host 127.0.0.1 --port 8000 --log-level warning
    exit $LASTEXITCODE
}

Write-Host "Subindo backend :8000 (hidden, python=$py)..."

# Wrapper + Win32_Process: sai do Job Object do agente (senao o uvicorn morre com a sessao).
$wrapper = Join-Path $LogDir "run-backend.cmd"
$lines = @(
    "@echo off",
    "cd /d `"$Backend`"",
    "set PYTHONUNBUFFERED=1",
    "set JARVIS_SKIP_XAI=1",
    "set JARVIS_VOICE_PRIMARY=local",
    "set JARVIS_LOCAL_CLONE_PREFER=xtts",
    "set JARVIS_LLM_PROVIDER=ollama"
)
Get-ChildItem Env:JARVIS_* -ErrorAction SilentlyContinue | ForEach-Object {
    $lines += ("set {0}={1}" -f $_.Name, $_.Value)
}
Get-ChildItem Env:ELEVENLABS_* -ErrorAction SilentlyContinue | ForEach-Object {
    $lines += ("set {0}={1}" -f $_.Name, $_.Value)
}
$lines += "`"$py`" -m uvicorn main:app --host 127.0.0.1 --port 8000 --log-level warning >> `"$LogOut`" 2>> `"$LogErr`""
$lines | Set-Content -Path $wrapper -Encoding ASCII

# pythonw morre no boot (uvicorn escreve no console e o processo cai).
# wscript estilo 0 sobe python.exe sem janela e fora do Job Object.
$vbsPath = Join-Path $LogDir "run-backend.vbs"
$vbsLines = @(
    "Set sh = CreateObject(""Wscript.Shell"")",
    "sh.CurrentDirectory = ""$Backend""",
    "sh.Run ""$wrapper"", 0, False"
)
$vbsLines | Set-Content -Path $vbsPath -Encoding ASCII
$proc = $null
try {
    $created = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine      = "wscript.exe //B //nologo `"$vbsPath`""
        CurrentDirectory = $Backend
    }
    if ($created -and $created.ProcessId) {
        $created.ProcessId | Out-File -FilePath $PidFile -Encoding ascii -Force
        Write-Host ("uvicorn pid=" + $created.ProcessId)
    }
} catch {
    Write-Host ("WMI falhou, Start-Process hidden: " + $_)
    $proc = Start-Process -FilePath $pyw -ArgumentList @(
        "-m", "uvicorn", "main:app",
        "--host", "127.0.0.1",
        "--port", "8000",
        "--log-level", "warning"
    ) -WorkingDirectory $Backend -WindowStyle Hidden -PassThru
    if ($proc -and $proc.Id) {
        $proc.Id | Out-File -FilePath $PidFile -Encoding ascii -Force
        Write-Host ("uvicorn pid=" + $proc.Id)
    }
}

$deadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $deadline) {
    if (Test-BackendLive) {
        $pids = Get-Port8000Pids
        if ($pids -and $pids.Count -gt 0) {
            $pids[0] | Out-File -FilePath $PidFile -Encoding ascii -Force
        }
        try {
            $r = Invoke-RestMethod "http://127.0.0.1:8000/health/live" -TimeoutSec 5
            Write-Host ("Backend OK - build=" + $r.build + " provider=" + $r.provider)
        } catch {
            Write-Host "Backend OK"
        }
        exit 0
    }
    if ($proc -and $proc.HasExited) {
        Start-Sleep -Seconds 1
        if (Test-BackendLive) {
            Write-Host "Backend OK (processo filho)"
            exit 0
        }
        Write-Host "Processo morreu - tentando wrapper hidden com log..."
        $wrapper = Join-Path $LogDir "run-backend.cmd"
        @(
            "@echo off",
            "cd /d `"$Backend`"",
            "`"$py`" -m uvicorn main:app --host 127.0.0.1 --port 8000 --log-level warning >> `"$LogOut`" 2>> `"$LogErr`""
        ) | Set-Content -Path $wrapper -Encoding ASCII
        $proc = Start-Process -FilePath $wrapper -WorkingDirectory $Backend -WindowStyle Hidden -PassThru
    }
    Start-Sleep -Seconds 2
}

Write-Host "ERRO: backend nao respondeu em /health/live"
if (Test-Path $LogErr) {
    Get-Content $LogErr -Tail 25 -ErrorAction SilentlyContinue
}
exit 1
