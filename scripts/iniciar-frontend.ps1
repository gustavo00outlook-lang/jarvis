# Sobe frontend JARVIS - modo estavel (next start) desacoplado.
param(
    [switch]$Stable,
    [switch]$Foreground,
    [switch]$Dev
)

$ErrorActionPreference = "Continue"
$Root = Split-Path $PSScriptRoot -Parent
$LogDir = Join-Path $Root "logs"
$LogOut = Join-Path $LogDir "frontend-uvicorn.out.log"
# keep name stable for ops
$LogOut = Join-Path $LogDir "frontend-start.out.log"
$LogErr = Join-Path $LogDir "frontend-start.err.log"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $Root

function Test-Frontend {
    try {
        $r = Invoke-WebRequest "http://127.0.0.1:3000" -UseBasicParsing -TimeoutSec 5
        return ($r.StatusCode -ge 200)
    } catch {
        return $false
    }
}

if (Test-Frontend) {
    Write-Host "Frontend ja online em :3000"
    exit 0
}

# Libera 3000 se zumbi
Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 1

$useStable = $Stable -or (-not $Dev)
if ($useStable) {
    $buildId = Join-Path $Root ".next\BUILD_ID"
    if (-not (Test-Path $buildId)) {
        Write-Host "Build ausente - compilando..."
        npm run build
        if ($LASTEXITCODE -ne 0) {
            Write-Host "ERRO: npm run build falhou."
            exit 1
        }
    }
    $cmd = "npm run start"
    Write-Host "Subindo frontend :3000 (modo estavel - next start)..."
} else {
    $cmd = "npm run dev"
    Write-Host "Subindo frontend :3000 (modo dev)..."
}

if ($Foreground) {
    Invoke-Expression $cmd
    exit $LASTEXITCODE
}

# Next via node.exe CreateNoWindow — sem cmd.exe.
$node = Join-Path $env:ProgramFiles "nodejs\node.exe"
if (-not (Test-Path $node)) { $node = "node" }
$nextJs = Join-Path $Root "node_modules\next\dist\bin\next"
$nextArgs = if ($Dev) { "dev" } else { "start" }
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $node
$psi.Arguments = "`"$nextJs`" $nextArgs"
$psi.WorkingDirectory = $Root
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
[void][Diagnostics.Process]::Start($psi)

$deadline = (Get-Date).AddSeconds(90)
do {
    if (Test-Frontend) {
        Write-Host "Frontend OK :3000"
        exit 0
    }
    Start-Sleep -Seconds 2
} while ((Get-Date) -lt $deadline)

Write-Host "ERRO: frontend nao respondeu em :3000"
Get-Content $LogErr -Tail 20 -ErrorAction SilentlyContinue
Get-Content $LogOut -Tail 20 -ErrorAction SilentlyContinue
exit 1
