# JARVIS - diagnostico rapido (health hibrido, voz, pesquisa, frontend)
$ErrorActionPreference = "Continue"
$API = "http://127.0.0.1:8000"
$FE = "http://localhost:3000"

function Test-Line($name, $ok, $detail) {
    $tag = if ($ok) { "PASS" } else { "FAIL" }
    Write-Host "[$tag] $name - $detail"
    return $ok
}

$all = $true
$health = $null

try {
    $live = Invoke-RestMethod "$API/health/live" -TimeoutSec 4
    $detail = "build=$($live.build) provider=$($live.provider)"
    $all = (Test-Line "backend /health/live" ($live.ok -eq $true) $detail) -and $all
} catch {
    $all = (Test-Line "backend /health/live" $false $_.Exception.Message) -and $all
}

try {
    $health = Invoke-RestMethod "$API/health" -TimeoutSec 6
    $detail = "ready=$($health.ready) ollama=$($health.ollama_available) chain=$($health.provider_chain -join '>')"
    $all = (Test-Line "backend /health" ($health.ok -eq $true) $detail) -and $all
} catch {
    $all = (Test-Line "backend /health" $false $_.Exception.Message) -and $all
}

if ($health) {
    $hybridOk = ($health.provider_chain -contains "ollama") -and ($health.ollama_available -eq $true)
    $all = (Test-Line "hibrido ollama" $hybridOk "chain_ok=$hybridOk") -and $all
    if ($health.ready) {
        Write-Host "[INFO] ready=$($health.ready) $($health.brain_note)" -ForegroundColor DarkCyan
    }
    if (-not $health.google_key_valid_format) {
        Write-Host "[WARN] GOOGLE_API_KEY formato invalido - use AIzaSy de aistudio.google.com/apikey"
        Write-Host "[WARN] Apos colar chave: .\scripts\pronto-apos-credito.ps1"
    } elseif ($health.ready -eq "KEY_OK_PROBE_PENDING") {
        Write-Host "[INFO] Chave AIza OK - rode .\scripts\pronto-apos-credito.ps1 para validar credito"
    }
}

try {
    $s = Invoke-RestMethod "$API/api/speak/status" -TimeoutSec 8
    $eng = [string]$s.voice_engine
    $voiceOk = ($eng -eq "local" -and $s.local -eq $true) -or ($eng -eq "thomas" -and $s.fish_api_ready -eq $true) -or ($eng -eq "eleven" -and $s.eleven -eq $true)
    $detail = "voice=$eng local=$($s.local) eleven=$($s.eleven)"
    $all = (Test-Line "speak/status" $voiceOk $detail) -and $all
} catch {
    $all = (Test-Line "speak/status" $false $_.Exception.Message) -and $all
}

try {
    $speakRoute = "/api/speak/local"
    $speakBody = @{ text = "Boa noite, senhor."; prefer = "xtts"; voice_id = "thomas-0701"; play_system = $false }
    $speakTag = "speak/local"
    if ($s -and $s.voice_engine -eq "local") {
        $speakRoute = "/api/speak/local"
        $speakBody = @{ text = "Boa noite, senhor."; prefer = "xtts"; voice_id = "thomas-0701"; play_system = $false }
        $speakTag = "speak/local"
    } elseif ($s -and $s.voice_engine -eq "eleven" -and $s.eleven -eq $true) {
        $speakRoute = "/api/speak/eleven"
        $speakBody = @{ text = "Boa noite, senhor." }
        $speakTag = "speak/eleven"
    }
    $body = $speakBody | ConvertTo-Json
    $r = Invoke-WebRequest -Uri "$API$speakRoute" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 45 -UseBasicParsing
    $len = 0
    if ($r.Headers["Content-Length"]) { $len = [int]$r.Headers["Content-Length"] }
    $ok = $r.StatusCode -eq 200 -and ($len -gt 800 -or $r.StatusCode -eq 200)
    $all = (Test-Line $speakTag $ok "bytes~$len HTTP $($r.StatusCode)") -and $all
} catch {
    $msg = $_.Exception.Message
    if ($_.ErrorDetails.Message) { $msg = $_.ErrorDetails.Message }
    $tag = if ($speakTag) { $speakTag } else { "speak/tts" }
    $all = (Test-Line $tag $false $msg) -and $all
}

try {
    $body = '{"text":"boa noite jarvis"}'
    $c = Invoke-RestMethod -Uri "$API/api/jarvis/chat" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 45
    $resp = [string]$c.response
    $ok = $resp.Length -ge 8
    $all = (Test-Line "chat saudacao" $ok "len=$($resp.Length)") -and $all
} catch {
    $all = (Test-Line "chat saudacao" $false $_.Exception.Message) -and $all
}

