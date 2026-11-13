"""
Fast paths do JARVIS Agent — ações rápidas sem passar pelo LLM.
Extraído de jarvis_agent.py para reduzir complexidade.
"""

import asyncio
import re
import urllib.parse
from typing import Any, Awaitable, Callable, Dict, List, Optional

from xai_client import fast_mode_enabled, get_client, get_fast_model
from conversation_state import get_api_messages, get_user_prefs, get_recent_context, update_user_pref
import jarvis_memory
from xai_tools import search_with_tools
from pending_state import load_pending, save_pending, clear_pending

import actions
import desktop_control
import jarvis_design_memory
import obsidian_notes
import web_browser
from intent_resolver import resolve_fast_action
from query_intelligence import normalize_search_query, parse_youtube_intent, resolve_search_query
import jarvis_credentials
import voice_prefs
import databricks_client
import jarvis_live
import local_vision
import offline_tools

from agent_constants import (
    MAX_ROUNDS,
    RISKY_TOOLS,
    _TOOL_TRIGGERS,
    _BROWSER_TOOLS,
    _OPENS_BROWSER,
    _BROWSER_APP_NAMES,
    _turn_user_text,
    _browse_allowed_for_turn,
    _needs_browser_action,
    _is_web_exploration,
    _is_conversational,
    _is_pure_chat,
    _is_info_tool_request,
    _is_capabilities_request,
    _is_cowatch_request,
    _is_youtube_cowatch,
    _is_browser_nav_query,
    _is_close_panel,
    _is_fullscreen,
    _is_skip_ad,
    _is_research_doc,
    _is_search_fast,
    _is_calango_live,
    _is_screen_assist,
    _is_whatsapp_open,
    _is_whatsapp_msg,
    _DOC_APPS,
    _YOUTUBE_OPEN_RE,
    _YOUTUBE_SEARCH_RE,
    _YOUTUBE_WATCH_RE,
    _YOUTUBE_URL_RE,
    _YOUTUBE_OPEN,
    _YOUTUBE_SEARCH,
    _YOUTUBE_PLAY,
    _BROWSER_NAV_QUERY,
    _CLOSE_PANEL_RE,
    _FULLSCREEN_RE,
    _SKIP_AD_RE,
    _COPA_CASETV_RE,
    _RESEARCH_DOC_RE,
    _SEARCH_FAST,
    _MULTI_AND_RE,
    _COWATCH_RE,
    _CALANGO_LIVE_RE,
    _SCREEN_ASSIST_RE,
    _WHATSAPP_OPEN_RE,
    _WHATSAPP_MSG_RE,
)

Broadcast = Callable[[dict], Awaitable[None]]

# ============================================================
# Helpers internos
# ============================================================

def _strip_wake_part(text: str) -> str:
    """Remove wake word 'jarvis' do início do texto."""
    return re.sub(r"^(?:jarvis)[,\s]+", "", text, flags=re.I).strip()

def _max_agent_rounds() -> int:
    if fast_mode_enabled():
        try:
            return max(2, min(5, int(os.getenv("JARVIS_MAX_ROUNDS") or "3")))
        except ValueError:
            return 3
    return MAX_ROUNDS

def _semantic_memory_enabled() -> bool:
    return (os.getenv("JARVIS_SEMANTIC_MEMORY") or "1").strip().lower() not in (
        "0", "false", "no", "off",
    ) and not fast_mode_enabled()

# ============================================================
# Fast paths: ferramentas rápidas sem LLM
# ============================================================

async def _try_fast_datetime(user_text: str, broadcast: Broadcast) -> Optional[Dict[str, Any]]:
    """Hora/data — resposta instantânea sem LLM."""
    from datetime import datetime
    import locale
    try:
        locale.setlocale(locale.LC_TIME, 'pt_BR.UTF-8')
    except Exception:
        pass
    now = datetime.now()
    if re.search(r"\b(?:que\s+horas|qual\s+(?:a\s+)?hora|hor[áa]rio\s+(?:atual|agora|de\s+agora))\b", user_text, re.I):
        spoken = f"São {now.strftime('%H:%M')}, senhor."
        return {"response": spoken, "tools_used": []}
    if re.search(r"\b(?:que\s+dia\s+(?:[ée]\s+)?hoje|data\s+de\s+hoje|dia\s+de\s+hoje)\b", user_text, re.I):
        spoken = f"Hoje é {now.strftime('%d de %B de %Y')}, senhor."
        return {"response": spoken, "tools_used": []}
    return None

