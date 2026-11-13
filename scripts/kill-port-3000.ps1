$ErrorActionPreference = "SilentlyContinue"
$listeners = netstat -aon | Select-String ":3000\s+.*LISTENING"
foreach ($line in $listeners) {
    $parts = ($line -replace '\s+', ' ').ToString().Trim().Split(' ')
    $procId = [int]$parts[-1]
    Write-Host "Encerrando PID $procId (porta 3000)..."
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2
$left = netstat -aon | Select-String ":3000\s+.*LISTENING"
if ($left) { Write-Host "AVISO: ainda ha listener em 3000"; exit 1 }
Write-Host "Porta 3000 livre."
exit 0