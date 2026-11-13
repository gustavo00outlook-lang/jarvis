"""Contexto situacional em tempo real — JARVIS sabe o que está acontecendo agora."""

from __future__ import annotations

from datetime import datetime
from typing import List


def build_situational_block() -> str:
    """Bloco leve injetado no system prompt — respostas mais rápidas e contextualizadas."""
    lines: List[str] = [
        "\n\n=== SITUAÇÃO AGORA (responda com base nisto; não invente estado) ===",
        f"• Data/hora PC: {datetime.now().strftime('%A %d/%m/%Y %H:%M')}",
    ]

    try:
        import jarvis_live

        if jarvis_live.is_cowatch_active():
            lines.append(
                "• CO-ASSISTIR ATIVO — narre o painel, debata se o Gustavo pedir opinião/argumento."
            )
    except Exception:
        pass

    try:
        import web_browser

        if web_browser.has_session():
            lines.append(
                "• Painel navegador ABERTO — use browse_read/click/type/scroll sem reabrir."
            )
        elif web_browser.has_playwright_page():
            lines.append("• Playwright aquecido — primeira navegação será rápida.")
    except Exception:
        pass

    try:
        from agent_orchestrator import get_orchestrator

        orch = get_orchestrator()
        st = orch.status_dict()
        aid = st.get("active_agent_id")
        if aid:
            lines.append(f"• Agente especialista ativo: {aid}")
        total = st.get("total_agents", 0)
        if total:
            lines.append(f"• Orquestrador: {total} agentes AIOS/Xquads disponíveis (/agentes).")
    except Exception:
        pass

    try:
        from jarvis_skills_registry import load_skills

        n = len(load_skills())
        if n:
            lines.append(f"• Skills Grok/Cursor: {n} (/skills).")
    except Exception:
        pass

    try:
        from voice_prefs import get_voice_config

        vc = get_voice_config()
        lines.append(f"• Voz TTS: {vc.get('engine', '?')} — {vc.get('label', '')[:48]}")
    except Exception:
        pass

    lines.append(
        "• PC: run_command, open_app, list_windows, look_at_screen, clipboard — acesso total com confirmação em risco."
    )
    lines.append(
        "• Sites: browse_open + browse_site_search (Google/YouTube/Instagram); co-assistir YouTube/IG/Reels."
    )
    return "\n".join(lines)