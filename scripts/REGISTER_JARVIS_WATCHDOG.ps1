# Registra UM watchdog hidden. Remove duplicatas que abriam CMD a cada poucos minutos.
$ErrorActionPreference = "Continue"
$Root = Split-Path $PSScriptRoot -Parent
$Canonical = Join-Path $PSScriptRoot "jarvis-watchdog.ps1"
$Watchdog = Join-Path $env:USERPROFILE "jarvis-watchdog.ps1"
$TaskBoot = "JARVIS-Watchdog-OnLogon"
$TaskPoll = "JARVIS-Watchdog-Every2Min"
$TaskDupes = @(
    "JARVIS-Watchdog",
    "JARVIS-Watchdog-Every30Min",
    "JARVIS-Watchdog-Every5Min"
)

if (-not (Test-Path $Canonical)) {
    Write-Error "Watchdog canonico ausente: $Canonical"
    exit 1
}
Copy-Item -Force $Canonical $Watchdog
Write-Host "Watchdog sincronizado: $Watchdog"

foreach ($name in $TaskDupes) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    schtasks /Delete /TN $name /F 2>$null | Out-Null
}

Copy-Item -Force (Join-Path $PSScriptRoot "jarvis-watchdog.vbs") (Join-Path $env:USERPROFILE "jarvis-watchdog.vbs")
$vbs = Join-Path $env:USERPROFILE "jarvis-watchdog.vbs"
$tr = "wscript.exe //B //nologo `"$vbs`""

# Sem admin o /Create falha e a tarefa antiga (powershell.exe) continua abrindo janela.
schtasks /Create /TN $TaskBoot /TR $tr /SC ONLOGON /F
if ($LASTEXITCODE -ne 0) { Write-Error "Falha ao registrar $TaskBoot (precisa de admin). CMD pode continuar aparecendo."; exit 1 }
schtasks /Create /TN $TaskPoll /TR $tr /SC MINUTE /MO 2 /F
if ($LASTEXITCODE -ne 0) { Write-Error "Falha ao registrar $TaskPoll (precisa de admin). CMD pode continuar aparecendo."; exit 1 }

foreach ($name in @($TaskBoot, $TaskPoll)) {
    try {
        $t = Get-ScheduledTask -TaskName $name
        $t.Settings.Hidden = $true
        $t.Settings.AllowDemandStart = $true
        $t.Settings.StartWhenAvailable = $true
        $t.Settings.MultipleInstances = "IgnoreNew"
        $t.Settings.ExecutionTimeLimit = "PT8M"
        $t.Settings.DisallowStartIfOnBatteries = $false
        $t.Settings.StopIfGoingOnBatteries = $false
        Set-ScheduledTask -InputObject $t | Out-Null
    } catch {
        Write-Host "aviso: nao deu para marcar $name como Hidden: $_"
    }
}

Write-Host "Tarefas registradas (hidden, sem CMD visivel):"
Write-Host "  $TaskBoot  (logon)"
Write-Host "  $TaskPoll  (cada 2 min)"
Write-Host "Duplicatas removidas: $($TaskDupes -join ', ')"
Write-Host "Log: $env:USERPROFILE\jarvis-watchdog.log"
