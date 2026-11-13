"""Auditoria JARVIS — o que faz, pedidos do usuário, bloqueios e por quê."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_AUDIT_RE = re.compile(
    r"\b(?:"
    r"o\s+que\s+n[aã]o\s+funciona|"
    r"auditoria\s+jarvis|"
    r"orquestra[cç][aã]o\s+jarvis|"
    r"por\s+que\s+n[aã]o\s+(?:faz|funciona)|"
    r"o\s+que\s+est[aá]\s+quebrado|"
    r"status\s+do\s+jarvis|"
    r"diagn[oó]stico\s+jarvis"
    r")\b",
    re.I,
)

VAULT_PATH = Path(
    os.getenv(
        "JARVIS_OBSIDIAN_VAULT",
        str(Path.home() / "Documents" / "JARVIS-notes" / "reviews" / "ORQUESTRACAO-JARVIS.md"),
    )
)

# Pedidos do Gustavo mapeados na sessão de desenvolvimento
USER_REQUESTS_AUDIT: List[Dict[str, str]] = [
    {
        "id": "ui_no_user_box",
        "pedido": "Só texto JARVIS, sem quadrado do usuário",
        "status": "ok",
        "motivo": "JarvisUserEcho só dispara eventos; sem card do usuário na UI.",
    },
    {
        "id": "ui_text_fade",
        "pedido": "Texto some alguns segundos após o JARVIS falar",
        "status": "ok",
        "motivo": "Fade via jarvis:tts-end → jarvis:text-fade (~4,5s).",
    },
    {
        "id": "ui_no_border",
        "pedido": "Remover contorno/caixa em volta da escrita",
        "status": "ok",
        "motivo": "Removido jarvis-reply-card; só jarvis-reply-text limpo.",
    },
    {
        "id": "voice_capcut",
        "pedido": "Voz CapCut 02-07 (Thomas)",
        "status": "parcial",
        "motivo": "Fish Audio clona por similaridade; xAI custom voice bloqueado na conta.",
    },
    {
        "id": "anim_google",
        "pedido": "Animação Google: painel esquerda, orb direita; centro no chat normal",
        "status": "ok",
        "motivo": "Orb só vai à direita com browserActive; esquerda só confirmação; centro em conversa.",
    },
    {
        "id": "seq_google_yt",
        "pedido": "Comandos sequenciais (Google depois YouTube)",
        "status": "ok",
        "motivo": "intent_resolver compound + site_early em jarvis_agent.",
    },
    {
        "id": "smart_search",
        "pedido": "Pesquisa inteligente (não literal)",
        "status": "parcial",
        "motivo": "query_intelligence.py; LLM pode falhar/timeout se xAI lento.",
    },
    {
        "id": "youtube_cowatch",
        "pedido": "YouTube: assistir, clicar, argumentar",
        "status": "parcial",
        "motivo": "Playwright headless + preview; app Tauri pode usar screenshot em vez de browser real.",
    },
    {
        "id": "agents_orchestrate",
        "pedido": "Agentes/skills orquestrarem tudo automaticamente",
        "status": "ok",
        "motivo": "166 agentes Xquads+AIOS + 13 squad activations + 61 skills; always-route; knowledge body + persona densa por turno.",
    },
    {
        "id": "ruflo_bridge",
        "pedido": "Ruflo dev/swarm auto quando JARVIS detectar tarefa de código",
        "status": "parcial",
        "motivo": "jarvis_ruflo_bridge.py injeta bloco swarm; install-ruflo-jarvis.ps1; ativa sem mencionar ao usuário.",
    },
    {
        "id": "google_gemini",
        "pedido": "Pesquisa Google grounding / Gemini",
        "status": "parcial",
        "motivo": "Cérebro atual = Ollama hermes3 (JARVIS_LLM_PROVIDER=ollama). Pesquisa web grátis DDG+Wiki+painel Google ativa. Gemini quando renovar cota (provider=auto).",
    },
    {
        "id": "launcher_stable",
        "pedido": "Abrir JARVIS sem cair",
        "status": "ok",
        "motivo": "scripts/iniciar-backend.ps1 processo independente + watchdog; frontend :3000 + backend :8000.",
    },
]


def wants_orchestration_report(text: str) -> bool:
    return bool(_AUDIT_RE.search((text or "").strip()))


async def _live_health() -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    try:
        import httpx

        async with httpx.AsyncClient(timeout=6.0) as c:
            h = await c.get("http://127.0.0.1:8000/health")
            if h.status_code == 200:
                out["health"] = h.json()
    except Exception as e:
        out["health_error"] = str(e)[:200]
    try:
        from fish_tts import fish_configured, get_jarvis_reference_id, get_fish_wallet_status
        from voice_prefs import get_voice_config

        wallet = await get_fish_wallet_status()
        vcfg = get_voice_config()
        out["voice"] = {
            "engine": vcfg.get("voice_id"),
            "label": vcfg.get("label"),
            "fish_configured": fish_configured(),
            "reference_id": get_jarvis_reference_id(),
            "api_credit_usd": wallet.get("active_credit_usd"),
            "sample_source": _read_voice_sample_source(),
        }
    except Exception as e:
        out["voice_error"] = str(e)[:200]
    return out


def _read_voice_sample_source() -> str:
    try:
        store = (Path.home() / '.hermes' / 'jarvis_voice.json')
        if store.exists():
            return json.loads(store.read_text(encoding="utf-8")).get("sample_source", "")
    except Exception:
        pass
    return ""


def _blockers(health: Dict[str, Any], voice: Dict[str, Any]) -> List[Dict[str, str]]:
    blockers: List[Dict[str, str]] = []
    ready = (health.get("health") or {}).get("ready") or (health.get("health") or {}).get("status")
    if ready == "CONFIGURE_GOOGLE_KEY":
        blockers.append({
            "id": "google_key",
            "titulo": "Google API Key",
            "acao": "Cole GOOGLE_API_KEY=AIzaSy... em jarvis-pro/.env.local e reinicie o backend.",
        })
    v = voice.get("voice") or {}
    credit = v.get("api_credit_usd")
    if credit is not None and float(credit) < 0.05:
        blockers.append({
            "id": "fish_credit",
            "titulo": "Crédito Fish Audio baixo",
            "acao": "Recarregue em https://fish.audio/pt/app/developers",
        })
    try:
        store = json.loads(
            (Path.home() / '.hermes' / 'jarvis_voice.json').read_text(encoding="utf-8")
        )
        if store.get("xai_clone_blocked"):
            blockers.append({
                "id": "xai_voice",
                "titulo": "Voz custom xAI bloqueada",
                "acao": "Usar Fish (Thomas) como voz principal — já configurado.",
            })
    except Exception:
        pass
    return blockers


def _spoken_summary(ok_n: int, partial_n: int, broken_n: int, blockers: List[Dict]) -> str:
    lines = [
        f"Senhor, auditoria JARVIS: {ok_n} pedidos ok, {partial_n} parciais, {broken_n} quebrados.",
    ]
    partials = [r for r in USER_REQUESTS_AUDIT if r["status"] == "parcial"][:3]
    for p in partials:
        lines.append(f"{p['pedido']}: {p['motivo']}")
    if blockers:
        lines.append(f"Bloqueio principal: {blockers[0]['titulo']} — {blockers[0]['acao']}")
    lines.append("Pergunte o que você pode fazer, ou peça auditoria completa no Obsidian.")
    return " ".join(lines)[:900]


async def build_report_async(*, include_capabilities: bool = True) -> Dict[str, Any]:
    from jarvis_agent import JARVIS_CAPABILITIES, _refresh_capabilities_meta

    if include_capabilities:
        _refresh_capabilities_meta()

    health = await _live_health()
    blockers = _blockers(health, health)
    ok_n = sum(1 for r in USER_REQUESTS_AUDIT if r["status"] == "ok")
    partial_n = sum(1 for r in USER_REQUESTS_AUDIT if r["status"] == "parcial")
    broken_n = sum(1 for r in USER_REQUESTS_AUDIT if r["status"] == "quebrado")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "ok": ok_n,
            "parcial": partial_n,
            "quebrado": broken_n,
            "total_pedidos": len(USER_REQUESTS_AUDIT),
        },
        "user_requests_audit": USER_REQUESTS_AUDIT,
        "blockers": blockers,
        "live": health,
        "capabilities": JARVIS_CAPABILITIES if include_capabilities else {},
        "spoken_summary": _spoken_summary(ok_n, partial_n, broken_n, blockers),
    }


def save_to_obsidian(report: Dict[str, Any]) -> str:
    VAULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ts = report.get("generated_at", "")[:19]
    lines = [
        "---",
        "tags: [jarvis, orquestracao, auditoria]",
        f"date: {ts}",
        "---",
        "",
        "# Orquestração JARVIS",
        "",
        f"> Gerado em {ts}",
        "",
        "## Resumo",
        "",
    ]
    s = report.get("summary") or {}
    lines.append(f"- OK: **{s.get('ok', 0)}** | Parcial: **{s.get('parcial', 0)}** | Quebrado: **{s.get('quebrado', 0)}**")
    lines.append("")
    lines.append("## Pedidos do Gustavo")
    lines.append("")
    lines.append("| Pedido | Status | Por quê |")
    lines.append("|--------|--------|---------|")
    for r in report.get("user_requests_audit") or []:
        lines.append(f"| {r.get('pedido', '')} | {r.get('status', '')} | {r.get('motivo', '')} |")
    lines.append("")
    lines.append("## Bloqueios")
    lines.append("")
    for b in report.get("blockers") or []:
        lines.append(f"- **{b.get('titulo', '')}**: {b.get('acao', '')}")
    if not report.get("blockers"):
        lines.append("- Nenhum bloqueio crítico detectado.")
    lines.append("")
    lines.append("## Links")
    lines.append("")
    lines.append("- [[jarvis_agent.py]] [[query_intelligence.py]] [[agent_orchestrator.py]]")
    lines.append("- [[intent_resolver.py]] [[jarvis_orchestration_report.py]]")
    lines.append("")
    voice = (report.get("live") or {}).get("voice") or {}
    if voice.get("reference_id"):
        lines.append(f"- Voz Fish: `{voice.get('reference_id')}`")
    lines.append("")
    text = "\n".join(lines)
    VAULT_PATH.write_text(text, encoding="utf-8")
    return str(VAULT_PATH)