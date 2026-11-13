# Mata processos na porta 8000 (uvicorn/dev_server + workers). Retry agressivo no Windows.
$ErrorActionPreference = "SilentlyContinue"

function Get-Port8000Pids {
    $pids = New-Object System.Collections.Generic.HashSet[int]
    netstat -aon | Select-String ":8000\s+.*LISTENING" | ForEach-Object {
        $parts = ($_.ToString() -replace '\s+', ' ').Trim().Split(' ')
        $id = 0
        if ([int]::TryParse($parts[-1], [ref]$id) -and $id -gt 0) {
            [void]$pids.Add($id)
        }
    }
    Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.OwningProcess -gt 0) { [void]$pids.Add([int]$_.OwningProcess) }
    }
    return @($pids)
}

function Stop-Tree([int]$ProcId) {
    if ($ProcId -le 0) { return }
    & taskkill /F /PID $ProcId /T 2>$null | Out-Null
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcId" -ErrorAction SilentlyContinue | ForEach-Object {
        Stop-Tree $_.ProcessId
    }
    Stop-Process -Id $ProcId -Force -ErrorAction SilentlyContinue
}

$maxRounds = 6
for ($round = 1; $round -le $maxRounds; $round++) {
    $pids = Get-Port8000Pids
    if (-not $pids -or $pids.Count -eq 0) {
        Write-Host "Porta 8000 livre."
        exit 0
    }
    foreach ($procId in $pids) {
        Write-Host "Encerrando PID $procId (porta 8000, tentativa $round)..."
        Stop-Tree $procId
    }
    Start-Sleep -Seconds 2
}

$left = Get-Port8000Pids
if ($left -and $left.Count -gt 0) {
    Write-Host "AVISO: ainda ha listener em 8000 (PIDs: $($left -join ', '))"
    exit 1
}
Write-Host "Porta 8000 livre."
exit 0