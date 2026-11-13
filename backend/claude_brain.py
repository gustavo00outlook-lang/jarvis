"""Cérebro Claude — delega tarefas do JARVIS ao Claude Code headless.

Roda o MESMO harness do Claude Code (ferramentas de arquivo, bash, busca,
skills, MCP) via `claude -p --output-format stream-json`, autenticado pela
assinatura do Gustavo — sem chave de API separada.

Fluxo: pedido vira tarefa → JARVIS confirma na hora (turno tem timeout de 88s)
→ subprocess roda em background com progresso no HUD (tool_call/agent_thought)
→ resultado final é falado via broadcast transcript.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

Broadcast = Callable[[Dict[str, Any]], Awaitable[None]]

_REPO_ROOT = Path(__file__).resolve().parents[1]
_KNOWN_EXE = Path(
    str(Path.home() / 'AppData' / 'Roaming' / 'npm' / 'node_modules' / '@anthropic-ai' / 'claude-code' / 'bin' / 'claude.exe')
)
_ENV_FILES = (
    _REPO_ROOT / ".env.local",
    (Path.home() / '.hermes' / '.env'),
)

_busy_lock = threading.Lock()
_busy = False


def _cfg(name: str, default: str = "") -> str:
    """os.environ primeiro; senão .env.local / .hermes/.env (padrão do repo —
    o backend não carrega dotenv)."""
    val = (os.getenv(name) or "").strip()
    if val:
        return val
    for p in _ENV_FILES:
        try:
            m = re.search(
                rf"^{name}\s*=\s*['\"]?([^'\"\r\n]+)", p.read_text(encoding="utf-8"), re.M
            )
            if m:
                return m.group(1).strip()
        except Exception:
            continue
    return default


def _claude_bin() -> Optional[str]:
    env_bin = _cfg("JARVIS_CLAUDE_BIN")
    if env_bin and Path(env_bin).is_file():
        return env_bin
    if _KNOWN_EXE.is_file():
        return str(_KNOWN_EXE)
    found = shutil.which("claude")
    if found and found.lower().endswith(".exe"):
        return found
    return None


def claude_brain_enabled() -> bool:
    if _cfg("JARVIS_CLAUDE_BRAIN", "1") in ("0", "off", "false"):
        return False
    return _claude_bin() is not None


_AUTH_HELP_SPOKEN = (
    "Senhor, o cérebro Claude precisa de re-autenticação. "
    "Abra um terminal, rode claude e use o comando barra login — "
    "depois disso eu executo tarefas sem pedir de novo."
)


def _auth_state() -> str:
    """ok | expirado | desconhecido — baseado no credential store do CLI."""
    if _cfg("JARVIS_CLAUDE_OAUTH_TOKEN"):
        return "ok"
    key = _cfg("JARVIS_CLAUDE_API_KEY")
    if key.startswith("sk-ant-") and "XXXX" not in key:
        return "ok"
    try:
        import time

        cred = json.loads(
            (Path.home() / ".claude" / ".credentials.json").read_text(encoding="utf-8")
        )
        oauth = cred.get("claudeAiOauth") or {}
        exp = float(oauth.get("expiresAt") or 0)
        if exp and exp > time.time() * 1000:
            return "ok"
        if oauth.get("refreshToken"):
            return "ok"
        return "expirado"
    except Exception:
        return "desconhecido"


def _subprocess_env() -> Dict[str, str]:
    env = dict(os.environ)
    # Placeholder sk-ant-XXXXX no ambiente confunde o CLI — remove
    if "XXXX" in (env.get("ANTHROPIC_API_KEY") or ""):
        env.pop("ANTHROPIC_API_KEY", None)
    token = _cfg("JARVIS_CLAUDE_OAUTH_TOKEN")
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    key = _cfg("JARVIS_CLAUDE_API_KEY")
    if key.startswith("sk-ant-") and "XXXX" not in key:
        env["ANTHROPIC_API_KEY"] = key
    return env


_EXPLICIT_RE = re.compile(
    r"(?:^\s*(?:claude|tarefa)\s*[,:]|\bcom\s+o\s+claude\b|\bus[ae]\s+o\s+claude\b|"
    r"\bpede?\s+(?:pro|para\s+o)\s+claude\b|\bc[ée]rebro\s+claude\b)",
    re.I,
)

_TASK_VERB = (
    r"(?:cri[ae]r?|program[ae]r?|desenvolv[ae]r?|refator[ae]r?|implement[ae]r?|"
    r"corrig(?:e|ir|a)|conserta?r?|escrev[ae]r?|ger[ae]r?|edit[ae]r?|"
    r"automatiz[ae]r?|mont[ae]r?|constru(?:a|ir)|faz(?:er)?|fa[çc]a|codifiqu?e|debug[au]?e?)"
)
_TASK_NOUN = (
    r"(?:c[óo]digo|script|arquivo|projeto|site|app|aplicativo|p[áa]gina|bot|api|"
    r"jogo|programa|reposit[óo]rio|componente|fun[çc][ãa]o|endpoint|teste|"
    r"landing\s*page|dashboard|planilha|extens[ãa]o|bug)"
)
_TASK_RE = re.compile(rf"\b{_TASK_VERB}\b[^.!?]{{0,60}}\b{_TASK_NOUN}\b", re.I)

_NOT_TASK_RE = re.compile(
    r"\b(?:que\s+horas|pesquis|google|youtube|m[úu]sica|toca|voz|volume|"
    r"abr[ae]\s+o|navega|assist[ae]|clima|tempo\s+em)\b",
    re.I,
)


def looks_like_claude_task(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 8:
        return False
    if _EXPLICIT_RE.search(t):
        return True
    if _NOT_TASK_RE.search(t):
        return False
    return bool(_TASK_RE.search(t))


def _strip_explicit_prefix(text: str) -> str:
    return re.sub(r"^\s*(?:claude|tarefa)\s*[,:]\s*", "", text, flags=re.I).strip() or text


_SYSTEM_APPEND = (
    "Você é o executor de tarefas do JARVIS, o assistente pessoal do Gustavo. "
    "Trate-o como 'senhor'. Execute a tarefa de forma completa e autônoma. "
    "Responda SEMPRE em português brasileiro. "
    "Sua resposta final será FALADA em voz alta pelo JARVIS: termine com um "
    "resumo claro de 1 a 4 frases do que foi feito e onde está o resultado, "
    "sem markdown, sem listas, sem caminhos longos — linguagem natural de fala."
)


def _build_prompt(task: str) -> str:
    ctx = ""
    try:
        from conversation_state import get_recent_context

        recent = (get_recent_context(4) or "").strip()
        if recent:
            ctx = f"Contexto recente da conversa com o Gustavo:\n{recent}\n\n"
    except Exception:
        pass
    return f"{ctx}Tarefa do Gustavo (via JARVIS, por voz): {task}"


def _spoken_summary(result: str) -> str:
    t = re.sub(r"\s+", " ", (result or "").strip())
    if not t:
        return "Tarefa concluída, senhor."
    if len(t) <= 700:
        return t
    cut = t[:600]
    dot = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if dot > 200:
        cut = cut[: dot + 1]
    return f"{cut} O relatório completo está no histórico, senhor."


async def try_claude_task(user_text: str, broadcast: Broadcast) -> Optional[Dict[str, Any]]:
    """Fast-path: se o pedido é uma tarefa para o cérebro Claude, agenda em
    background e responde na hora (o turno HTTP tem timeout curto)."""
    global _busy
    if not claude_brain_enabled():
        return None
    if not looks_like_claude_task(user_text):
        return None

    with _busy_lock:
        if _busy:
            return {
                "response": (
                    "Senhor, ainda estou executando a tarefa anterior com o cérebro "
                    "Claude. Assim que concluir, aviso e pego a próxima."
                ),
                "tools_used": ["claude_code"],
            }
        _busy = True

    task = _strip_explicit_prefix(user_text)
    loop = asyncio.get_running_loop()
    asyncio.create_task(_run_claude_task(task, broadcast, loop))
    return {
        "response": (
            "Entendido, senhor. Assumindo a tarefa com o cérebro Claude — "
            "acompanhe o progresso na tela; aviso assim que concluir."
        ),
        "tools_used": ["claude_code"],
        "claude_task": True,
    }


async def _run_claude_task(task: str, broadcast: Broadcast, loop: asyncio.AbstractEventLoop) -> None:
    global _busy
    try:
        await broadcast({"type": "agent_suggestion", "id": "claude-code", "name": "Claude Code", "reason": "executor de tarefas"})
        await broadcast({"type": "tool_call", "tool": "claude_code", "status": "running"})
        await broadcast({"type": "state", "state": "thinking"})

        result = await asyncio.get_running_loop().run_in_executor(
            None, _run_claude_subprocess, task, broadcast, loop
        )

        final_text = result.get("text") or ""
        is_error = bool(result.get("is_error"))
        if is_error and not final_text:
            final_text = (
                "Senhor, a tarefa falhou no cérebro Claude — reveja o pedido ou "
                "tente novamente em instantes."
            )
        spoken = _spoken_summary(final_text)

        try:
            from conversation_state import append_message

            append_message("jarvis", final_text or spoken)
        except Exception:
            pass

        await broadcast({"type": "tool_call", "tool": "claude_code", "status": "done"})
        await broadcast({"type": "transcript", "role": "jarvis", "text": spoken})
        await broadcast({"type": "state", "state": "speaking"})
        await asyncio.sleep(min(24.0, 3.0 + len(spoken) / 14.0))
        await broadcast({"type": "agent_suggestion", "id": "", "name": ""})
        await broadcast({"type": "state", "state": "idle"})
    except Exception as e:
        print(f"[claude_brain] tarefa falhou: {type(e).__name__}: {e}")
        try:
            await broadcast({"type": "tool_call", "tool": "claude_code", "status": "done"})
            await broadcast(
                {
                    "type": "transcript",
                    "role": "jarvis",
                    "text": "Senhor, tive um contratempo ao executar a tarefa com o cérebro Claude. Estou online — pode tentar de novo.",
                }
            )
            await broadcast({"type": "state", "state": "speaking"})
            await asyncio.sleep(6.0)
            await broadcast({"type": "state", "state": "idle"})
        except Exception:
            pass
    finally:
        with _busy_lock:
            _busy = False


def _emit(loop: asyncio.AbstractEventLoop, broadcast: Broadcast, payload: Dict[str, Any]) -> None:
    try:
        asyncio.run_coroutine_threadsafe(broadcast(payload), loop)
    except Exception:
        pass


_TOOL_LABEL_PT = {
    "Bash": "executando comando",
    "Read": "lendo arquivo",
    "Write": "escrevendo arquivo",
    "Edit": "editando arquivo",
    "Glob": "procurando arquivos",
    "Grep": "buscando no código",
    "WebSearch": "pesquisando na web",
    "WebFetch": "lendo página web",
    "Task": "delegando a subagente",
    "TodoWrite": "planejando etapas",
}


def _run_claude_subprocess(task: str, broadcast: Broadcast, loop: asyncio.AbstractEventLoop) -> Dict[str, Any]:
    """Roda claude -p em thread (evita depender de suporte a subprocess no
    event loop do Windows). Emite progresso via run_coroutine_threadsafe."""
    exe = _claude_bin()
    if not exe:
        return {"text": "Cérebro Claude indisponível — o Claude Code não foi encontrado neste PC, senhor.", "is_error": True}

    cwd = _cfg("JARVIS_CLAUDE_CWD") or str(_REPO_ROOT)
    mode = _cfg("JARVIS_CLAUDE_PERMISSION_MODE", "bypass").lower()
    timeout_s = max(120.0, float(_cfg("JARVIS_CLAUDE_TIMEOUT_S", "900")))

    args = [
        exe,
        "-p",
        _build_prompt(task),
        "--output-format",
        "stream-json",
        "--verbose",
        "--append-system-prompt",
        _SYSTEM_APPEND,
    ]
    if mode in ("bypass", "bypasspermissions"):
        args.append("--dangerously-skip-permissions")
    else:
        args += ["--permission-mode", mode]
    model = _cfg("JARVIS_CLAUDE_MODEL")
    if model:
        args += ["--model", model]

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(
        args,
        cwd=cwd,
        env=_subprocess_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )

    final_text = ""
    is_error = False
    timer = threading.Timer(timeout_s, proc.kill)
    timer.daemon = True
    timer.start()
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            etype = ev.get("type")
            if etype == "assistant":
                for block in (ev.get("message") or {}).get("content") or []:
                    btype = block.get("type")
                    if btype == "tool_use":
                        name = str(block.get("name") or "")
                        label = _TOOL_LABEL_PT.get(name, name.lower() or "trabalhando")
                        _emit(loop, broadcast, {"type": "caption", "text": f"Claude: {label}…"})
                        _emit(loop, broadcast, {"type": "agent_thought", "text": f"{label}…", "agent": "claude-code"})
                    elif btype == "text":
                        snippet = re.sub(r"\s+", " ", str(block.get("text") or "")).strip()
                        if snippet:
                            _emit(loop, broadcast, {"type": "caption", "text": snippet[:220]})
            elif etype == "result":
                final_text = str(ev.get("result") or "")
                is_error = bool(ev.get("is_error"))
                if is_error and (
                    ev.get("api_error_status") == 401
                    or ("401" in final_text and "authenticate" in final_text.lower())
                ):
                    final_text = _AUTH_HELP_SPOKEN
        proc.wait(timeout=30)
    except Exception as e:
        print(f"[claude_brain] subprocess: {type(e).__name__}: {e}")
        is_error = True
    finally:
        timer.cancel()
        try:
            if proc.poll() is None:
                proc.kill()
        except Exception:
            pass

    if not final_text and proc.returncode not in (0, None):
        err = ""
        try:
            err = (proc.stderr.read() or "")[:300] if proc.stderr else ""
        except Exception:
            pass
        print(f"[claude_brain] exit={proc.returncode} err={err}")
        is_error = True
    return {"text": final_text, "is_error": is_error}


def claude_brain_status() -> Dict[str, Any]:
    exe = _claude_bin()
    return {
        "enabled": claude_brain_enabled(),
        "bin": exe,
        "auth": _auth_state(),
        "cwd": _cfg("JARVIS_CLAUDE_CWD") or str(_REPO_ROOT),
        "permission_mode": _cfg("JARVIS_CLAUDE_PERMISSION_MODE", "bypass"),
        "model": _cfg("JARVIS_CLAUDE_MODEL") or "padrão da conta",
        "busy": _busy,
    }