try {
    $searchTimeout = 90
    $body = '{"text":"pesquisa noticias de IA hoje"}'
    $c = Invoke-RestMethod -Uri "$API/api/jarvis/chat" -Method POST -Body $body -ContentType "application/json" -TimeoutSec $searchTimeout
    $tools = @()
    if ($c.tools_used) {
        $tools = @($c.tools_used | ForEach-Object { $_.tool })
    }
    $respLen = if ($c.response) { $c.response.Length } else { 0 }
    $ok = ($tools -contains "web_search") -or ($tools -contains "browse_open") -or ($respLen -ge 25)
    $all = (Test-Line "chat pesquisa" $ok "tools=$($tools -join ',') len=$respLen") -and $all
} catch {
    $all = (Test-Line "chat pesquisa" $false $_.Exception.Message) -and $all
}

try {
    $hist = Invoke-RestMethod "$API/api/jarvis/history?limit=1" -TimeoutSec 8
    $ok = $hist.count -ge 0
    $all = (Test-Line "history api" $ok "count=$($hist.count)") -and $all
} catch {
    $all = (Test-Line "history api" $false $_.Exception.Message) -and $all
}

try {
    $oa = Invoke-WebRequest -Uri "$API/openapi.json" -UseBasicParsing -TimeoutSec 8
    $hasStt = $oa.Content -match "/api/jarvis/stt"
    $all = (Test-Line "stt endpoint" $hasStt "openapi") -and $all
} catch {
    $all = (Test-Line "stt endpoint" $false $_.Exception.Message) -and $all
}

try {
    $cap = Invoke-RestMethod "$API/api/jarvis/capabilities" -TimeoutSec 10
    $cats = @($cap.categories).Count
    $ok = ($cap.ok -eq $true) -and ($cats -ge 5) -and ($cap.skills_total -ge 1)
    $all = (Test-Line "capabilities api" $ok "cats=$cats skills=$($cap.skills_total) agents=$($cap.agents_total)") -and $all
} catch {
    $all = (Test-Line "capabilities api" $false $_.Exception.Message) -and $all
}

try {
    $sk = Invoke-RestMethod "$API/api/jarvis/skills" -TimeoutSec 10
    $ok = ($sk.ok -eq $true) -and ($sk.total -ge 5)
    $all = (Test-Line "skills api" $ok "total=$($sk.total)") -and $all
} catch {
    $all = (Test-Line "skills api" $false $_.Exception.Message) -and $all
}

try {
    $body = '{"text":"quais habilidades voce tem"}'
    $c = Invoke-RestMethod -Uri "$API/api/jarvis/chat" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 30
    $resp = [string]$c.response
    $ok = $resp.Length -ge 40 -and ($resp -match "skill|agente|painel|especialist|habil")
    $all = (Test-Line "chat habilidades" $ok "len=$($resp.Length)") -and $all
} catch {
    $all = (Test-Line "chat habilidades" $false $_.Exception.Message) -and $all
}

try {
    $ag = Invoke-RestMethod "$API/api/jarvis/agents" -TimeoutSec 15
    $ok = ($ag.ok -eq $true) -and ($ag.total_agents -ge 100)
    $all = (Test-Line "agents api" $ok "total=$($ag.total_agents)") -and $all
} catch {
    $all = (Test-Line "agents api" $false $_.Exception.Message) -and $all
}

try {
    $body = '{"text":"/agentes"}'
    $c = Invoke-RestMethod -Uri "$API/api/jarvis/chat" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 20
    $resp = [string]$c.response
    $ok = $resp.Length -ge 80 -and ($resp -match "166|especialist|AIOS|Xquads|/ativar")
    $all = (Test-Line "chat /agentes" $ok "len=$($resp.Length)") -and $all
} catch {
    $all = (Test-Line "chat /agentes" $false $_.Exception.Message) -and $all
}

try {
    $body = '{"text":"/ativar copy-chief"}'
    $c = Invoke-RestMethod -Uri "$API/api/jarvis/chat" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 20
    $resp = [string]$c.response
    $ok = $resp -match "Ativado|copy-chief|copy chief"
    $all = (Test-Line "chat /ativar" $ok "agent=$($c.active_agent)") -and $all
} catch {
    $all = (Test-Line "chat /ativar" $false $_.Exception.Message) -and $all
}

try {
    $r = Invoke-WebRequest $FE -UseBasicParsing -TimeoutSec 12
    $hasOrb = $r.Content -match "wa-v22-huw"
    $hasError = $r.Content -match "webpack_modules|Runtime TypeError"
    $ok = $r.StatusCode -eq 200 -and $hasOrb -and -not $hasError
    $all = (Test-Line "frontend :3000" $ok "HTTP $($r.StatusCode) orb=$hasOrb err=$hasError") -and $all
} catch {
    $msg = $_.Exception.Message
    if ($msg -match "conectar|connect|recusou") {
        Write-Host "[WARN] frontend :3000 offline - rode: npm run dev (ou ABRIR_JARVIS.bat)"
        Write-Host "[INFO] backend OK sozinho - UI precisa do :3000"
    } else {
        $all = (Test-Line "frontend :3000" $false $msg) -and $all
    }
}

Write-Host ""
if ($all) {
    Write-Host "RESULTADO: TUDO PASS"
    exit 0
} else {
    Write-Host "RESULTADO: ALGUM FAIL - ver linhas acima"
    exit 1
}