async def _try_fast_status(user_text: str, broadcast: Broadcast) -> Optional[Dict[str, Any]]:
    """Status do PC — RAM, CPU, bateria, disco."""
    if not _is_info_tool_request(user_text):
        return None
    try:
        import psutil
    except ImportError:
        return {"response": "psutil não instalado, senhor.", "tools_used": []}
    
    cpu = psutil.cpu_percent(interval=0.2)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    bat = psutil.sensors_battery()
    
    parts = [f"CPU {cpu:.0f}%", f"RAM {mem.percent:.0f}% ({mem.used//1024//1024}MB/{mem.total//1024//1024}MB)"]
    if bat:
        parts.append(f"Bateria {bat.percent:.0f}%{' carregando' if bat.power_plugged else ''}")
    parts.append(f"Disco {disk.percent:.0f}% livre ({disk.free//1024//1024//1024}GB)")
    
    spoken = "Status do sistema: " + ", ".join(parts) + ", senhor."
    return {"response": spoken, "tools_used": [{"tool": "system_status", "result": "ok"}]}

async def _try_fast_voice_change(user_text: str, broadcast: Broadcast) -> Optional[Dict[str, Any]]:
    """Troca de voz — edge, eleven, fish, local, clone."""
    from voice_prefs import set_voice_id, list_voices, get_voice_config
    from fish_tts import get_jarvis_reference_id
    
    vcfg = get_voice_config()
    voices = list_voices()
    
    # Detecta qual voz o usuário quer
    target = None
    if re.search(r"\b(?:eleven|thomas|0701|elevenlabs)\b", user_text, re.I):
        target = "eleven"
    elif re.search(r"\b(?:edge|antonio|microsoft|padr[ãa]o|default)\b", user_text, re.I):
        target = "edge"
    elif re.search(r"\b(?:fish|peixe|verdadeiro|clone\s+fish)\b", user_text, re.I):
        target = "fish"
    elif re.search(r"\b(?:local|clone|xtts|meu\s+clone)\b", user_text, re.I):
        target = "local"
    elif re.search(r"\b(?:xai|grok)\b", user_text, re.I):
        target = "xai"
    
    if not target:
        return None
    
    try:
        if target == "eleven":
            from eleven_tts import eleven_configured
            if not eleven_configured():
                return {"response": "ElevenLabs não configurado, senhor.", "tools_used": []}
            set_voice_id("eleven")
            spoken = "Voz alterada para JARVIS Thomas, senhor."
        elif target == "edge":
            set_voice_id("antonio")
            spoken = "Voz alterada para Edge Antonio Neural, senhor."
        elif target == "fish":
            if not get_jarvis_reference_id():
                return {"response": "Voz Fish não clonada ainda, senhor. Rode clone_fish_voice.py.", "tools_used": []}
            set_voice_id("thomas")
            spoken = "Voz alterada para Fish Audio (clone 0701), senhor."
        elif target == "local":
            from local_clone_tts import local_clone_status
            status = await local_clone_status()
            if not (status.get("ok") or status.get("reference_ok")):
                return {"response": "Clone local não disponível, senhor.", "tools_used": []}
            set_voice_id("local")
            spoken = "Voz alterada para clone local XTTS 0701, senhor."
        elif target == "xai":
            from xai_tts import get_xai_voice_id
            if not get_xai_voice_id():
                return {"response": "Voz xAI não disponível, senhor.", "tools_used": []}
            set_voice_id("xai")
            spoken = "Voz alterada para xAI TTS, senhor."
        else:
            return None
        
        return {"response": spoken, "tools_used": [{"tool": "voice_change", "result": target}]}
    except Exception as e:
        return {"response": f"Falha ao trocar voz: {e}", "tools_used": []}

