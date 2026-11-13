"""Fast-paths do agente JARVIS - comandos diretos sem LLM (Ollama-safe)."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional

Broadcast = Callable[[Dict[str, Any]], Awaitable[None]]
BroadcastTool = Callable[[Broadcast, str, Dict[str, Any]], Awaitable[str]]

_SECURITY_AUDIT_RE = re.compile(
    r"\b(?:audita|auditar|audit(?:ar)?|verifica(?:r)?)\b.*\b(?:seguran[cç]a|chaves?|secrets?|projeto|credenciais)\b",
    re.I,
)
_VAULT_REVIEW_RE = re.compile(
    r"\b(?:revis[aã]o|review)\b.*\b(?:semanal|vault|obsidian)\b",
    re.I,
)
_VAULT_CLEANUP_RE = re.compile(
    r"\b(?:limpa|limpar|cleanup|varre)\b.*\b(?:vault|obsidian|notas?)\b",
    re.I,
)

_DIAS_SEMANA = (
    "segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
    "sexta-feira", "sábado", "domingo",
)
_MESES = (
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)

_HOUR_ASK_RE = re.compile(
    r"\bque\s+horas?\b"
    r"|\bqual\s+(?:é\s+|e\s+)?(?:a\s+)?hora\b"
    r"|\bhor[áa]rio\s+(?:atual|agora|de\s+agora)\b"
    r"|\bme\s+d(?:iz|iga)\s+as?\s+horas?\b",
    re.I,
)
_WEEKDAY_ASK_RE = re.compile(
    r"\bdia\s+da\s+semana\b|\bhoje\s+é\s+que\s+dia\b|\bque\s+dia\s+cai\s+hoje\b",
    re.I,
)
_DATE_ASK_RE = re.compile(
    r"\bque\s+dia\s+(?:é\s+|e\s+)?hoje\b"
    r"|\bdata\s+de\s+hoje\b"
    r"|\bqual\s+(?:é\s+|e\s+)?a\s+data\b"
    r"|\b(?:em\s+)?que\s+dia\s+estamos\b"
    r"|\bhoje\s+é\s+dia\b",
    re.I,
)
# "que horas começa o jogo" pergunta sobre um EVENTO — não é hora atual.
_DT_EVENT_GUARD_RE = re.compile(
    r"\b(?:jogo|partida|filme|s[ée]rie|reuni[ãa]o|voo|evento|show|consulta|prova|aula|"
    r"come[cç]a|estreia|termina|acaba|encerra|feriado|anivers[áa]rio)\b",
    re.I,
)

_PC_STATUS_RE = re.compile(
    r"\b(?:status|situa[çc][ãa]o|sa[úu]de)\s+d[oa]\s+(?:meu\s+)?(?:pc|computador|sistema|m[áa]quina|notebook)\b"
    r"|\bcomo\s+(?:est[áa]|t[áa]|anda)\s+(?:o\s+|a\s+)?(?:meu\s+|minha\s+)?(?:pc|computador|sistema|m[áa]quina|notebook)\b"
    r"|\b(?:uso|n[íi]vel|quanto)\s+(?:de\s+|da\s+|do\s+)?(?:ram|cpu|mem[óo]ria|disco|bateria)\b"
    r"|\bminha\s+bateria\b|\bn[íi]vel\s+da\s+bateria\b|\bquanta\s+(?:ram|mem[óo]ria)\b",
    re.I,
)
# "quanto de ram esse programa precisa" fala de requisito, não do estado do PC.
_PC_GUARD_RE = re.compile(
    r"\b(?:jogo|programa|app|aplicativo|chrome|precisa|necessari[oa]|necess[áa]ri[oa]|"
    r"requisitos?|recomendad[oa])\b",
    re.I,
)

_SELF_STATUS_RE = re.compile(
    r"\b(?:status|situa[çc][ãa]o|diagn[óo]stico)\s+(?:do\s+)?(?:jarvis|seus?\s+sistemas?)\b"
    r"|\bseu\s+status\b"
    r"|\bcomo\s+(?:você|voce|vc)\s+est[áa]\s+funcionando\b"
    r"|\b(?:tudo|sistemas?)\s+(?:funcionando|operacional|operacionais|online)\b"
    r"|\bauto[- ]?diagn[óo]stico\b"
    r"|\b(?:sua\s+)?voz\s+(?:est[áa]\s+)?ativa\b"
    r"|\bquantas?\s+skills\b|\bquantos?\s+agentes\b",
    re.I,
)


async def try_datetime_info(
    user_text: str,
    broadcast: Broadcast,
    broadcast_tool: BroadcastTool,
) -> Optional[Dict[str, Any]]:
    """Hora/data/dia da semana pt-BR — 100% offline, sem LLM."""
    raw = (user_text or "").strip()
    if not raw or _DT_EVENT_GUARD_RE.search(raw):
        return None
    wants_hour = bool(_HOUR_ASK_RE.search(raw))
    wants_weekday = bool(_WEEKDAY_ASK_RE.search(raw))
    wants_date = bool(_DATE_ASK_RE.search(raw))
    if not (wants_hour or wants_weekday or wants_date):
        return None

    now = datetime.now()
    dia = _DIAS_SEMANA[now.weekday()]
    data_txt = f"{dia}, {now.day} de {_MESES[now.month - 1]} de {now.year}"
    hh = f"{now.hour}h{now.minute:02d}"
    hora_txt = f"É {hh}" if now.hour == 1 else f"São {hh}"

    if wants_hour and (wants_date or wants_weekday):
        response = f"Hoje é {data_txt}, e agora {hora_txt[0].lower()}{hora_txt[1:]}, senhor."
    elif wants_hour:
        response = f"{hora_txt}, senhor."
    elif wants_date:
        response = f"Hoje é {data_txt}, senhor."
    else:
        response = f"Hoje é {dia}, senhor."

    fb = await broadcast_tool(broadcast, "current_datetime", {})
    return {
        "response": response,
        "tools_used": [{"tool": "current_datetime", "result": str(fb)[:200]}],
    }


async def try_pc_status(
    user_text: str,
    broadcast: Broadcast,
    broadcast_tool: BroadcastTool,
) -> Optional[Dict[str, Any]]:
    """RAM/CPU/disco/bateria reais via actions.system_status — sem LLM."""
    raw = (user_text or "").strip()
    if not raw or not _PC_STATUS_RE.search(raw) or _PC_GUARD_RE.search(raw):
        return None

    fb = str(await broadcast_tool(broadcast, "system_status", {}))
    low = raw.lower()
    focus = None
    if "bateria" in low:
        focus = "Bateria"
    elif re.search(r"\bram\b|mem[óo]ria", low):
        focus = "RAM"
    elif "cpu" in low:
        focus = "CPU"
    elif "disco" in low:
        focus = "Disco"

    response = f"Status do sistema, senhor. {fb}"
    if focus:
        m = re.search(rf"{focus}: [^.]+", fb)
        if m:
            response = f"{m.group(0)}, senhor."
    return {
        "response": response[:420],
        "tools_used": [{"tool": "system_status", "result": fb[:200]}],
    }


def _collect_self_status() -> str:
    parts: List[str] = []
    try:
        from xai_client import get_last_used_provider, get_model, get_provider

        prov = get_last_used_provider() or get_provider()
        parts.append(f"cérebro {prov} com modelo {get_model()}")
    except Exception:
        pass
    try:
        from voice_prefs import get_voice_config

        vc = get_voice_config()
        engine = vc.get("engine") or vc.get("voice_id") or ""
        if engine:
            parts.append(f"voz {engine} ativa")
    except Exception:
        pass
    try:
        from jarvis_skills_registry import load_skills

        n = len(load_skills())
        if n:
            parts.append(f"{n} skills carregadas")
    except Exception:
        pass
    try:
        from agent_orchestrator import get_orchestrator

        total = get_orchestrator().status_dict().get("total_agents", 0)
        if total:
            parts.append(f"{total} agentes especialistas prontos")
    except Exception:
        pass
    if not parts:
        return "Todos os sistemas essenciais operacionais, senhor. Backend de pé e respondendo."
    return (
        "Todos os sistemas operacionais, senhor: "
        + ", ".join(parts)
        + ". Backend respondendo normalmente."
    )


async def try_jarvis_status(user_text: str) -> Optional[Dict[str, Any]]:
    """Auto-diagnóstico do próprio JARVIS (cérebro, voz, skills, agentes) — sem LLM."""
    raw = (user_text or "").strip()
    if not raw or not _SELF_STATUS_RE.search(raw):
        return None
    if _PC_STATUS_RE.search(raw):
        return None
    response = await asyncio.to_thread(_collect_self_status)
    return {"response": response, "tools_used": []}


async def try_security_audit(
    user_text: str,
    broadcast: Broadcast,
    broadcast_tool: BroadcastTool,
) -> Optional[Dict[str, Any]]:
    raw = (user_text or "").strip()
    if not raw or not _SECURITY_AUDIT_RE.search(raw):
        return None
    result = str(await broadcast_tool(broadcast, "security_audit", {}))
    return {
        "response": result,
        "tools_used": [{"tool": "security_audit", "result": result[:240]}],
    }


async def try_vault_ops(
    user_text: str,
    broadcast: Broadcast,
    broadcast_tool: BroadcastTool,
) -> Optional[Dict[str, Any]]:
    raw = (user_text or "").strip()
    if not raw:
        return None
    if _VAULT_REVIEW_RE.search(raw):
        result = str(await broadcast_tool(broadcast, "weekly_vault_review", {}))
        return {
            "response": result,
            "tools_used": [{"tool": "weekly_vault_review", "result": result[:240]}],
        }
    if _VAULT_CLEANUP_RE.search(raw):
        result = str(await broadcast_tool(broadcast, "vault_cleanup", {}))
        return {
            "response": result,
            "tools_used": [{"tool": "vault_cleanup", "result": result[:240]}],
        }
    return None
