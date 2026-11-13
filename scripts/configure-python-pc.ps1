# Reaplica Python 3.13.15 como padrao do Windows (PATH + py launcher).
$ErrorActionPreference = "Continue"
$pyDir = "C:\Users\Micro\AppData\Local\Programs\Python\Python313"
$pyScripts = Join-Path $pyDir "Scripts"
$launcher = "C:\Users\Micro\AppData\Local\Programs\Python\Launcher"
$winApps = Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps"

if (-not (Test-Path (Join-Path $pyDir "python.exe"))) {
    Write-Host "ERRO: Python 3.13 nao instalado em $pyDir"
    exit 1
}

foreach ($stub in @("python.exe","python3.exe","python3.13.exe","python3.14.exe")) {
    $p = Join-Path $winApps $stub
    if (Test-Path $p) { Remove-Item -Force -LiteralPath $p -ErrorAction SilentlyContinue }
}

$userPath = [Environment]::GetEnvironmentVariable("Path","User")
$parts = @($userPath -split ";" | Where-Object { $_ -and $_.Trim() } | ForEach-Object { $_.Trim().TrimEnd("\") })
$priority = @($pyDir, $pyScripts, $launcher)
$skip = @($pyDir, $pyScripts, $launcher, (Join-Path $env:LOCALAPPDATA "Python\bin")) | ForEach-Object { $_.TrimEnd("\").ToLower() }
$rest = $parts | Where-Object {
    $n = $_.TrimEnd("\").ToLower()
    ($skip -notcontains $n) -and ($n -notlike "*\appdata\local\python\bin")
}
$newPath = (@($priority + $rest) | Select-Object -Unique) -join ";"
[Environment]::SetEnvironmentVariable("Path", $newPath, "User")
[Environment]::SetEnvironmentVariable("PYTHONUTF8", "1", "User")
[Environment]::SetEnvironmentVariable("PY_PYTHON", "3.13", "User")

$ini = @"
[defaults]
python=3.13
"@
Set-Content -Path (Join-Path $env:LOCALAPPDATA "py.ini") -Value $ini -Encoding ASCII
Set-Content -Path (Join-Path $launcher "py.ini") -Value $ini -Encoding ASCII -ErrorAction SilentlyContinue

$p3 = Join-Path $pyDir "python3.exe"
if (-not (Test-Path $p3)) {
    cmd /c "mklink `"$p3`" `"$(Join-Path $pyDir 'python.exe')`"" | Out-Null
}

Write-Host "Python padrao: $((& (Join-Path $pyDir 'python.exe') -c 'import sys; print(sys.version.split()[0])'))"
Write-Host "py.ini = 3.13 | PYTHONUTF8=1 | PATH 3.13 na frente"
exit 0