async def _try_fast_site_open(user_text: str, broadcast: Broadcast) -> Optional[Dict[str, Any]]:
    """Abre site conhecido direto no painel."""
    # Sites conhecidos
    sites = {
        "google": "https://www.google.com",
        "youtube": "https://www.youtube.com",
        "instagram": "https://www.instagram.com",
        "github": "https://github.com",
        "gmail": "https://mail.google.com",
        "whatsapp": "https://web.whatsapp.com",
        "linkedin": "https://www.linkedin.com",
        "twitter": "https://twitter.com",
        "x.com": "https://x.com",
        "reddit": "https://www.reddit.com",
        "netflix": "https://www.netflix.com",
        "spotify": "https://open.spotify.com",
    }
    
    for name, url in sites.items():
        if re.search(rf"\b(?:abre|abra|abrir|acesse|acessa)\s+(?:o\s+)?{name}\b", user_text, re.I):
            await broadcast({"type": "tool_call", "tool": "browse_open", "status": "running", "desc": f"Abrindo {name}"})
            try:
                feedback = await asyncio.wait_for(web_browser.open_url(url), timeout=25.0)
            except Exception as e:
                feedback = str(e)
            await broadcast({"type": "tool_call", "tool": "browse_open", "status": "done", "result": str(feedback)[:200]})
            return {"response": f"{name.capitalize()} aberto no painel, senhor.", "tools_used": [{"tool": "browse_open", "result": str(feedback)[:200]}]}
    return None

async def _try_fast_app_open(user_text: str, broadcast: Broadcast) -> Optional[Dict[str, Any]]:
    """Abre app nativo do Windows."""
    for pat, app_key, label in _DOC_APPS:
        if pat.search(user_text):
            if not (re.search(r"\b(?:abre|abra|abrir|acesse|acessa)\b", user_text, re.I)):
                return None
            await broadcast({"type": "tool_call", "tool": "open_app", "status": "running", "desc": f"Abrindo {label}"})
            try:
                fb = await asyncio.to_thread(desktop_control.open_app, app_key)
            except Exception as e:
                fb = str(e)
            await broadcast({"type": "tool_call", "tool": "open_app", "status": "done", "result": str(fb)[:200]})
            return {"response": f"{label} aberto, senhor.", "tools_used": [{"tool": "open_app", "result": str(fb)[:200]}]}
    return None

async def _try_fast_youtube(user_text: str, broadcast: Broadcast) -> Optional[Dict[str, Any]]:
    """YouTube no painel — busca inteligente e play no primeiro vídeo."""
    raw = (user_text or "").strip()
    if not raw:
        return None

    intent = parse_youtube_intent(raw)
    if intent and intent.get("action") == "cowatch":
        return None

    if _YOUTUBE_WATCH_RE.search(raw):
        url_m = _YOUTUBE_URL_RE.search(raw)
        if url_m:
            target = url_m.group(0)
            return await _panel_browse(broadcast, target, query="YouTube", spoken="Vídeo aberto no painel, senhor.")

    if intent:
        action = intent.get("action")
        if action == "open":
            return await _panel_browse(broadcast, "https://www.youtube.com", query="YouTube", spoken="Sim, senhor. YouTube aberto no painel.")
        if action in ("search", "play"):
            q = await resolve_search_query(intent.get("query") or raw, platform="youtube")
            if q and len(q) >= 2:
                await broadcast({"type": "tool_call", "tool": "browse_open", "status": "running", "desc": f"YouTube: {q}"})
                try:
                    feedback = await web_browser.youtube_search_and_play(q)
                except Exception as e:
                    feedback = str(e)
                await broadcast({"type": "tool_call", "tool": "browse_open", "status": "done", "result": str(feedback)[:200]})
                spoken = f"Sim, senhor. Pesquisei {q} no YouTube e abri o vídeo." if action == "play" else f"Pesquisa no YouTube: {q}, senhor."
                return {"response": spoken, "tools_used": [{"tool": "browse_open", "result": str(feedback)[:200]}]}

    if _YOUTUBE_OPEN_RE.search(raw) and not _YOUTUBE_SEARCH_RE.search(raw) and not _YOUTUBE_WATCH_RE.search(raw):
        return await _panel_browse(broadcast, "https://www.youtube.com", query="YouTube", spoken="Sim, senhor. YouTube aberto no painel.")

    return None

async def _panel_browse(broadcast: Broadcast, url: str, query: str, spoken: str) -> Dict[str, Any]:
    """Abre URL no painel e retorna resposta padronizada."""
    await broadcast({"type": "tool_call", "tool": "browse_open", "status": "running", "desc": f"Abrindo {url}"})
    try:
        feedback = await asyncio.wait_for(web_browser.open_url(url), timeout=30.0)
    except Exception as e:
        feedback = str(e)
    await broadcast({"type": "tool_call", "tool": "browse_open", "status": "done", "result": str(feedback)[:200]})
    return {"response": spoken, "tools_used": [{"tool": "browse_open", "result": str(feedback)[:200]}]}

# Import os for _max_agent_rounds
import os