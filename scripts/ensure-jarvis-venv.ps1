# Cria/repara o .venv do JARVIS com Python 3.13 (oficial) e as deps do backend.
param(
    [switch]$Force
)
$ErrorActionPreference = "Continue"
$Root = Split-Path $PSScriptRoot -Parent
$VenvDir = Join-Path $Root ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$Req = Join-Path $Root "backend\requirements.txt"

. (Join-Path $PSScriptRoot "get-jarvis-python.ps1")

$sys = Get-JarvisSystemPython
if (-not $sys) {
    Write-Host "ERRO: Python 3.13 oficial nao encontrado"
    exit 1
}

$needRecreate = $Force -or -not (Test-Path -LiteralPath $VenvPython)
if (-not $needRecreate) {
    $ver = & $VenvPython -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    if ($ver -ne "3.13") { $needRecreate = $true }
}

if (-not $needRecreate -and (Test-JarvisPythonReady $VenvPython)) {
    Write-Host "venv OK ($ver): $VenvPython"
    exit 0
}

if ($needRecreate) {
    Write-Host "Recriando venv com $sys ..."
    if (Test-Path $VenvDir) {
        $bak = Join-Path $Root (".venv-bak-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
        try {
            Move-Item -LiteralPath $VenvDir -Destination $bak -Force
            Write-Host "venv antigo movido para $bak"
        } catch {
            Write-Host "nao moveu venv antigo (em uso?) - tentando reusar"
        }
    }
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        & $sys -m venv $VenvDir
    }
}

if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Host "ERRO: venv nao criado"
    exit 1
}

Write-Host "Instalando dependencias do backend..."
& $VenvPython -m pip install -U pip setuptools wheel
$packages = @(
    "-r", $Req,
    "python-dotenv",
    "websockets",
    "python-multipart",
    "pydantic",
    "numpy"
)
& $VenvPython -m pip install @packages
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERRO: pip install falhou"
    exit 1
}

if (-not (Test-JarvisPythonReady $VenvPython)) {
    Write-Host "ERRO: venv ainda sem uvicorn/httpx/fastapi"
    exit 1
}

Write-Host "venv pronto: $VenvPython"
& $VenvPython -c "import sys; print(sys.version)"
exit 0
