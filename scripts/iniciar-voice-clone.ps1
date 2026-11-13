# Sobe o clone Thomas :8787 SEM janela (pythonw).
$ErrorActionPreference = "Continue"
$CloneDir = Join-Path (Split-Path $PSScriptRoot -Parent) "voice-clone-app"
$Pyw = Join-Path $CloneDir ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $Pyw)) { $Pyw = Join-Path $CloneDir ".venv\Scripts\python.exe" }
if (-not (Test-Path $Pyw)) {
    Write-Host "ERRO: venv do clone ausente"
    exit 1
}
$LogDir = Join-Path (Split-Path $CloneDir -Parent) "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$env:COQUI_TOS_AGREED = "1"
$env:CUDA_VISIBLE_DEVICES = ""
Start-Process -FilePath $Pyw -ArgumentList @("`"$CloneDir\server.py`"") -WorkingDirectory $CloneDir -WindowStyle Hidden | Out-Null
Write-Host "Clone Thomas hidden :8787"
exit 0
