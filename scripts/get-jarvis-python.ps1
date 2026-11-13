# Resolve o Python do JARVIS. Prefere o venv; nunca o 3.14 do PATH.
function Get-JarvisPython {
    $Root = Split-Path $PSScriptRoot -Parent
    $candidates = @(
        (Join-Path $Root ".venv\Scripts\python.exe"),
        "C:\Users\Micro\Documents\Claude\Projects\Jarvis\.venv\Scripts\python.exe",
        "C:\Users\Micro\AppData\Local\Programs\Python\Python313\python.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path -LiteralPath $c) { return $c }
    }
    $py313 = & py -3.13 -c "import sys; print(sys.executable)" 2>$null
    if ($LASTEXITCODE -eq 0 -and $py313) { return $py313.Trim() }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notmatch "WindowsApps|pythoncore-3\.14") {
        return $cmd.Source
    }
    return $null
}

function Get-JarvisSystemPython {
    $official = "C:\Users\Micro\AppData\Local\Programs\Python\Python313\python.exe"
    if (Test-Path -LiteralPath $official) { return $official }
    $py313 = & py -3.13 -c "import sys; print(sys.executable)" 2>$null
    if ($LASTEXITCODE -eq 0 -and $py313) { return $py313.Trim() }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notmatch "WindowsApps|pythoncore-3\.14") {
        return $cmd.Source
    }
    return $null
}

function Test-JarvisPythonReady([string]$PythonExe) {
    if (-not $PythonExe -or -not (Test-Path -LiteralPath $PythonExe)) { return $false }
    & $PythonExe -c "import uvicorn, httpx, fastapi" 2>$null
    return ($LASTEXITCODE -eq 0)
}
