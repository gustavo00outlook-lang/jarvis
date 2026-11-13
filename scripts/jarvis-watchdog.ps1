# Blindagem JARVIS — clone + backend + frontend + ollama.
# Roda hidden via schtasks. Nao abre CMD. Nao mata clone saudavel.
$ErrorActionPreference = "SilentlyContinue"
$JarvisRoot = "C:\Users\Micro\Documents\Claude\Projects\Jarvis\jarvis-pro"
$LogFile = Join-Path $env:USERPROFILE "jarvis-watchdog.log"
$Scripts = Join-Path $JarvisRoot "scripts"
$env:JARVIS_PLAY_SYSTEM = "1"
$env:JARVIS_VOICE_PRIMARY = "local"
$env:JARVIS_LOCAL_CLONE_PREFER = "xtts"

function Write-Log([string]$Message) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    try { Add-Content -Path $LogFile -Value $line -Encoding UTF8 } catch {}
}

# powershell.exe e programa de console: chamar com & abre janela.
# CREATE_NO_WINDOW nao cria console.
function Invoke-HiddenScript([string]$File, [string]$ExtraArgs) {
    if (-not (Test-Path $File)) {
        Write-Log "script ausente: $File"
        return
    }
    $arg = "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$File`""
    if ($ExtraArgs) { $arg += " $ExtraArgs" }
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    $psi.Arguments = $arg
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    try {
        $p = [System.Diagnostics.Process]::Start($psi)
        if ($p -and -not $p.WaitForExit(180000)) {
            Write-Log "timeout hidden: $File"
        }
    } catch {
        Write-Log "falha hidden: $File $_"
    }
}

function Test-HttpOk([string]$Url, [int]$Sec = 5) {
    try {
        $r = Invoke-WebRequest $Url -UseBasicParsing -TimeoutSec $Sec
        return ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500)
    } catch { return $false }
}

function Test-BackendLive {
    try {
        $r = Invoke-RestMethod "http://127.0.0.1:8000/health/live" -TimeoutSec 6
        return $r.ok -eq $true
    } catch { return $false }
}

function Get-PortPids([int]$Port) {
    $pids = @()
    netstat -aon | Select-String ":$Port\s+.*LISTENING" | ForEach-Object {
        $parts = ($_.ToString() -replace '\s+', ' ').Trim().Split(' ')
        $id = 0
        if ([int]::TryParse($parts[-1], [ref]$id) -and $id -gt 0) { $pids += $id }
    }
    return @($pids | Select-Object -Unique)
}

$okClone = Test-HttpOk "http://127.0.0.1:8787/status" 4
$okBe = Test-BackendLive
$okFe = Test-HttpOk "http://127.0.0.1:3000" 6
$okOllama = Test-HttpOk "http://127.0.0.1:11434/api/tags" 4

if (-not $okBe -and (Get-PortPids 8000).Count -gt 0) {
    Write-Log "ZUMBI :8000 - matando"
    & (Join-Path $Scripts "kill-jarvis-backend.ps1") | Out-Null
    Start-Sleep -Seconds 2
    $okBe = $false
}

if ($okClone -and $okBe -and $okFe) {
    Write-Log "OK clone=$okClone be=$okBe fe=$okFe ollama=$okOllama"
    exit 0
}

Write-Log "DOWN clone=$okClone be=$okBe fe=$okFe ollama=$okOllama - heal"

if (-not $okOllama) {
    Write-Log "tentando ollama serve"
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden -ErrorAction SilentlyContinue
}

if (-not $okClone) {
    Write-Log "subindo clone :8787"
    Invoke-HiddenScript (Join-Path $Scripts "iniciar-voice-clone.ps1")
}

if (-not $okBe) {
    Write-Log "subindo backend :8000"
    Invoke-HiddenScript (Join-Path $Scripts "iniciar-backend.ps1")
}

if (-not $okFe) {
    Write-Log "subindo frontend :3000"
    Invoke-HiddenScript (Join-Path $Scripts "iniciar-frontend.ps1") "-Stable"
}

$ok2c = Test-HttpOk "http://127.0.0.1:8787/status" 4
$ok2b = Test-BackendLive
$ok2f = Test-HttpOk "http://127.0.0.1:3000" 6
if ($ok2b -and $ok2f) {
    Write-Log "RECUPERADO clone=$ok2c be=$ok2b fe=$ok2f"
    exit 0
}
Write-Log "FALHA heal clone=$ok2c be=$ok2b fe=$ok2f"
exit 1
