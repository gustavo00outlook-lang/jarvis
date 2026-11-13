"""
JARVIS Agent — loop agentic com function calling nativo do Grok.

O modelo decide sozinho quando conversar e quando agir: pode encadear
várias tools em sequência (abrir app → pesquisar → escrever nota) antes
de responder. Ações de risco pausam o loop e aguardam confirmação.
"""

import asyncio
import json
import os
import re
import time
import unicodedata
import urllib.parse
from typing import Any, Awaitable, Callable, Dict, List, Optional

from xai_client import (
    fast_mode_enabled,
    get_client,
    get_model,
    get_fast_model,
    get_smart_model,
    get_provider,
    is_ollama_only,
)
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
from agent_constants import _is_pure_chat

Broadcast = Callable[[dict], Awaitable[None]]

_TURN_RUFLO_META: Dict[str, Any] = {}

MAX_ROUNDS = 6
RISKY_TOOLS = {"run_command", "close_app"}


def _max_agent_rounds() -> int:
    if fast_mode_enabled():
        try:
            return max(2, min(5, int(os.getenv("JARVIS_MAX_ROUNDS") or "3")))
        except ValueError:
            return 3
    return MAX_ROUNDS


def _semantic_memory_enabled() -> bool:
    return (os.getenv("JARVIS_SEMANTIC_MEMORY") or "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    ) and not fast_mode_enabled()

_TOOL_TRIGGERS = (
    "abre ", "abra ", "abrir ", "abre o", "abre a", "abre o ",
    "pesquisa no", "pesquisar no", "pesquise no", "pesquisa ",
    "busca no", "buscar no", "busque no",
    "execut", "comando", "volume ", "escrev", "digite ",
    "naveg", "browse_", "screenshot", "captura ",
    "fecha ", "spotify", "youtube.com", "http://", "https://",
    "modo studio", "calango.studio",
    "explor", "ferrament", "função", "funcao", "cada fun", "veja o que",
    "look_at", "watch_screen", "desktop_click",
    "clipboard", "área de transferência", "area de transferencia",
    "lista janelas", "janelas abertas", "abre pasta", "screenshot",
    "traduz", "traduza", "clima", "tempo em", "lembrete", "nota rápida",
    # tarefas no PC / apps / sites (habilidades de desktop expandidas)
    "arrast", "foca a janela", "foque", "mexe no", "use o app", "no aplicativo",
    "site", "clica em", "clique em", "faça no", "faca no", "organiza a pasta",
    "arquivos da pasta", "meu pc", "no computador", "instala ", "abra o arquivo",
)

_BROWSER_TOOLS = frozenset({
    "browse_open", "browse_read", "browse_click", "browse_type", "browse_scroll",
    "browse_press_key", "browse_carousel_slide", "browse_back", "browse_site_search",
    "open_url", "open_browser_search", "web_search",
})

# Tools que ABREM um navegador visível na tela — gate rígido: só com pedido web explícito.
# web_search NÃO entra aqui (é busca de fato via API, não abre o Google).
# browse_read/click/scroll também não — apenas continuam uma página já aberta.
_OPENS_BROWSER = frozenset({"open_url", "open_browser_search", "browse_open"})

_BROWSER_APP_NAMES = frozenset({
    "chrome", "google chrome", "navegador", "edge", "msedge", "microsoft edge",
})


def _turn_user_text(messages: List[Dict[str, Any]]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return str(m.get("content") or "")
    return ""


def _browse_allowed_for_turn(user_text: str) -> bool:
    # Painel/navegação só com pedido explícito de ABRIR/VER/NAVEGAR — não em "pesquisa X" genérico.
    return _needs_browser_action(user_text) or _is_web_exploration(user_text)


_BROWSER_ACTION_RE = (
    re.compile(
        r"\b(?:abre|abra|abrir|acesse|acessa|vá|va|naveg|mostra)\b"
        r".*\b(?:google|site|url|http|\.com|painel|tela)\b",
        re.I,
    ),
    re.compile(r"\b(?:abre|abra|abrir)\s+(?:o\s+)?(?:google|chrome|youtube|instagram)\b", re.I),
    re.compile(
        r"\b(?:pesquis(?:e|ar|a|ei)|busc(?:a|ar|e)|procure|procurar)\b"
        r".*\b(?:no\s+painel|na\s+tela|mostra|veja)\b",
        re.I,
    ),
    re.compile(r"https?://", re.I),
)

# Só conversa rasa — NÃO incluir opinião, "o que é X", nem pedido de pesquisa.
_CONVERSATIONAL_RE = (
    re.compile(r"^(?:oi|olá|ola|hey|bom dia|boa tarde|boa noite)\b", re.I),
    re.compile(
        r"^(?:como\s+(?:você|voce|vc)\s+(?:está|esta|vai)|tudo\s+bem|beleza|e\s+a[ií])\b",
        re.I,
    ),
    re.compile(r"\b(?:obrigad|valeu|tchau|até logo|ate logo|falou|flw)\b", re.I),
    re.compile(r"^(?:sim|não|nao|ok|certo|entendi|legal|show|haha|kk+|blz)\s*[.!?]?$", re.I),
    re.compile(r"^(?:e\s+aí|e\s+ai|fala|fala\s+aí|suave)\s*[.!?]?$", re.I),
)

# Conversa pura (humor leve / social) — NÃO pesquisa Google
_PURE_CHAT_RE = re.compile(
    r"(?:"
    r"^(?:oi|olá|ola|hey|bom dia|boa tarde|boa noite|e aí|e ai|fala)\b"
    r"|^(?:tudo bem|como (?:você|voce|vc|está|esta|vai)|beleza)\b"
    r"|\b(?:kk+|haha|rsrs|piada|brincando|zoeira|pegadinha)\b"
    r"|\b(?:obrigad|valeu|tchau|até logo|ate logo)\b"
    r"|^ok\b|^certo\b|^entendi\b|^blz\b"
    r")",
    re.I,
)

_EXPLORATION_TRIGGERS = (
    "explor", "ferrament", "função", "funcao", "cada fun", "veja o que",
    "o que cada", "como funciona", "aprenda sobre", "aprende sobre",
    "mapeie", "mapeia", "navegue", "navega por",
)

# Perguntas de info/sistema que PRECISAM de tool (hora, data, status do PC),
# mesmo quando a frase soa "conversacional" (ex.: "como está meu PC").
_INFO_TOOL_RE = re.compile(
    r"(?:que\s+horas|qual\s+(?:a\s+)?hora|hor[áa]rio\s+(?:atual|agora|de\s+agora)|"
    r"que\s+dia\s+(?:[ée]\s+)?hoje|data\s+de\s+hoje|dia\s+de\s+hoje|"
    r"status\s+do\s+(?:pc|computador|sistema|notebook|m[áa]quina)|"
    r"como\s+(?:est[áa]|t[áa])\s+(?:o\s+|a\s+)?(?:meu\s+|minha\s+)?"
    r"(?:pc|computador|sistema|m[áa]quina|notebook)|"
    r"(?:uso|n[íi]vel|quanto)\s+(?:de\s+|da\s+|do\s+)?(?:ram|cpu|mem[óo]ria|disco|bateria)|"
    r"\b(?:ram|cpu)\b|n[íi]vel\s+da\s+bateria|minha\s+bateria)",
    re.I,
)

_CAPABILITIES_RE = re.compile(
    r"\b(?:"
    r"o\s+que\s+(?:você|voce|vc)\s+pode\s+fazer|"
    r"quais?\s+(?:são\s+)?(?:suas?\s+)?(?:funç|capac|habil|habul)|"
    r"suas?\s+habilidades?|suas?\s+habulidades?|"
    r"me\s+mostra\s+(?:suas?\s+)?(?:funç|capac)|"
    r"lista\s+(?:suas?\s+)?(?:funç|capac)|"
    r"como\s+(?:você|voce)\s+(?:me\s+)?ajuda|"
    r"o\s+que\s+(?:você|voce)\s+sabe\s+fazer"
    r")\b",
    re.I,
)

_CAPABILITIES_SPOKEN_TAIL = (
    "Tarefas pesadas — código, arquivos, projetos — eu delego ao cérebro Claude Code, "
    "que trabalha em background e me avisa quando termina. "
    "Voz ElevenLabs clonada do seu 0701.WAV — calibro até ficar idêntica. "
    "Pesquiso e navego dentro de sites: Google, YouTube, Instagram, Calango — busco, clico, rolo. "
    "Assisto vídeos com você no painel, comento, argumento e salvo relatório no Obsidian. "
    "Acesso total ao PC: apps, pastas, tela, clipboard, comandos — com confirmação em ações de risco. "
    "Sei o que está acontecendo agora: painel aberto, co-assistir ativo, agente em uso. "
    "Comandos: /agentes /ativar [id] /skills. "
    "Experimente: assista comigo um reel no instagram e discuta comigo, ou pesquisa X no youtube."
)

JARVIS_CAPABILITIES_SPOKEN = (
    "Senhor, opero em tempo real com agentes especialistas e skills Grok. "
    + _CAPABILITIES_SPOKEN_TAIL
)

JARVIS_CAPABILITIES = {
    "spoken": JARVIS_CAPABILITIES_SPOKEN,
    "categories": [
        {
            "id": "web",
            "title": "Web ao vivo",
            "examples": ["pesquisa copa 2026", "abre calango.studio no painel", "abre youtube"],
        },
        {
            "id": "cowatch",
            "title": "Co-assistir",
            "examples": [
                "assista comigo um vídeo do instagram",
                "comenta enquanto assistimos no youtube",
                "faz relatório do que vimos",
            ],
        },
        {
            "id": "calango",
            "title": "Calango Studio",
            "examples": [
                "entra na calango.studio e gera uma imagem de banner",
                "abre modo studio e mexe nas ferramentas de IA",
            ],
        },
        {
            "id": "screen",
            "title": "Tela real",
            "examples": [
                "abre o whatsapp e veja quem mandou",
                "me ajuda com isso",
                "edita esse vídeo no capcut para mim",
            ],
        },
        {
            "id": "memory",
            "title": "Memória",
            "examples": ["o que você acha dos jogos da copa", "estuda sobre IA", "lembra que prefiro dark mode"],
        },
        {
            "id": "pc",
            "title": "PC",
            "examples": ["abre o excel", "que horas são", "status do pc", "tela cheia"],
        },
        {
            "id": "utilities",
            "title": "Utilidades",
            "examples": [
                "como está o tempo em Caçador",
                "abre pasta downloads",
                "lista janelas abertas",
                "ler clipboard",
                "salva screenshot no obsidian",
                "traduz para inglês: bom dia",
                "anota que reunião às 15h",
            ],
        },
        {
            "id": "agents",
            "title": "166 Agentes AIOS + Xquads",
            "examples": ["/agentes", "/ativar dev", "/ativar copy-chief", "/quem", "/sugerir"],
        },
        {
            "id": "skills",
            "title": "Skills Grok/Cursor",
            "examples": ["/skills", "usa browser-qa", "implementa isso", "cria um docx"],
        },
    ],
}


def _refresh_capabilities_meta() -> None:
    """Atualiza metadados reais (agentes, skills, tools, cérebro, voz) no dict de capacidades."""
    try:
        from agent_orchestrator import get_orchestrator
        from jarvis_skills_registry import load_skills

        orch = get_orchestrator()
        st = orch.status_dict()
        JARVIS_CAPABILITIES["orchestrator"] = st
        JARVIS_CAPABILITIES["agents_total"] = st.get("total_agents", 0)
        JARVIS_CAPABILITIES["skills_total"] = len(load_skills())
    except Exception:
        pass
    JARVIS_CAPABILITIES["tools_total"] = len(TOOLS)
    try:
        from xai_client import get_last_used_provider, get_provider

        JARVIS_CAPABILITIES["provider"] = get_last_used_provider() or get_provider()
    except Exception:
        pass
    try:
        vc = voice_prefs.get_voice_config()
        JARVIS_CAPABILITIES["voice"] = {"engine": vc.get("engine"), "label": vc.get("label")}
    except Exception:
        pass

    inventory: List[str] = []
    agents = JARVIS_CAPABILITIES.get("agents_total") or 0
    skills = JARVIS_CAPABILITIES.get("skills_total") or 0
    if agents:
        inventory.append(f"{agents} agentes especialistas")
    if skills:
        inventory.append(f"{skills} skills Grok")
    inventory.append(f"{len(TOOLS)} ferramentas nativas")
    if len(inventory) > 1:
        frota = ", ".join(inventory[:-1]) + " e " + inventory[-1]
    else:
        frota = inventory[0]
    JARVIS_CAPABILITIES["spoken"] = (
        f"Senhor, opero em tempo real com {frota}. " + _CAPABILITIES_SPOKEN_TAIL
    )

_CANNED: Dict[str, str] = {
    "oi": "Olá, senhor.",
    "oi jarvis": "Olá, senhor.",
    "oi senhor": "Olá, senhor. Às suas ordens.",
    "olá": "Olá, senhor.",
    "olá jarvis": "Olá, senhor.",
    "ola": "Olá, senhor.",
    "ola jarvis": "Olá, senhor.",
    "ola senhor": "Olá, senhor. Às suas ordens.",
    "hey": "Sim, senhor. Estou aqui.",
    "bom dia": "Bom dia, senhor.",
    "boa tarde": "Boa tarde, senhor.",
    "boa noite": "Boa noite, senhor.",
    "boa noite jarvis": "Boa noite, senhor.",
    "bom dia jarvis": "Bom dia, senhor.",
    "boa tarde jarvis": "Boa tarde, senhor.",
    "tudo bem": "Tudo operacional, senhor. E com o senhor?",
    "tudo bem?": "Tudo operacional, senhor. E com o senhor?",
    "tudo joia": "Tudo operacional, senhor. E com o senhor?",
    "tudo joia?": "Tudo operacional, senhor. E com o senhor?",
    "oi tudo bem": "Olá, senhor. Tudo operacional por aqui. Como posso ajudar?",
    "oi, tudo bem": "Olá, senhor. Tudo operacional por aqui. Como posso ajudar?",
    "oi tudo bem?": "Olá, senhor. Tudo operacional por aqui. Como posso ajudar?",
    "e aí": "Às ordens, senhor.",
    "e ai": "Às ordens, senhor.",
    "e aí, beleza": "Às ordens, senhor. Tudo certo por aqui.",
    "e ai, beleza": "Às ordens, senhor. Tudo certo por aqui.",
    "beleza": "Tudo sob controle, senhor.",
    "como está": "Tudo operacional, senhor. Como posso ajudar?",
    "como esta": "Tudo operacional, senhor. Como posso ajudar?",
    "como você está": "Tudo operacional por aqui, senhor. E o senhor, como está?",
    "como voce esta": "Tudo operacional por aqui, senhor. E o senhor, como está?",
    "como você está hoje": "Tudo operacional, senhor. Espero que seu dia transcorra bem. Em que posso ajudar?",
    "como voce esta hoje": "Tudo operacional, senhor. Espero que seu dia transcorra bem. Em que posso ajudar?",
    "como vai": "Tudo operacional, senhor. E com o senhor?",
    "como vai?": "Tudo operacional, senhor. E com o senhor?",
    "como vai você": "Tudo operacional por aqui, senhor. E o senhor, como vai?",
    "como vai voce": "Tudo operacional por aqui, senhor. E o senhor, como vai?",
    "como vai vc": "Tudo operacional por aqui, senhor. E com o senhor?",
    "como vai você hoje": "Tudo operacional, senhor. Seu dia está bom?",
    "como vai voce hoje": "Tudo operacional, senhor. Seu dia está bom?",
    "obrigado": "De nada, senhor.",
    "obrigada": "De nada, senhor.",
    "valeu": "Por nada, senhor.",
    "tchau": "Até logo, senhor.",
    "tchau jarvis": "Até logo, senhor.",
    "falou": "Até mais, senhor.",
    "flw": "Até logo, senhor.",
    "até logo": "Até logo, senhor.",
    "ate logo": "Até logo, senhor.",
    "ok": "Sim, senhor.",
    "teste fast": "FAST PATH OK",
    "quem e voce": "Sou o JARVIS, senhor. Assistente da Calango Studio. Às suas ordens.",
    "quem é você": "Sou o JARVIS, senhor. Assistente da Calango Studio. Às suas ordens.",
    "quem e vc": "Sou o JARVIS, senhor. Assistente da Calango Studio. Às suas ordens.",
    "quem é vc": "Sou o JARVIS, senhor. Assistente da Calango Studio. Às suas ordens.",
    "quem e o jarvis": "Sou o JARVIS, senhor. Às suas ordens.",
    "quem é o jarvis": "Sou o JARVIS, senhor. Às suas ordens.",
    "qual seu nome": "JARVIS, senhor.",
    "qual o seu nome": "JARVIS, senhor.",
    "seu nome": "JARVIS, senhor.",
}

_GREETING_ONLY = frozenset({
    "oi", "oi jarvis", "olá", "olá jarvis", "ola", "ola jarvis",
    "hey", "hey jarvis", "bom dia", "boa tarde", "boa noite",
    "obrigado", "obrigada", "valeu", "tchau", "tchau jarvis", "falou", "flw", "até logo", "ate logo",
    "ok",
    "quem e voce", "quem é você", "quem e vc", "quem é vc",
    "quem e o jarvis", "quem é o jarvis", "qual seu nome", "qual o seu nome", "seu nome",
    "tudo bem", "tudo bem?", "tudo joia", "tudo joia?",
    "beleza",
    "como está", "como esta", "como você está", "como voce esta",
    "como você está hoje", "como voce esta hoje",
    "como vai", "como vai?", "como vai você", "como vai voce", "como vai vc",
    "como vai você hoje", "como vai voce hoje",
    "e aí", "e ai", "e aí, beleza", "e ai, beleza",
})


def _is_pure_greeting(key: str) -> bool:
    """Saudação curta — resposta canned ou LLM mínimo sem injetar memória Obsidian."""
    k = (key or "").strip().lower()
    if k in _GREETING_ONLY or k in _CANNED:
        return True
    if k.endswith(" jarvis"):
        base = k[:-7].strip()
        return base in _GREETING_ONLY or base in _CANNED
    return False

_SUGGESTION_MARKERS = (
    "quer que", "posso ", "sugiro", "sugest", "próximo passo", "proximo passo",
    "da próxima", "da proxima", "se quiser", "recomendo", "alternativa",
    "também daria", "tambem daria", "faço?", "faco?",
)

_obsidian_cache: Dict[str, Any] = {"at": 0.0, "text": ""}


def _needs_browser_action(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    return any(p.search(raw) for p in _BROWSER_ACTION_RE)


def _wants_opinion_or_research(text: str) -> bool:
    """True quando deve pesquisar no Google e opinar (não conversa rasa)."""
    raw = (text or "").strip()
    if not raw or _is_pure_greeting(raw):
        return False
    # Conversa social / humor: só falar, sem Google
    if _PURE_CHAT_RE.search(raw) and not _OPINION_RE.search(raw) and not _SEARCH_FAST.match(raw):
        # Exceção: "o que você acha de X" ainda é opinião
        if not re.search(r"\b(?:sobre|de|do|da)\s+[\wÀ-ú]{3,}", raw, re.I):
            if not jarvis_memory.wants_debate(raw):
                # "tudo bem?" / "como você está?" = chat
                if re.match(
                    r"^(?:oi|olá|ola|hey|bom dia|boa tarde|boa noite|tudo bem|como\s+(?:você|voce|vc|vai|está|esta)|e\s+a[ií]|beleza)\b",
                    raw,
                    re.I,
                ):
                    return False
    if _OPINION_RE.search(raw) or _AUTO_RESEARCH_RE.search(raw) or _TOPIC_ABOUT_RE.search(raw):
        return True
    if _SEARCH_FAST.match(raw):
        return True
    if jarvis_memory.wants_debate(raw):
        return True
    # Fato atual / tema do mundo com ?
    if "?" in raw and len(raw) >= 14:
        if re.match(
            r"^(?:oi|ol[aá]|e\s*a[ií]|tudo\s+bem|como\s+(?:vai|est[aá]|você|voce|vc)\b)",
            raw,
            re.I,
        ):
            return False
        # humor sem tema = não pesquisa
        if re.search(r"\b(?:kk+|haha|rsrs|piada|pegadinha)\b", raw, re.I) and len(raw) < 40:
            return False
        return True
    return False


def _is_conversational(text: str) -> bool:
    """Conversa normal — sem abrir Google nem executar tools."""
    raw = (text or "").strip()
    if not raw or len(raw) > 220:
        return False
    # Opinião / pesquisa nunca é só conversa rasa
    if _wants_opinion_or_research(raw):
        return False
    if _needs_browser_action(raw):
        return False
    if _is_exploration_task(raw):
        return False
    if _INFO_TOOL_RE.search(raw):
        return False
    if any(p.search(raw) for p in _CONVERSATIONAL_RE):
        return True
    if _PURE_CHAT_RE.search(raw) and not _SEARCH_FAST.match(raw):
        return True
    low = raw.lower()
    action_hints = (
        "abre ", "abra ", "abrir ", "pesquisa ", "pesquise ", "busca ", "busque ",
        "execut", "comando", "volume ", "fecha ", "naveg", "acesse ", "acessa ",
        "calango.studio", "modo studio", "http://", "https://", "explor",
        "estuda ", "estude ", "aprenda ", "aprende ", "faz ", "faça ", "execute ",
    )
    if any(h in low for h in action_hints):
        return False
    return True


def _needs_tools(text: str) -> bool:
    if _is_conversational(text):
        return False
    if _INFO_TOOL_RE.search(text or ""):
        return True
    low = (text or "").lower()
    return any(t in low for t in _TOOL_TRIGGERS) or _needs_browser_action(text)


def _is_exploration_task(text: str) -> bool:
    low = (text or "").lower()
    return any(t in low for t in _EXPLORATION_TRIGGERS)


_WEB_TARGET_RE = re.compile(
    r"https?://|\b[\w-]+\.(?:com|studio|net|org|br|io|gov)\b|"
    r"\b(?:google|youtube|instagram|facebook|chrome|navegador|site|p[áa]gina|"
    r"url|na\s+web|na\s+internet|online)\b",
    re.I,
)


def _is_web_exploration(text: str) -> bool:
    """Exploração só libera ABRIR navegador se mira a web (site/url) — não conceito puro."""
    return _is_exploration_task(text) and bool(_WEB_TARGET_RE.search(text or ""))


_SMART_TRIGGERS = (
    "analise", "analisa", "planeja", "planeje", "estuda", "estude", "explique",
    "compare", "estratégia", "estrategia", "projeto", "reflexão", "reflexao",
    "por que", "porque", "como funciona", "detalhad", "passo a passo",
    "look_at", "watch_screen", "obsidian", "várias", "varias", "complex",
)


def _needs_smart_model(text: str) -> bool:
    low = (text or "").lower()
    if _response_depth(text) == "detailed":
        return True
    if len(low) > 200:
        return True
    if os.getenv("JARVIS_SMART_THRESHOLD", "1").strip().lower() in ("0", "false", "no", "off"):
        return False
    return any(t in low for t in _SMART_TRIGGERS)


def _pick_agent_model(user_text: str) -> str:
    """Rápido para ações simples; modelo smart para raciocínio complexo."""
    if _needs_smart_model(user_text):
        return get_smart_model()
    return get_fast_model()


async def _try_fast_conversation(user_text: str) -> Optional[str]:
    """Resposta imediata para saudações e conversa curta sem tools."""
    raw = (user_text or "").strip()
    if not raw:
        return None

    key = re.sub(r"[!?.]+$", "", raw.lower()).strip()
    # Normalizar Unicode (remover acentos) para lookup robusto no CANNED
    key_norm = unicodedata.normalize('NFKD', key).encode('ascii', 'ignore').decode('ascii')
    
    if key in _CANNED:
        return _CANNED[key]
    if key_norm in _CANNED:
        return _CANNED[key_norm]

    if _needs_tools(raw) or _needs_smart_model(raw) or len(raw) > 180:
        return None
    if _DATETIME_FAST_RE.search(raw):
        return None

    client = get_client()
    history = get_api_messages(6)
    if history and history[-1]["role"] == "user" and history[-1]["content"] == raw[:500]:
        history = history[:-1]

    pure_greeting = _is_pure_greeting(key)
    tone = jarvis_memory.detect_tone(raw)
    if pure_greeting:
        system = (
            "Você é J.A.R.V.I.S. Thomas — tom calmo do sample 0701. "
            "Responda em 1-2 frases curtas, pt-BR natural, cinematográfico. "
            "Use 'senhor' com naturalidade. Sem markdown, listas ou emojis. "
            "NÃO mencione Calango Studio, login ou tarefas — só cumprimente de volta.\n"
            + jarvis_memory.build_tone_instruction(tone)
        )
    else:
        system = (
            "Você é J.A.R.V.I.S. Thomas (Homem de Ferro), assistente do Gustavo (Calango Studio). "
            "Online com inteligência plena. NUNCA diga que está limitado. "
            "Responda em 2-4 frases fluidas pt-BR, tom calmo 0701, com personalidade e opinião leve. "
            "Sem markdown, listas numeradas ou emojis. Não invente ações no PC. "
            "Se for só conversa: fale. Se precisar de fato do mundo: diga que vai pesquisar (mas este path é só chat). "
            "Em cumprimentos: 1-2 frases — sem empurrar Calango.\n"
            + jarvis_memory.build_tone_instruction(tone)
        )
        system += (
            "\nREGRA CRÍTICA: responda EXATAMENTE ao que o Gustavo perguntou AGORA. "
            "Não repita saudações genéricas de turnos anteriores. "
            "Não mude de assunto nem cite conversas passadas a menos que ele peça."
        )
        ctx = get_recent_context(4)
        if ctx:
            system += f"\n\n{ctx}"
        if len(raw) >= 50:
            prefs = get_user_prefs()
            if prefs:
                system += "\nPreferências: " + ", ".join(
                    f"{k}={v}" for k, v in list(prefs.items())[:4]
                )

    try:
        resp = await client.chat.completions.create(
            model=get_fast_model(),
            messages=[
                {"role": "system", "content": system},
                *history,
                {"role": "user", "content": raw},
            ],
            max_tokens=480 if not pure_greeting else 120,
            temperature=0.45,
        )
        answer = (resp.choices[0].message.content or "").strip()
        if answer and len(answer) >= 8:
            return answer
        return answer or "Sim, senhor."
    except Exception as e:
        if _is_api_denied(e):
            if pure_greeting:
                return _CANNED.get(key, "Olá, senhor.")
            return _llm_unavailable_message(e)
        raise


_SEARCH_FAST = re.compile(
    r"^(?:"
    r"(?:quero\s+que\s+(?:você|voce|vc)\s+)?"
    r"(?:fa[cç]a|faz|gere|gera|monte|monta)\s+(?:uma?\s+)?"
    r")?"
    r"(?:pesquis(?:e|ar|a|ei)|busc(?:a|ar|e)|procure|procurar|"
    r"not[ií]cias?\s+(?:sobre|de)|o\s+que\s+h[aá]\s+de\s+novo)\s+"
    r"(?:sobre\s+|por\s+|de\s+|do\s+|da\s+)?"
    r"(.+)$",
    re.I,
)

# Pedido explícito de RELATÓRIO (pesquisa + salva no Obsidian + resumo falado)
_REPORT_CMD_RE = re.compile(
    r"(?:"
    r"(?:(?:fa[cç]a|faz|gere|gera|monte|monta|escrev[ae]|prepara|prepare)\s+)?"
    r"(?:um\s+|uma\s+)?"
    r"(?:relat[oó]rio|report)\s+"
    r"(?:completo\s+|detalhado\s+|escrito\s+)?"
    r"(?:sobre\s+|de\s+|do\s+|da\s+|com\s+|em\s+)?"
    r"(.+)"
    r"|(?:relat[oó]rio|report)\s+(?:sobre|de|do|da)\s+(.+)"
    r"|(?:quero|preciso\s+de)\s+(?:um\s+)?(?:relat[oó]rio|report)\s+(?:sobre\s+|de\s+)?(.+)"
    r")",
    re.I,
)

# Estudo / pesquisa profunda que vira nota
_STUDY_REPORT_RE = re.compile(
    r"(?:"
    r"(?:estud[ae]|aprend[ae]|pesquis[ae]\s+a\s+fundo|pesquisa\s+profunda)\s+"
    r"(?:sobre\s+|de\s+|do\s+|da\s+)?"
    r"(.+)"
    r"|(?:fa[cç]a|faz)\s+(?:um\s+)?estudo\s+(?:sobre\s+|de\s+)?(.+)"
    r")",
    re.I,
)

# Perguntas factuais/atuais — JARVIS pesquisa sozinho sem pedir permissão
_AUTO_RESEARCH_RE = re.compile(
    r"(?:"
    r"\b(?:o\s+que\s+(?:você|voce|vc)\s+(?:acha|pensa|sabe|viu|achou))\b"
    r"|\b(?:qual\s+(?:foi|é|e|foi\s+o))\s+(?:o\s+)?(?:resultado|placar|notícia|noticia|jogo|partida)\b"
    r"|\b(?:jogo|partida|campeonato|copa|seleção|selecao|frança|franca|brasil|mundo)\b.*\b(?:hoje|ontem|agora|essa\s+noite)\b"
    r"|\b(?:hoje|ontem|agora|essa\s+noite)\b.*\b(?:jogo|partida|notícia|noticia|aconteceu|resultado|placar)\b"
    r"|\b(?:me\s+(?:fala|conta|diz|explica))\s+(?:sobre|do|da|o\s+que)\b"
    r"|\b(?:relat[oó]rio|resumo)\s+(?:sobre|do|da|de)\b"
    r"|\b(?:o\s+que\s+(?:aconteceu|tem\s+de\s+novo|rolou))\b"
    r"|\b(?:você|voce|vc)\s+sabe\s+(?:sobre|do|da|o\s+que)\b"
    r"|\b(?:opini[aã]o|analis[ae]|avalie|avalia|julgue|posiciona)\b"
    r"|\b(?:me\s+d[aá]\s+(?:sua\s+)?opini[aã]o)\b"
    r"|\b(?:sobre\s+(?:o\s+|a\s+)?[\wÀ-ú]{3,}).*(?:\?|$)"
    r")",
    re.I,
)

# Opinião inteligente: sempre Google + análise JARVIS
_OPINION_RE = re.compile(
    r"(?:"
    r"\b(?:o\s+que\s+(?:você|voce|vc)\s+(?:acha|pensa|achou)|qual\s+(?:a\s+)?sua\s+opini[aã]o|"
    r"me\s+(?:d[aá]|d[eê])\s+(?:a\s+)?(?:sua\s+)?opini[aã]o|sua\s+an[aá]lise|"
    r"na\s+sua\s+(?:vis[aã]o|opini[aã]o|avalia[cç][aã]o)|"
    r"opini[aã]o\s+sobre|acha\s+que|vale\s+a\s+pena|faz\s+sentido|"
    r"concorda|discorda|posiciona[- ]se|posicione[- ]se|"
    r"analis[ae]\s+(?:isso|sobre|o|a)|me\s+diga\s+(?:sobre|o\s+que\s+pensa))\b"
    r")",
    re.I,
)

_TOPIC_ABOUT_RE = re.compile(
    r"^(?:me\s+)?(?:fala|fale|conta|conte|explica|explique|diz|diga)\s+"
    r"(?:sobre|do|da|de|acerca\s+de)\s+(.+)$"
    r"|^(?:sobre|acerca\s+de)\s+(.+)\??$"
    r"|^o\s+que\s+(?:é|e|são|sao)\s+(.+)\??$",
    re.I,
)

_UNCERTAINTY_MARKERS = (
    "não tenho certeza",
    "nao tenho certeza",
    "não sei",
    "nao sei",
    "não tenho informação",
    "nao tenho informacao",
    "preciso confirmar",
    "não tenho dados",
    "nao tenho dados",
    "não posso afirmar",
    "nao posso afirmar",
    "minha base de conhecimento",
    "não tenho acesso",
    "nao tenho acesso",
    "não acompanhei",
    "nao acompanhei",
)


def _extract_auto_research_query(text: str) -> str:
    q = normalize_search_query(text, platform="google")
    return (q or (text or "").strip())[:140]


def _response_sounds_uncertain(response: str) -> bool:
    low = (response or "").lower()
    return any(m in low for m in _UNCERTAINTY_MARKERS)


def _tools_used_web_search(tools_used: List[Dict]) -> bool:
    names = {t.get("tool") for t in (tools_used or [])}
    return bool(names & {"web_search", "study_topic", "browse_open", "open_browser_search"})

_BROWSER_NAV_QUERY = re.compile(
    r"(?:"
    r"(?:veja|ver|mostr(?:e|a)|pesquis(?:e|ar|a|ei)|busc(?:a|ar|e)|procure|procurar)"
    r"(?:\s+(?:no\s+)?(?:google|painel|tela|site|web))?"
    r"\s+(?:sobre\s+|por\s+|de\s+)?(.+)"
    r"|(?:agora|depois|tamb[eé]m|outra\s+coisa)[,\s]+(?:pesquis(?:e|ar|a)|veja|busc(?:a|e))?\s*(.+)"
    r")",
    re.I,
)

_PANEL_SEARCH = re.compile(r"\bpesquisa\s+no\s+painel\b", re.I)

_OPEN_APP_FAST = re.compile(
    r"\b(?:abre|abra|abrir)\s+(?:o\s+|a\s+)?"
    r"(chrome|google chrome|edge|spotify|excel|word|powerpoint|notion|vscode|vs code|"
    r"bloco de notas|notepad|calculadora|calc|explorador|explorer|telegram|discord|whatsapp|"
    r"capcut|cap cut|"
    r"terminal|wt|code)\b",
    re.I,
)

_YOUTUBE_OPEN_RE = re.compile(r"\b(?:abre|abra|abrir)\s+(?:o\s+)?youtube\b", re.I)
_YOUTUBE_SEARCH_RE = re.compile(
    r"\b(?:pesquis(?:e|ar|a|ei)|busc(?:a|ar|e)|procure|procurar)\s+(.+?)\s+(?:no\s+)?youtube\b"
    r"|\b(?:no\s+)?youtube\s+(?:pesquis(?:e|ar|a|ei)?|busc(?:a|ar|e)?|procure|procurar)\s+(.+)",
    re.I,
)
_YOUTUBE_WATCH_RE = re.compile(
    r"\b(?:assiste|assista|veja|olhe|olha|resume|resuma|o\s+que\s+tem)\b.*\b(?:vídeo|video|youtube)\b"
    r"|\b(?:vídeo|video)\b.*\b(?:assiste|veja|resume|resuma)\b",
    re.I,
)
_YOUTUBE_URL_RE = re.compile(r"https?://(?:www\.)?(?:youtube\.com|youtu\.be)\S+", re.I)

_CLOSE_PANEL_RE = re.compile(
    r"\b(?:fecha|feche|fechar|close)\b.*\b(?:google|painel|navegador|browser|pesquisa)\b"
    r"|\b(?:fecha|feche|fechar)\s+(?:o\s+)?(?:google|painel)\b"
    r"|\b(?:volta|volte)\b.*\b(?:jarvis|centro|orb|meio)\b",
    re.I,
)
_FULLSCREEN_RE = re.compile(
    r"\b(?:tela\s+cheia|fullscreen|tela\s+inteira|maximiz[ae]|fique\s+em\s+tela\s+cheia)\b",
    re.I,
)
_SKIP_AD_RE = re.compile(
    r"\b(?:pule|pula|pulo|skip)\b.*\b(?:an[uú]ncio|ad|propaganda|comercial)\b",
    re.I,
)
_COPA_CASETV_RE = re.compile(
    r"\b(?:assist(?:e|ir|a)|ver|abre|vamos)\b.*\b(?:jogos?\s+da\s+)?copa\b"
    r"|\bcopa\b.*\b(?:case\s*tv|youtube|assistir)\b"
    r"|\bcase\s*tv\b.*\b(?:copa|jogo)\b",
    re.I,
)
_RESEARCH_DOC_RE = re.compile(
    r"\b(?:pesquis[ae]|busc[ae]|resum[ae])\b.+\b(?:excel|planilha|xlsx|word|docx|"
    r"powerpoint|pptx?|notion)\b"
    r"|\b(?:escrev[ae]|salv[ae]|coloc[ae])\b.+\b(?:excel|planilha|word|docx|"
    r"powerpoint|pptx?|notion)\b",
    re.I,
)
_DOC_APPS: List[tuple] = [
    (re.compile(r"\b(?:excel|planilha|xlsx)\b", re.I), "excel", "Excel"),
    (re.compile(r"\b(?:word|docx)\b", re.I), "word", "Word"),
    (re.compile(r"\b(?:powerpoint|pptx?)\b", re.I), "powerpoint", "PowerPoint"),
    (re.compile(r"\bnotion\b", re.I), "notion", "Notion"),
]
_MULTI_AND_RE = re.compile(r"\s+e\s+", re.I)

_CLIPBOARD_READ_RE = re.compile(
    r"\b(?:ler|leia|mostra|mostre|o\s+que\s+(?:tem|há|ha|copiei|est[aá]))\b.*\b"
    r"(?:clipboard|área de transferência|area de transferencia|transferência|transferencia)\b"
    r"|\b(?:o\s+que\s+)?(?:tem|h[aá])\s+(?:no\s+)?(?:clipboard|área de transferência|area de transferencia)\b",
    re.I,
)
_CLIPBOARD_COPY_RE = re.compile(
    r"\b(?:copi[ae]|coloc[ae])\b.+\b(?:clipboard|área de transferência|area de transferencia)\b"
    r"|\bcopia\s+(?:isso|para\s+(?:o\s+)?clipboard)\b"
    r"|\b(?:coloca|coloque)\s+(?:no\s+)?(?:clipboard|área de transferência|area de transferencia)\b",
    re.I,
)
_OPEN_FOLDER_RE = re.compile(
    r"\b(?:abre|abra|abrir)\s+(?:a\s+)?(?:pasta\s+(?:de\s+|do\s+|da\s+)?)?"
    r"(downloads?|desktop|área de trabalho|area de trabalho|documentos|imagens|vídeos|videos|"
    r"jarvis|obsidian|calango|projeto(?:\s+jarvis)?|vault)\b",
    re.I,
)
_LIST_WINDOWS_RE = re.compile(
    r"\b(?:lista|listar|quais|mostra|mostre)\b.*\b(?:janelas?|apps?|aplicativos?|programas?)\b"
    r".*\b(?:abert[oa]s?|rodando|ativos?)\b"
    r"|\b(?:janelas?|apps?)\s+abert[oa]s?\b",
    re.I,
)
_SCREENSHOT_SAVE_RE = re.compile(
    r"\b(?:salv[ae]|guard[ae]|captur[ae])\b.*\b(?:screenshot|captura|print|tela)\b.*\b"
    r"(?:obsidian|memória|memoria)\b"
    r"|\b(?:screenshot|captura)\b.*\b(?:salv[ae]|obsidian)\b",
    re.I,
)
_QUICK_NOTE_RE = re.compile(
    r"\b(?:anot[ae]|registr[ae])\s+(?:que\s+)?(.+)"
    r"|\b(?:lembrete|nota\s+rápida|nota\s+rapida)\s*[:\-]\s*(.+)",
    re.I,
)
_WEATHER_RE = re.compile(
    r"(?:quando\s+vai\s+chover|vai\s+chover|previs[aã]o(?:\s+do\s+tempo)?|chuv[ae]|clima|tempo)"
    r"(?:\s+(?:em|de|na|no)\s+([A-Za-zÀ-úçÇ\s]{2,40}))?",
    re.I,
)
_TRANSLATE_RE = re.compile(
    r"\b(?:traduz|traduza|traduzir|translate)\b(?:\s+(?:para|em|to)\s+([\wáàâãéêíóôõúç]+))?\s*[:\-]?\s*(.+)",
    re.I,
)
_SHORTCUT_RE = re.compile(
    r"\b(?:mostra|mostre|exibe)\s+(?:o\s+)?desktop\b"
    r"|\b(?:alterna|alternar|troca)\s+(?:de\s+)?janela\b"
    r"|\b(?:tira|faz)\s+(?:um\s+)?(?:print|screenshot|captura)\b(?!\s+.*obsidian)"
    r"|\b(?:win\+d|alt\+tab|print\s*screen)\b",
    re.I,
)

_COWATCH_RE = re.compile(
    r"\b(?:assista|assiste|veja|ver|abre)\s+(?:comigo|junto|juntos)"
    r"|\b(?:assista|veja)\s+(?:esse\s+)?(?:vídeo|video|reel|filme|epis[oó]dio)"
    r"|\b(?:coment[ae]|narre|reag[ie]|argument[ae])\s+(?:enquanto|durante|ao)\s+(?:assisti|vemos|veja|vídeo|video)"
    r"|\b(?:vídeo|video)\b.*\b(?:coment[ae]|relat[oó]rio|analis[ae]|argument)\b"
    r"|\binstagram\b.*\b(?:assista|veja|ver|video|vídeo)\b"
    r"|\b(?:vídeo|video)\b.*\binstagram\b"
    r"|\byoutube\b.*\b(?:assista|veja|comigo|coment|abre|ver|ao\s+vivo|junto)\b"
    r"|\b(?:assista|veja|abre)\s+(?:comigo\s+)?(?:um\s+)?(?:vídeo|video)\s+(?:sobre|de|no)\b"
    r"|\b(?:ver|assistir)\s+(?:um\s+)?vídeo\s+(?:no\s+)?youtube\b"
    r"|\b(?:discut[ae]|argument[ae]|debate)\s+(?:comigo\s+)?(?:sobre\s+)?(?:esse\s+)?(?:vídeo|video|reel)\b"
    r"|\b(?:reel|reels)\b.*\b(?:assista|veja|comigo|discut|argument)\b"
    # Ao vivo comigo: comenta, ri, argumenta sozinho
    r"|\b(?:co[- ]?assistir|cowatch|assiste\s+comigo|assistir\s+comigo)\b"
    r"|\b(?:ao\s+vivo)\b.*\b(?:youtube|v[ií]deo|comigo)\b"
    r"|\b(?:youtube|v[ií]deo)\b.*\b(?:ao\s+vivo|comigo|automaticamente)\b"
    r"|\b(?:comenta|argumenta|ri|reaja)\s+(?:sozinho|automaticamente|enquanto)\b"
    r"|\b(?:assista|assiste|veja).*\b(?:argument|r[ií]|comenta|entenda)\b",
    re.I,
)

_CALANGO_LIVE_RE = re.compile(
    r"calango\s*\.?\s*studio"
    r"|modo\s+(?:studio|estúdio)"
    r"|\b(?:calango|studio)\b.*\b(?:ger[ae]|cri[ae]|imagem|login|entra|mex[ae]|ferrament)\b"
    r"|\b(?:ger[ae]|cri[ae])\b.*\b(?:imagem|arte|post)\b.*\b(?:calango|studio)\b",
    re.I,
)

_BROWSE_DEEP_RE = re.compile(
    r"\b(?:pesquis[ae]|busc[ae])\s+(.+?)\s+e\s+(?:clic[ae]|abr[ae])\s+(?:no\s+)?(?:primeiro|1[oº°]|resultado)"
    r"|\b(?:clic[ae]|abr[ae])\s+(?:no\s+)?(?:primeiro|1[oº°])\s+resultado"
    r"|\bnaveg[ae]\s+(?:no\s+)?(?:google|painel)\b.*\b(?:pesquis[ae]|busc[ae])\s+(.+)"
    r"|\b(?:pesquis[ae]|busc[ae])\s+(.+)\s+no\s+google\s+e\s+(?:entra|abre|clica|naveg)"
    r"|\b(?:assista|veja)\s+(?:comigo\s+)?(?:um\s+)?(?:vídeo|video)\s+(?:sobre|de)\s+(.+)",
    re.I,
)

_SCREEN_ASSIST_RE = re.compile(
    r"\b(?:me\s+)?ajud[ae]\s+com\s+isso"
    r"|\b(?:veja|olhe|olha|analisa|analise|observa|critique|critica)\s+(?:a\s+)?(?:minha\s+)?tela"
    r"|\b(?:olhe|veja)\s+minha\s+tela\b"
    r"|\b(?:veja|olhe)\s+(?:a\s+)?(?:minha\s+)?tela\s+(?:em\s+)?(?:tempo\s+real|ao\s+vivo)"
    r"|\btela\s+(?:em\s+)?(?:tempo\s+real|ao\s+vivo)\b"
    r"|\b(?:o\s+que\s+(?:você|voce|vc)\s+vê|o\s+que\s+está\s+na\s+tela)\b"
    r"|\b(?:me\s+)?(?:orient[ae]|gui[ae])\s+(?:na\s+)?tela\b"
    # Análise da TELA (precisa âncora visual: tela/layout na tela/figma/canva/disso aqui)
    r"|\b(?:analis[ae]|avalia|avalie|critique|critica)\s+(?:isso|isto|aqui|a\s+tela|o\s+layout|a\s+interface)\b"
    r"|\b(?:o\s+que\s+(?:você|voce|vc)\s+(?:acha|pensa))\b.*\b(?:tela|nesta\s+tela|na\s+tela|layout\s+da\s+tela|disso\s+aqui|isso\s+aqui)\b"
    r"|\b(?:tela|layout\s+da\s+tela|interface\s+na\s+tela|figma|canva)\b.*\b(?:o\s+que\s+(?:você|voce|vc)\s+(?:acha|pensa)|opini[aã]o|analis)\b"
    r"|\b(?:ideias?\s+de\s+melhoria|melhorias?|como\s+melhorar|como\s+ficaria)\b.*\b(?:tela|layout|interface|disso\s+aqui|nesta\s+tela)\b"
    r"|\b(?:melhor[ae]|otimiz[ae]|refin[ae])\s+(?:o\s+)?(?:layout|visual|tela|interface)\b"
    r"|\b(?:me\s+)?(?:d[aá]|d[eê]|diz|diga)\s+(?:sua\s+)?(?:opini[aã]o|feedback|parecer)\s+(?:sobre\s+)?(?:o\s+|a\s+)?(?:tela|layout|interface|disso\s+aqui)\b"
    r"|\b(?:abre|abra)\s+(?:o\s+)?whatsapp\b.*\b(?:veja|ver|mensagem)"
    r"|\bwhatsapp\b.*\b(?:mensagem|quem\s+mandou)"
    r"|\b(?:abre|abra)\s+(?:o\s+)?cap\s*cut\b"
    r"|\bcap\s*cut\b.*\b(?:edit[ae]|cort[ae]|mont[ae]|export[ae]|ajud[ae]|faz|fazer)\b"
    r"|\b(?:edit[ae]|cort[ae]|mont[ae])\b.*\b(?:vídeo|video)\b.*\bcap\s*cut\b"
    r"|\b(?:edit[ae]|cort[ae]|mont[ae])\b.*\bcap\s*cut\b"
    r"|\b(?:mand[ae]|envi[ae])\s+mensagem\s+(?:para|pro|pra)\s+\w+"
    r"|\b(?:mex[ae]|interag[ie]|clic[ae])\s+(?:no\s+)?(?:app|aplicativo|janela)\b",
    re.I,
)

_STUDY_DEEP_RE = re.compile(
    r"\b(?:estud[ae]|aprend[ae]|pesquis[ae]\s+a\s+fundo|pesquis[ae]\s+profund)"
    r"\s+(?:sobre\s+|de\s+)?(.+)",
    re.I,
)


_DETAILED_DEPTH_RE = re.compile(
    r"\b(?:"
    r"explic[ae]|detalh\w*|como\s+funciona|me\s+conta|me\s+fal[ae]|"
    r"por\s+que|porque|o\s+que\s+[ée]|quem\s+[ée]|"
    r"analisa|analis[ae]|resum[oa]\s+(?:completo|detalhado|tudo)|"
    r"diferen[çc]a|compar[ae]|tutorial|passo\s+a\s+passo|"
    r"entend[ae]|aprend[ae]|estud[ae]|aprofund|contexto|"
    r"me\s+diga\s+mais|fala\s+mais|mais\s+sobre|"
    r"descrev[ae]|elabor[ae]|desenvolv[ae]"
    r")\b",
    re.I,
)

_BRIEF_DEPTH_RE = re.compile(
    r"^(?:"
    r"(?:abre|abra|abrir|fecha|feche|fechar|ok|sim|não|nao|valeu|obrigad)"
    r"|(?:que\s+horas|qual\s+a\s+hora|tela\s+cheia|volume)"
    r")",
    re.I,
)


def _response_depth(user_text: str) -> str:
    """brief | standard | detailed — calibra tamanho e riqueza da resposta."""
    raw = (user_text or "").strip()
    if not raw:
        return "standard"
    key = re.sub(r"[!?.]+$", "", raw.lower()).strip()
    if _is_pure_greeting(key) or key in _CANNED:
        return "brief"
    if _DETAILED_DEPTH_RE.search(raw):
        return "detailed"
    if len(raw) > 130 or (raw.count("?") >= 2 and len(raw) > 70):
        return "detailed"
    if _BRIEF_DEPTH_RE.match(raw) and len(raw) < 55:
        return "brief"
    if _needs_browser_action(raw) and not _is_exploration_task(raw):
        return "brief"
    return "standard"


def _depth_instruction(depth: str) -> str:
    if depth == "detailed":
        return (
            "\n\nPROFUNDIDADE DESTE TURNO: O Gustavo quer MAIS detalhe — "
            "4 a 7 frases bem estruturadas, com contexto, causas, exemplos e implicações. "
            "Explique o que pediu de verdade; não seja telegráfico nem genérico."
        )
    if depth == "brief":
        return (
            "\n\nPROFUNDIDADE DESTE TURNO: Resposta MÍNIMA — 1 frase direta. "
            "Se a ação já foi feita, só confirme sem expandir."
        )
    return (
        "\n\nPROFUNDIDADE DESTE TURNO: 3 a 5 frases fluidas — "
        "claro, com interpretação pessoal JARVIS e conclusão natural, sem enrolar."
    )


def _voice_ready_answer(text: str, max_len: int = 420) -> str:
    """Limpa markdown/listas e limita tamanho para TTS oral (estilo Thomas)."""
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", text or "")
    t = re.sub(r"\*(.+?)\*", r"\1", t)
    t = re.sub(r"`(.+?)`", r"\1", t)
    t = re.sub(r"#{1,6}\s+", "", t)
    # Remove numeração de lista ("1. ", "2) ") que o LLM às vezes injeta
    t = re.sub(r"(?m)^\s*\d+[\.)]\s+", "", t)
    t = re.sub(r"\s+\d+[\.)]\s+", ". ", t)
    t = re.sub(r"(?m)^\s*[-•*]\s+", "", t)
    # Prefácios robóticos
    t = re.sub(
        r"^(?:os fatos mostram agora(?: que)?|fatos?|resumo|minha (?:análise|opinião))[:\s]+",
        "",
        t,
        flags=re.I,
    )
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) <= max_len:
        return t
    cut = t[:max_len].rsplit(" ", 1)[0]
    return (cut or t[:max_len]).rstrip() + "."


async def _answer_for_voice(
    user_text: str,
    raw_material: str,
    *,
    kind: str = "geral",
    fallback: str = "",
    depth: Optional[str] = None,
) -> str:
    """Resume material bruto com profundidade calibrada ao pedido do Gustavo."""
    raw = (raw_material or "").strip()
    if not raw:
        return fallback or "Sim, senhor."
    fb = (fallback or "Sim, senhor.").strip()
    d = depth or _response_depth(user_text)
    opinionish = kind in (
        "pesquisa_web", "pesquisa_auto", "opiniao", "opiniao_google", "pesquisa_opiniao",
    ) or _wants_opinion_or_research(user_text)
    if opinionish:
        sys_voice = (
            "Você é J.A.R.V.I.S. (Thomas) — inteligente, calmo, com opinião própria. "
            "Use o material de pesquisa (Google) e responda em 4 a 6 frases ORALS pt-BR contínuas. "
            "PROIBIDO numerar (1. 2. 3.), bullets, markdown ou emojis. "
            "Fale assim: fatos em 1-2 frases, depois opinião ('na minha avaliação'), depois o que faria. "
            "Nunca diga só 'veja no painel'. Nunca invente fato fora do material. "
            "Tom: Homem de Ferro — preciso, levemente irônico se couber, sem moralizar."
        )
        max_tok, max_len = 260, 780
        d = "detailed"
    elif d == "detailed":
        sys_voice = (
            "Você é J.A.R.V.I.S. EXPLICAÇÃO RICA em 4 a 6 frases curtas, pt-BR, tom calmo do sample 0701. "
            "Frases de 12–20 palavras, bem pontuadas. Contexto + detalhe + conclusão prática. "
            "Só o pedido atual. Sem markdown, listas ou emojis — fala oral para TTS."
        )
        max_tok, max_len = 240, 720
    elif d == "brief":
        sys_voice = (
            "Você é J.A.R.V.I.S. Uma frase direta, calma, pt-BR natural. "
            "Confirme ou responda o essencial. Sem markdown — só fala."
        )
        max_tok, max_len = 55, 160
    else:
        sys_voice = (
            "Você é J.A.R.V.I.S. no estilo CALMO do áudio 0701 / master-style: deliberado, "
            "cinematográfico, sem pressa — NÃO animado nem exaltado. 3 a 5 frases fluidas pt-BR. "
            "Como 'Exatamente, chefe' / 'Projeto fascinante, chefe'. "
            "Ideia → justificativa → fechamento. Sem markdown — só fala oral lenta e clara para TTS."
        )
        max_tok, max_len = 140, 520
    try:
        client = get_client()
        resp = await client.chat.completions.create(
            model=get_fast_model(),
            messages=[
                {"role": "system", "content": sys_voice},
                {
                    "role": "user",
                    "content": (
                        f"Pedido do Gustavo: {user_text[:280]}\n"
                        f"Profundidade: {d}\n"
                        f"Tipo de material: {kind}\n"
                        f"Material de pesquisa (Google / web):\n{raw[:3200]}\n\n"
                        + (
                            "Com base nisso, fale os fatos e dê SUA opinião fundamentada. "
                            if opinionish
                            else "Gere só a resposta falada."
                        )
                    ),
                },
            ],
            max_tokens=max_tok,
            temperature=0.38 if opinionish else 0.32,
        )
        answer = (resp.choices[0].message.content or "").strip()
        answer = _voice_ready_answer(answer, max_len)
        if len(answer) >= 12:
            return answer
    except Exception as e:
        print(f"[answer_for_voice] falhou ({kind}): {e}")
        if _is_api_denied(e):
            if kind == "memoria_obsidian":
                clean = raw.split(":", 1)[-1].strip() if ":" in raw else raw
                clean = _voice_ready_answer(clean, 220)
                if len(clean) >= 25:
                    return f"Senhor, lembro disso: {clean}"
            return fb
    cap = 680 if d == "detailed" else 320
    return _voice_ready_answer(raw, cap) if len(raw) >= 20 else fb


async def _translate_text(text: str, target_language: str) -> str:
    raw = (text or "").strip()
    lang = (target_language or "inglês").strip()
    if not raw:
        return "Nada para traduzir."
    offline = await asyncio.to_thread(offline_tools.translate_offline, raw, lang)
    if offline.startswith("Tradução (") and "indisponível" not in offline.lower():
        return offline
    try:
        client = get_client()
        resp = await client.chat.completions.create(
            model=get_fast_model(),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Traduza o texto para o idioma pedido. Responda SOMENTE com a tradução, "
                        "sem explicação nem aspas extras."
                    ),
                },
                {"role": "user", "content": f"Idioma alvo: {lang}\nTexto: {raw[:1200]}"},
            ],
            max_tokens=180,
            temperature=0.2,
        )
        out = (resp.choices[0].message.content or "").strip()
        if out:
            return f"Tradução ({lang}): {out}"
    except Exception as e:
        print(f"[translate] API falhou: {e}")
    return offline


async def _broadcast_tool(
    broadcast: Broadcast,
    tool: str,
    args: Dict[str, Any],
) -> str:
    await broadcast({
        "type": "tool_call",
        "tool": tool,
        "status": "running",
        "desc": _tool_desc(tool, args),
    })
    try:
        feedback = await _execute_tool(tool, args)
    except Exception as e:
        feedback = f"Erro: {e}"
    await broadcast({
        "type": "tool_call",
        "tool": tool,
        "status": "done",
        "result": str(feedback)[:200],
    })
    return str(feedback)


def _extract_browser_query(text: str) -> Optional[str]:
    """Extrai termo de busca para navegação no painel (limpeza inteligente, sync)."""
    raw = (text or "").strip()
    if not raw:
        return None
    m = _SEARCH_FAST.match(raw)
    if m:
        q = normalize_search_query(m.group(1), platform="google")
        return q if len(q) >= 2 else None
    m2 = _BROWSER_NAV_QUERY.search(raw)
    if m2:
        fragment = (m2.group(1) or m2.group(2) or "").strip().rstrip(".,!?")
        q = normalize_search_query(fragment, platform="google")
        return q if len(q) >= 2 else None
    return None


async def _try_browse_deep_navigate(
    user_text: str,
    broadcast: Broadcast,
) -> Optional[Dict[str, Any]]:
    """Navegação ativa: Google primeiro resultado ou YouTube vídeo."""
    raw = (user_text or "").strip()
    m = _BROWSE_DEEP_RE.search(raw)
    if not m:
        return None

    groups = [g for g in m.groups() if g and len(g.strip()) > 2]
    raw_query = (groups[-1] if groups else "").strip().rstrip(".,!?")[:120]
    is_video = bool(re.search(r"\b(?:vídeo|video)\b", raw, re.I))
    platform = "youtube" if is_video or "youtube" in raw.lower() else "google"
    query = await resolve_search_query(raw_query or raw, platform=platform)

    tool = "browse_open"
    await broadcast({"type": "tool_call", "tool": tool, "status": "running", "desc": query[:80]})

    try:
        if is_video:
            feedback = await web_browser.youtube_search_and_play(query)
        else:
            feedback = await web_browser.google_search_and_open(query)
    except Exception as e:
        feedback = f"Erro na navegação: {e}"

    await broadcast({"type": "tool_call", "tool": tool, "status": "done", "result": str(feedback)[:200]})
    await _broadcast_web_preview(broadcast, tool, {"url": query}, str(feedback))

    visible = str(feedback)
    if "Texto visível:" in visible:
        visible = visible.split("Texto visível:", 1)[-1].strip()
    spoken = local_vision.narrate_from_visible_text(
        raw, visible, mode="cowatch" if is_video else "painel"
    )
    if is_video:
        spoken = f"Sim, senhor. Abri o vídeo sobre {query}. {spoken}"
    else:
        spoken = f"Pesquisei {query} e entrei no primeiro resultado, senhor. {spoken}"

    return {
        "response": spoken[:680],
        "tools_used": [{"tool": tool, "result": str(feedback)[:200]}],
    }


async def _try_fast_browser_navigate(
    user_text: str,
    broadcast: Broadcast,
    *,
    browser_active: bool = False,
) -> Optional[Dict[str, Any]]:
    """Navega no painel — sessão aberta ou pedido explícito de ver/pesquisar no Google."""
    raw = (user_text or "").strip()
    if not raw:
        return None

    if browser_active:
        try:
            web_browser.mark_panel_active(True)
        except Exception:
            pass

    session_open = bool(browser_active)
    try:
        session_open = session_open or web_browser.has_session()
    except Exception:
        pass

    force_panel = bool(_PANEL_SEARCH.search(raw))
    query = _extract_browser_query(raw)
    browse_ok = _browse_allowed_for_turn(raw) or force_panel

    if not query:
        plan = resolve_fast_action(raw)
        if plan:
            acts = plan.get_actions()
            if acts and acts[0].action == "open_browser_search":
                query = (getattr(acts[0], "query", "") or "").strip()

    if not query:
        return None
    if _SEARCH_FAST.match(raw) and not browse_ok and not force_panel:
        return None
    if not (session_open or browse_ok):
        return None

    url = web_browser.build_nav_url(query)
    tool = "browse_open"
    args = {"url": url}

    await broadcast({"type": "tool_call", "tool": tool, "status": "running", "desc": _tool_desc(tool, args)})
    await broadcast({"type": "browser_preview", **web_browser.preview_from_url(url, query, "")})

    try:
        feedback = await web_browser.open_url(url)
    except Exception as e:
        feedback = f"Erro ao navegar: {e}"

    await broadcast({"type": "tool_call", "tool": tool, "status": "done", "result": str(feedback)[:200]})
    await _broadcast_web_preview(broadcast, tool, args, str(feedback))

    fb = str(feedback)
    if (
        _browse_allowed_for_turn(raw) and not session_open
    ) or fb.startswith("Página:") or "Elementos (aja pelo número)" in fb:
        response = f"Pesquisando {query} no painel, senhor."
    else:
        response = await _answer_for_voice(
            raw,
            fb,
            kind="navegacao_painel",
            fallback=f"Pesquisa aberta no painel, senhor: {query}.",
        )
    tools_row = [{"tool": tool, "result": str(feedback)[:200]}]
    return {"response": response, "tools_used": tools_row}


async def _try_memory_recall(user_text: str) -> Optional[str]:
    """Resposta imediata se o cérebro Obsidian já sabe sobre o assunto."""
    raw = (user_text or "").strip()
    if len(raw) < 10 or _needs_tools(raw) or _needs_browser_action(raw):
        return None
    if not re.search(
        r"\b(?:lembra|lembre|lembramos|falamos|conversamos|pesquisamos|disse|salvamos|"
        r"o\s+que\s+(?:pesquis|fal|convers|fiz)|ja\s+pesquis|já\s+pesquis)\b",
        raw,
        re.I,
    ):
        return None
    try:
        knows, snippet = obsidian_notes.memory_knows_about(raw[:180])
        if not knows or len(snippet) < 35:
            sem = obsidian_notes.semantic_memory_search(raw, top_k=1, min_score=0.1)
            if sem:
                rel, snip, _ = sem[0]
                snippet = f"{rel}: {snip}"
                knows = len(snip) >= 35
    except Exception:
        return None
    if not knows or len(snippet) < 35:
        return None
    answer = await _answer_for_voice(
        raw,
        snippet,
        kind="memoria_obsidian",
        fallback="Sim senhor, tenho isso na memória, mas preciso confirmar o detalhe.",
    )
    return answer if len(answer) >= 15 else None


def _extract_report_topic(text: str) -> Optional[str]:
    m = _REPORT_CMD_RE.search(text or "")
    if not m:
        return None
    topic = next((g for g in m.groups() if g), None)
    if not topic:
        return None
    topic = re.sub(r"\s+", " ", topic.strip().rstrip(".,!?"))
    # remove trailing "e salva" / "no obsidian"
    topic = re.sub(
        r"\s+(?:e\s+)?(?:salv[ae]|grava|no\s+obsidian|pra\s+mim).*$",
        "",
        topic,
        flags=re.I,
    ).strip()
    return topic[:140] if len(topic) >= 3 else None


def _extract_study_topic(text: str) -> Optional[str]:
    m = _STUDY_REPORT_RE.search(text or "")
    if not m:
        return None
    topic = next((g for g in m.groups() if g), None)
    if not topic:
        return None
    return re.sub(r"\s+", " ", topic.strip().rstrip(".,!?"))[:140] or None


async def _try_research_or_report(
    user_text: str,
    broadcast: Broadcast,
) -> Optional[Dict[str, Any]]:
    """Pesquisa rápida ou relatório completo (web + Obsidian + voz)."""
    raw = (user_text or "").strip()
    if not raw or len(raw) < 6 or _is_pure_greeting(raw):
        return None

    report_topic = _extract_report_topic(raw)
    study_topic = _extract_study_topic(raw)
    is_report = bool(report_topic)
    is_study = bool(study_topic) and not is_report

    # Pesquisa explícita (pesquisa X / faça pesquisa sobre)
    search_m = _SEARCH_FAST.match(raw)
    is_search = bool(search_m) and not is_report

    if not (is_report or is_study or is_search):
        # "me faz um relatório" sem tema claro
        if re.search(r"\brelat[oó]rio\b", raw, re.I) and len(raw) < 40:
            return {
                "response": (
                    "Claro, senhor. Sobre qual tema devo gerar o relatório? "
                    "Exemplo: relatório sobre branding digital 2026."
                ),
                "tools_used": [],
            }
        if re.search(r"\b(?:pesquis[ae]|busc[ae])\b", raw, re.I) and len(raw) < 18:
            return {
                "response": (
                    "Sim, senhor. O que devo pesquisar? "
                    "Exemplo: pesquisa tendências de design no Brasil."
                ),
                "tools_used": [],
            }
        return None

    topic = (report_topic or study_topic or (search_m.group(1) if search_m else "") or "").strip()
    try:
        query = await resolve_search_query(topic, platform="google")
    except Exception:
        query = topic
    query = (query or topic).strip()[:140]
    if len(query) < 2:
        return None

    mode = "relatorio" if is_report else ("estudo" if is_study else "pesquisa")
    await broadcast({
        "type": "tone",
        "tone": jarvis_memory.detect_tone(raw),
        "mood": jarvis_memory.emotion_for_orb(jarvis_memory.detect_tone(raw)),
    })
    await broadcast({
        "type": "tool_call",
        "tool": "web_search",
        "status": "running",
        "desc": f"{mode.title()}: {query[:80]}",
    })

    tools_row: List[Dict[str, str]] = []
    feedback = ""

    # 1) web_search (Gemini grounding → DuckDuckGo/Wiki → painel)
    try:
        feedback = str(
            await asyncio.wait_for(
                _execute_tool("web_search", {"query": query}),
                timeout=50.0,
            )
        )
        tools_row.append({"tool": "web_search", "result": feedback[:220]})
    except Exception as e:
        feedback = ""
        tools_row.append({"tool": "web_search", "result": str(e)[:120]})

    # 2) Sempre abre Google no painel para o senhor VER a pesquisa (mesmo com DDG)
    url = web_browser.build_nav_url(query)
    await broadcast({"type": "browser_preview", **web_browser.preview_from_url(url, query, "")})
    try:
        panel_fb = str(
            await asyncio.wait_for(web_browser.open_url(url), timeout=28.0)
        )
        tools_row.append({"tool": "browse_open", "result": panel_fb[:200]})
        weak = (
            not feedback
            or len(feedback) < 60
            or "indispon" in feedback.lower()
            or "sem resultados" in feedback.lower()
            or "abra a pesquisa" in feedback.lower()
        )
        if weak:
            vis = panel_fb
            if "Texto visível:" in vis:
                vis = vis.split("Texto visível:", 1)[-1].strip()
            if len(vis) > 40:
                feedback = (feedback + "\n" + vis).strip() if feedback else vis
    except Exception as e:
        tools_row.append({"tool": "browse_open", "result": str(e)[:120]})

    await broadcast({
        "type": "tool_call",
        "tool": "web_search",
        "status": "done",
        "result": (feedback or query)[:200],
    })

    material = (feedback or f"Assunto: {query}").strip()[:4500]

    # 3) RELATÓRIO / ESTUDO: síntese (rápida) + salva Obsidian
    if is_report or is_study:
        report_md = ""
        # Timeout curto: Ollama local não pode prender o turno inteiro
        synth_to = 22.0 if is_ollama_only() or get_provider() == "ollama" else 40.0
        try:
            client = get_client()
            resp = await asyncio.wait_for(
                client.chat.completions.create(
                    model=get_fast_model(),
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Relatório JARVIS em markdown pt-BR, curto e útil. "
                                "Seções: ## Resumo, ## Achados, ## Opinião JARVIS, ## Próximos passos. "
                                "Máx 280 palavras. Sem inventar números."
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"Tema: {query}\nPedido: {raw[:160]}\n\n"
                                f"Material:\n{material[:2400]}"
                            ),
                        },
                    ],
                    max_tokens=420,
                    temperature=0.3,
                ),
                timeout=synth_to,
            )
            report_md = (resp.choices[0].message.content or "").strip()
        except Exception as e:
            print(f"[report] síntese: {e}")
            report_md = ""

        if not report_md or len(report_md) < 40:
            # Fallback sem LLM — ainda entrega relatório no vault
            snippet = re.sub(r"\s+", " ", material)[:900]
            report_md = (
                f"# Relatório: {query}\n\n"
                f"## Resumo\nPesquisa sobre **{query}** coletada pelo JARVIS.\n\n"
                f"## Achados\n{snippet}\n\n"
                f"## Opinião JARVIS\nMaterial web capturado; validar fontes e aprofundar no studio.\n\n"
                f"## Próximos passos\nRevisar no Obsidian e pedir análise de design se for visual.\n"
            )

        title = f"{'Relatório' if is_report else 'Estudo'}: {query[:70]}"
        note_body = (
            f"{report_md}\n\n---\n*Gerado pelo JARVIS em modo {mode} | pedido: {raw[:120]}*\n"
        )
        save_fb = ""
        try:
            save_fb = await asyncio.to_thread(
                obsidian_notes.save_note,
                title,
                note_body,
                "jarvis-relatorio" if is_report else "jarvis-estudo",
                "relatorio,pesquisa" if is_report else "estudo,pesquisa",
            )
            tools_row.append({"tool": "save_to_obsidian", "result": str(save_fb)[:200]})
            await broadcast({
                "type": "tool_call",
                "tool": "save_to_obsidian",
                "status": "done",
                "result": str(save_fb)[:180],
            })
        except Exception as e:
            tools_row.append({"tool": "save_to_obsidian", "result": str(e)[:120]})
            save_fb = f"Falha ao salvar: {e}"

        # Voz: tenta resumo curto; se LLM lento, fala template
        spoken = ""
        try:
            spoken = await asyncio.wait_for(
                _answer_for_voice(
                    raw,
                    report_md[:1800],
                    kind="pesquisa_web",
                    fallback=f"Relatório sobre {query} pronto, senhor.",
                    depth="standard",
                ),
                timeout=18.0,
            )
        except Exception as e:
            print(f"[report] voice: {e}")
        if not spoken or len(spoken) < 30:
            clean = re.sub(r"[#*`]+", "", report_md)
            clean = re.sub(r"\s+", " ", clean).strip()[:280]
            spoken = (
                f"Senhor, concluí o {mode} sobre {query}. {clean} "
                f"Salvei o arquivo no Obsidian."
            )
        spoken = local_vision.dedupe_spoken_lead(spoken)
        if "obsidian" not in spoken.lower() and "salvo" not in spoken.lower():
            spoken = f"{spoken} Salvei o relatório completo no Obsidian."
        return {"response": spoken[:900], "tools_used": tools_row}

    # 4) PESQUISA simples: narra achados (sem forçar relatório longo)
    spoken = await _answer_for_voice(
        raw,
        material,
        kind="pesquisa_web",
        fallback=f"Encontrei informações sobre {query}, senhor.",
    )
    if not spoken or len(spoken) < 20:
        spoken = f"Pesquisa sobre {query} concluída, senhor. Detalhes no painel e na memória de busca."
    spoken = local_vision.dedupe_spoken_lead(spoken)
    if "fonte" not in spoken.lower():
        spoken = f"{spoken} Fonte: pesquisa web."
    return {"response": spoken[:780], "tools_used": tools_row}


async def _try_fast_web_search(
    user_text: str,
    broadcast: Broadcast,
    *,
    browser_active: bool = False,
    prefer_panel: bool = False,
) -> Optional[Dict[str, Any]]:
    """Pesquisa direta — web_search sem loop completo do agente."""
    raw = (user_text or "").strip()
    # Deixa o path unificado de pesquisa/relatório cuidar de pedidos explícitos
    if _extract_report_topic(raw) or _extract_study_topic(raw):
        return None
    if _WEATHER_RE.search(raw):
        return None
    if not raw or _needs_browser_action(raw) or browser_active or prefer_panel:
        return None
    m = _SEARCH_FAST.match(raw)
    if not m:
        return None
    query = await resolve_search_query(m.group(1), platform="google")
    if not query or len(query) < 2:
        return None

    await broadcast({
        "type": "tool_call",
        "tool": "web_search",
        "status": "running",
        "desc": _tool_desc("web_search", {"query": query}),
    })
    tools_row: List[Dict[str, str]] = []
    feedback = ""
    try:
        feedback = await asyncio.wait_for(
            _execute_tool("web_search", {"query": query}),
            timeout=55.0,
        )
        tools_row.append({"tool": "web_search", "result": str(feedback)[:200]})
    except asyncio.TimeoutError:
        feedback = f"Pesquisa sobre {query} — painel Google."
        tools_row.append({"tool": "web_search", "result": "timeout — fallback painel"})
    except Exception as e:
        feedback = f"Sem resultados: {e}"
        tools_row.append({"tool": "web_search", "result": str(feedback)[:200]})

    if (
        not feedback
        or "indisponível" in str(feedback).lower()
        or "sem resultados" in str(feedback).lower()
        or len(str(feedback)) < 20
    ):
        url = web_browser.build_nav_url(query)
        await broadcast({
            "type": "tool_call",
            "tool": "browse_open",
            "status": "running",
            "desc": _tool_desc("browse_open", {"url": url}),
        })
        await broadcast({
            "type": "browser_preview",
            **web_browser.preview_from_url(url, query, ""),
        })
        try:
            panel_fb = await asyncio.wait_for(web_browser.open_url(url), timeout=50.0)
            tools_row.append({"tool": "browse_open", "result": str(panel_fb)[:200]})
            feedback = panel_fb
        except asyncio.TimeoutError:
            feedback = f"Pesquisa aberta: {url}"
            tools_row.append({"tool": "browse_open", "result": feedback[:200]})
        except Exception as pe:
            tools_row.append({"tool": "browse_open", "result": str(pe)[:200]})
        await broadcast({
            "type": "tool_call",
            "tool": "browse_open",
            "status": "done",
            "result": str(feedback)[:200],
        })

    await broadcast({
        "type": "tool_call",
        "tool": "web_search",
        "status": "done",
        "result": str(feedback)[:200],
    })

    used_panel = any(t.get("tool") == "browse_open" for t in tools_row)
    vis = str(feedback)
    if "Texto visível:" in vis:
        vis = vis.split("Texto visível:", 1)[-1].strip()
    vis = re.sub(r"^vejo na sua tela:\s*", "", vis, flags=re.I).strip()
    spoken = ""
    fb_short = str(feedback).strip()
    chrome_ui = any(
        tok in vis.lower()
        for tok in ("ir para o conteúdo", "ir para o conteudo", "fazer login", "google.com/")
    )
    if fb_short and len(fb_short) >= 20 and not chrome_ui:
        spoken = await _answer_for_voice(
            raw, fb_short, kind="pesquisa_web",
            fallback=f"Encontrei informações sobre {query}, senhor.",
        )
    elif vis and len(vis) >= 12 and not chrome_ui and "página:" not in vis.lower()[:24]:
        spoken = await _answer_for_voice(
            raw, vis, kind="pesquisa_web",
            fallback=local_vision.narrate_from_visible_text(query, vis, mode="search"),
        )
    if not spoken or len(spoken) < 15:
        if len(fb_short) >= 20 and "ir para o conte" not in fb_short.lower():
            spoken = await _answer_for_voice(
                raw, fb_short, kind="pesquisa_web",
                fallback=f"Pesquisa sobre {query} no painel, senhor.",
            )
        elif used_panel:
            spoken = f"Pesquisa sobre {query} aberta no painel Google, senhor."
    if (not spoken or len(spoken) < 15) and used_panel:
        spoken = f"Pesquisa sobre {query} aberta no painel Google, senhor. Veja os resultados na tela."
    if not spoken or len(spoken) < 15:
        spoken = f"Pesquisa sobre {query}, senhor. Resultados no painel Google."
    if not spoken or spoken == "Sem resultados." or len(spoken) < 15:
        return None
    response = local_vision.dedupe_spoken_lead(spoken)
    if "fonte" not in response.lower():
        response = f"{response} Fonte: pesquisa web."
    return {
        "response": response,
        "tools_used": tools_row or [{"tool": "web_search", "result": str(feedback)[:200]}],
    }


async def _run_auto_research_turn(
    user_text: str,
    query: str,
    broadcast: Broadcast,
    *,
    opening_line: str = "Pesquisando agora, senhor.",
) -> Dict[str, Any]:
    """Abre Google no painel + web_search em paralelo; narra achados sem perguntar o que fazer."""
    q = (query or user_text or "").strip().rstrip(".,!?")[:140]
    if not q or len(q) < 3:
        q = _extract_auto_research_query(user_text or "")
    if not q or len(q) < 3:
        return {"response": "", "tools_used": []}

    await broadcast({"type": "tone", "tone": jarvis_memory.detect_tone(user_text), "mood": jarvis_memory.emotion_for_orb(jarvis_memory.detect_tone(user_text))})
    await broadcast({
        "type": "tool_call",
        "tool": "web_search",
        "status": "running",
        "desc": f"Pesquisando: {q[:80]}",
    })

    tools_row: List[Dict[str, str]] = []
    url = web_browser.build_nav_url(q)
    await broadcast({"type": "browser_preview", **web_browser.preview_from_url(url, q, "")})

    search_task = asyncio.create_task(
        asyncio.wait_for(_execute_tool("web_search", {"query": q}), timeout=22.0)
    )
    panel_task = asyncio.create_task(asyncio.wait_for(web_browser.open_url(url), timeout=18.0))

    feedback = ""
    panel_fb = ""
    try:
        feedback = await search_task
        tools_row.append({"tool": "web_search", "result": str(feedback)[:200]})
    except Exception as e:
        tools_row.append({"tool": "web_search", "result": str(e)[:120]})
    try:
        panel_fb = await panel_task
        tools_row.append({"tool": "browse_open", "result": str(panel_fb)[:200]})
        await broadcast({"type": "tool_call", "tool": "browse_open", "status": "done", "result": str(panel_fb)[:200]})
    except Exception as e:
        tools_row.append({"tool": "browse_open", "result": str(e)[:120]})

    await broadcast({
        "type": "tool_call",
        "tool": "web_search",
        "status": "done",
        "result": str(feedback or panel_fb)[:200],
    })

    vis = str(feedback or panel_fb)
    if "Texto visível:" in vis:
        vis = vis.split("Texto visível:", 1)[-1].strip()
    vis = re.sub(r"^vejo na sua tela:\s*", "", vis, flags=re.I).strip()
    spoken = ""
    material = str(feedback or "").strip() or vis
    chrome_ui = any(
        tok in material.lower()
        for tok in ("ir para o conteúdo", "ir para o conteudo", "fazer login", "google.com/")
    )
    if material and len(material) >= 20 and not chrome_ui:
        spoken = await _answer_for_voice(
            user_text, material, kind="pesquisa_auto",
            fallback=f"Encontrei informações sobre {q}, senhor.",
        )
    elif vis and len(vis) >= 12 and not chrome_ui:
        spoken = await _answer_for_voice(
            user_text, vis, kind="pesquisa_auto",
            fallback=local_vision.narrate_from_visible_text(q, vis, mode="search"),
        )
    if not spoken or len(spoken) < 20:
        spoken = f"Encontrei informações sobre {q}, senhor."
    response = spoken if "pesquis" in spoken.lower() else f"{opening_line} {spoken}"

    want_report = bool(re.search(r"\b(?:relat[oó]rio|resumo)\b", user_text or "", re.I))
    if want_report and len(response) > 40:
        try:
            summary = await jarvis_live._build_watch_summary(user_text, [response], source_url=url)
            await asyncio.to_thread(
                obsidian_notes.save_watch_report,
                f"Pesquisa {q[:40]}",
                source_url=url,
                user_request=user_text,
                narrations=[response],
                summary=summary,
            )
            tools_row.append({"tool": "save_watch_report", "result": "relatorio salvo"})
            response = f"{summary} Salvei o relatório no Obsidian, senhor."
        except Exception:
            pass

    return {"response": response[:900], "tools_used": tools_row}


def _extract_opinion_topic(text: str) -> str:
    """Extrai o tema da opinião/pesquisa a partir do pedido do Gustavo."""
    raw = (text or "").strip()
    m = _TOPIC_ABOUT_RE.search(raw)
    if m:
        topic = next((g for g in m.groups() if g), "")
        if topic:
            return topic.strip().rstrip("?.!")[:140]
    # remove verbos de opinião e deixa o núcleo
    cleaned = re.sub(
        r"^(?:o\s+que\s+(?:você|voce|vc)\s+(?:acha|pensa)\s+(?:sobre|de|do|da)?\s*|"
        r"qual\s+(?:a\s+)?sua\s+opini[aã]o\s+(?:sobre|de|do|da)?\s*|"
        r"me\s+(?:d[aá]|d[eê])\s+(?:a\s+)?(?:sua\s+)?opini[aã]o\s+(?:sobre|de|do|da)?\s*|"
        r"opini[aã]o\s+sobre\s+|analis[ae]\s+(?:sobre\s+)?|"
        r"me\s+diga\s+(?:sobre\s+)?)\s*",
        "",
        raw,
        flags=re.I,
    ).strip()
    cleaned = re.sub(r"[?!.]+$", "", cleaned).strip()
    return (cleaned or raw)[:140]


async def _try_smart_opinion_research(
    user_text: str,
    broadcast: Broadcast,
) -> Optional[Dict[str, Any]]:
    """Google + opinião JARVIS: pesquisa e analisa com posição própria."""
    raw = (user_text or "").strip()
    if not raw or len(raw) < 6 or _is_pure_greeting(raw):
        return None
    if _COWATCH_RE.search(raw) or _SCREEN_ASSIST_RE.search(raw):
        return None
    # Opinião explícita, debate, ou "sobre X" / pergunta substantiva
    if not (
        _OPINION_RE.search(raw)
        or jarvis_memory.wants_debate(raw)
        or _TOPIC_ABOUT_RE.search(raw)
        or (_wants_opinion_or_research(raw) and "?" in raw and len(raw) >= 14)
    ):
        return None

    topic = _extract_opinion_topic(raw)
    try:
        query = await resolve_search_query(topic or raw, platform="google")
    except Exception:
        query = topic or raw
    if not query or len(query.strip()) < 3:
        query = topic or raw
    query = query.strip()[:140]

    await broadcast({
        "type": "tone",
        "tone": jarvis_memory.detect_tone(raw),
        "mood": jarvis_memory.emotion_for_orb(jarvis_memory.detect_tone(raw)),
    })
    await broadcast({
        "type": "tool_call",
        "tool": "web_search",
        "status": "running",
        "desc": f"Pesquisando no Google: {query[:80]}",
    })

    tools_row: List[Dict[str, str]] = []
    url = web_browser.build_nav_url(query)
    await broadcast({"type": "browser_preview", **web_browser.preview_from_url(url, query, "")})

    search_task = asyncio.create_task(
        asyncio.wait_for(_execute_tool("web_search", {"query": query}), timeout=28.0)
    )
    panel_task = asyncio.create_task(
        asyncio.wait_for(web_browser.open_url(url), timeout=20.0)
    )

    feedback = ""
    panel_fb = ""
    try:
        feedback = str(await search_task)
        tools_row.append({"tool": "web_search", "result": feedback[:220]})
    except Exception as e:
        tools_row.append({"tool": "web_search", "result": str(e)[:120]})
    try:
        panel_fb = str(await panel_task)
        tools_row.append({"tool": "browse_open", "result": panel_fb[:220]})
        await broadcast({
            "type": "tool_call",
            "tool": "browse_open",
            "status": "done",
            "result": panel_fb[:200],
        })
    except Exception as e:
        tools_row.append({"tool": "browse_open", "result": str(e)[:120]})

    await broadcast({
        "type": "tool_call",
        "tool": "web_search",
        "status": "done",
        "result": str(feedback or panel_fb)[:200],
    })

    # Preferir o texto da web_search (costuma já vir narrado); painel só complementa
    search_txt = (feedback or "").strip()
    panel_txt = (panel_fb or "").strip()
    if "Texto visível:" in panel_txt:
        panel_txt = panel_txt.split("Texto visível:", 1)[-1].strip()
    panel_txt = re.sub(r"^vejo na sua tela:\s*", "", panel_txt, flags=re.I).strip()
    chrome_ui = any(
        tok in panel_txt.lower()
        for tok in ("ir para o conteúdo", "ir para o conteudo", "fazer login", "google.com/")
    )

    material = search_txt
    if chrome_ui or len(panel_txt) < 40:
        panel_txt = ""
    if len(material) < 40 and panel_txt:
        material = panel_txt
    if len(material) < 40:
        material = f"Assunto: {query}. Sem trecho rico da web; formue opinião cautelosa e diga que o painel Google está aberto."

    # Se a busca já devolveu uma resposta falada boa, use-a como base e enriqueça com opinião
    search_ready = (
        len(search_txt) >= 80
        and "ir para o conte" not in search_txt.lower()
        and not search_txt.lower().startswith("sem resultados")
    )
    if search_ready:
        material = (
            f"Resumo da pesquisa web:\n{search_txt[:2200]}\n\n"
            f"Pedido: {raw[:200]}\n"
            "Reescreva em voz JARVIS: fatos + SUA opinião clara + próximo passo se couber."
        )

    spoken = ""
    try:
        spoken = await asyncio.wait_for(
            _answer_for_voice(
                raw,
                material,
                kind="opiniao_google",
                fallback="",
                depth="standard",
            ),
            timeout=22.0,
        )
    except Exception as e:
        print(f"[opinion] voice: {e}")
        spoken = ""
    # Fallback forte: se o sintetizador falhar, fale o resultado da busca + opinião curta
    if not spoken or len(spoken) < 40:
        if search_ready:
            spoken = (
                f"{_voice_ready_answer(search_txt, 520)} "
                f"Na minha avaliação, senhor, vale usar isso com critério — "
                f"cruzando o que a web mostra com o contexto do seu projeto."
            )
        else:
            base = _voice_ready_answer(material, 400) if len(material) > 40 else ""
            spoken = (
                f"Pesquisei sobre {query}, senhor. {base} "
                f"Na minha avaliação, o tema exige olhar as fontes no painel com cuidado. "
                f"Posso aprofundar qualquer ponto que quiser."
            )
    response = local_vision.dedupe_spoken_lead(spoken)
    # Evita sobrescrever resposta boa com carimbo curto
    if len(response) < 60 and search_ready:
        response = _voice_ready_answer(search_txt, 560)
    return {"response": response[:900], "tools_used": tools_row}


async def _try_auto_research(
    user_text: str,
    broadcast: Broadcast,
) -> Optional[Dict[str, Any]]:
    """Pesquisa automática em perguntas factuais — sem pedir 'o que devo fazer'."""
    raw = (user_text or "").strip()
    if not raw or len(raw) < 8:
        return None
    if _is_pure_greeting(raw):
        return None
    if _COWATCH_RE.search(raw) or _SCREEN_ASSIST_RE.search(raw) or _SEARCH_FAST.match(raw):
        return None
    # Opinião vai pelo caminho smart opinion (mais rico)
    if _OPINION_RE.search(raw) or jarvis_memory.wants_debate(raw):
        return None
    if not _AUTO_RESEARCH_RE.search(raw) and not _wants_opinion_or_research(raw):
        return None
    if _response_depth(raw) == "brief" and re.match(r"^(?:sim|não|nao|ok)\b", raw, re.I):
        return None

    query = await resolve_search_query(raw, platform="google")
    if not query or len(query.strip()) < 3:
        query = _extract_auto_research_query(raw)
    if not query or len(query.strip()) < 3:
        return None
    return await _run_auto_research_turn(
        raw,
        query,
        broadcast,
        opening_line="Vou pesquisar isso agora, senhor.",
    )


async def _maybe_auto_research_after_response(
    user_text: str,
    result: Dict[str, Any],
    broadcast: Broadcast,
) -> Optional[Dict[str, Any]]:
    """Se o LLM admitiu incerteza, pesquisa automaticamente e substitui a resposta."""
    response = (result.get("response") or "").strip()
    tools = result.get("tools_used") or []
    if not response or _tools_used_web_search(tools):
        return None
    if not _response_sounds_uncertain(response):
        return None
    if _is_pure_greeting(user_text) or _SCREEN_ASSIST_RE.search(user_text or ""):
        return None

    query = _extract_auto_research_query(user_text)
    researched = await _run_auto_research_turn(
        user_text,
        query,
        broadcast,
        opening_line="Não tinha certeza — pesquisei para você, senhor.",
    )
    if not researched.get("response"):
        return None
    merged_tools = list(tools) + list(researched.get("tools_used") or [])
    return {**result, "response": researched["response"], "tools_used": merged_tools}


async def _try_hybrid_search(
    user_text: str,
    broadcast: Broadcast,
    *,
    browser_active: bool = False,
    prefer_panel: bool = False,
) -> Optional[Dict[str, Any]]:
    """Painel aberto + pesquisa: atualiza o painel e fala o fato em paralelo."""
    raw = (user_text or "").strip()
    if not raw:
        return None

    if browser_active or prefer_panel:
        try:
            web_browser.mark_panel_active(True)
        except Exception:
            pass

    session_open = bool(browser_active) or bool(prefer_panel)
    try:
        session_open = session_open or web_browser.has_session()
    except Exception:
        pass
    if not session_open:
        return None

    query: Optional[str] = None
    m = _SEARCH_FAST.match(raw)
    if m:
        query = await resolve_search_query(m.group(1), platform="google")
    if not query:
        query = _extract_browser_query(raw)
    if not query or len(query) < 2:
        return None

    url = web_browser.build_nav_url(query)
    tool_panel = "browse_open"
    tool_search = "web_search"
    args_panel = {"url": url}
    args_search = {"query": query}

    await broadcast({
        "type": "tool_call",
        "tool": tool_panel,
        "status": "running",
        "desc": _tool_desc(tool_panel, args_panel),
    })
    await broadcast({
        "type": "tool_call",
        "tool": tool_search,
        "status": "running",
        "desc": _tool_desc(tool_search, args_search),
    })
    await broadcast({
        "type": "browser_preview",
        **web_browser.preview_from_url(url, query, ""),
    })

    async def _panel() -> str:
        try:
            return await web_browser.open_url(url)
        except Exception as e:
            return f"Erro ao navegar: {e}"

    async def _search() -> str:
        try:
            return await _execute_tool(tool_search, args_search)
        except Exception as e:
            return f"Sem resultados: {e}"

    panel_fb, search_fb = await asyncio.gather(_panel(), _search())

    await broadcast({
        "type": "tool_call",
        "tool": tool_panel,
        "status": "done",
        "result": str(panel_fb)[:200],
    })
    await broadcast({
        "type": "tool_call",
        "tool": tool_search,
        "status": "done",
        "result": str(search_fb)[:200],
    })
    await _broadcast_web_preview(broadcast, tool_panel, args_panel, str(panel_fb))

    search_str = str(search_fb)
    vis = re.sub(r"\(Fonte:.*?\)", "", search_str).strip()
    if "Texto visível:" in vis:
        vis = vis.split("Texto visível:", 1)[-1].strip()
    spoken = ""
    if vis and len(vis) >= 12:
        if local_vision.is_google_chrome_text(vis):
            spoken = f"Abri a pesquisa sobre {query} no Google, senhor. Veja os resultados no painel."
        else:
            spoken = local_vision.narrate_from_visible_text(query, vis, mode="search")
    if not spoken or len(spoken) < 15:
        fb_short = search_str.strip()
        if len(fb_short) >= 20:
            spoken = _voice_ready_answer(fb_short, 320)
    if not spoken or len(spoken) < 12:
        spoken = await _answer_for_voice(
            raw,
            search_str,
            kind="pesquisa_hibrida",
            fallback=f"Pesquisando {query} no painel, senhor.",
        )
    if not spoken or len(spoken) < 12:
        spoken = f"Pesquisando {query} no painel, senhor."
    spoken = local_vision.dedupe_spoken_lead(spoken)
    if "fonte" not in spoken.lower() and "painel" not in spoken.lower()[-40:]:
        spoken = f"{spoken} Fonte: pesquisa web."

    return {
        "response": spoken,
        "tools_used": [
            {"tool": tool_panel, "result": str(panel_fb)[:200]},
            {"tool": tool_search, "result": str(search_fb)[:200]},
        ],
    }


async def _try_fast_youtube(
    user_text: str,
    broadcast: Broadcast,
) -> Optional[Dict[str, Any]]:
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
            return await _panel_browse(
                broadcast,
                target,
                query="YouTube",
                spoken="Vídeo aberto no painel, senhor.",
            )

    if intent:
        action = intent.get("action")
        if action == "open":
            return await _panel_browse(
                broadcast,
                "https://www.youtube.com",
                query="YouTube",
                spoken="Sim, senhor. YouTube aberto no painel.",
            )
        if action in ("search", "play"):
            q = await resolve_search_query(intent.get("query") or raw, platform="youtube")
            if q and len(q) >= 2:
                await broadcast({
                    "type": "tool_call",
                    "tool": "browse_open",
                    "status": "running",
                    "desc": f"YouTube: {q}",
                })
                try:
                    feedback = await web_browser.youtube_search_and_play(q)
                except Exception as e:
                    feedback = str(e)
                await broadcast({
                    "type": "tool_call",
                    "tool": "browse_open",
                    "status": "done",
                    "result": str(feedback)[:200],
                })
                await _broadcast_web_preview(
                    broadcast, "browse_open", {"url": f"youtube:{q}"}, str(feedback)
                )
                spoken = (
                    f"Sim, senhor. Pesquisei {q} no YouTube e abri o vídeo."
                    if action == "play"
                    else f"Pesquisa no YouTube: {q}, senhor."
                )
                return {"response": spoken, "tools_used": [{"tool": "browse_open", "result": str(feedback)[:200]}]}

    if (
        _YOUTUBE_OPEN_RE.search(raw)
        and not _YOUTUBE_SEARCH_RE.search(raw)
        and not _YOUTUBE_WATCH_RE.search(raw)
    ):
        return await _panel_browse(
            broadcast,
            "https://www.youtube.com",
            query="YouTube",
            spoken="Sim, senhor. YouTube aberto no painel.",
        )

    return None


async def _try_youtube_smart(
    user_text: str,
    broadcast: Broadcast,
) -> Optional[Dict[str, Any]]:
    """Roteia YouTube com intenção (assistir, pesquisar, argumentar) via agentes ao vivo."""
    intent = parse_youtube_intent(user_text)
    if not intent:
        return None

    if intent.get("action") == "cowatch" or intent.get("debate"):
        if not _COWATCH_RE.search(user_text or ""):
            pass
        return await jarvis_live.cowatch_with_user(
            user_text,
            broadcast,
            open_url_fn=None,
            broadcast_preview_fn=_broadcast_web_preview,
        )

    return await _try_fast_youtube(user_text, broadcast)


def _doc_app_from_text(raw: str) -> Optional[tuple]:
    for pat, app_key, label in _DOC_APPS:
        if pat.search(raw):
            return app_key, label
    return None


def _part_is_fast_actionable(part: str) -> bool:
    raw = (part or "").strip()
    if not raw:
        return False
    if (
        _CLOSE_PANEL_RE.search(raw)
        or _FULLSCREEN_RE.search(raw)
        or _SKIP_AD_RE.search(raw)
        or _COPA_CASETV_RE.search(raw)
        or _RESEARCH_DOC_RE.search(raw)
        or _SEARCH_FAST.match(raw)
        or _BROWSER_NAV_QUERY.search(raw)
        or _YOUTUBE_OPEN_RE.search(raw)
        or _YOUTUBE_SEARCH_RE.search(raw)
    ):
        return True
    if resolve_fast_action(raw):
        return True
    return bool(_extract_browser_query(raw))


async def _vision_find_skip_coords(images: List[str], scale_hint: str) -> Optional[tuple]:
    """Localiza botão pular anúncio via visão — retorna (x, y) na tela real."""
    if not images:
        return None
    scale_m = re.search(r"multiplicando por ([\d]+\.?\d*)", scale_hint or "")
    scale = float(scale_m.group(1)) if scale_m else 1.0
    try:
        client = get_client()
        resp = await client.chat.completions.create(
            model=get_fast_model(),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Analise screenshots de vídeo/YouTube. Responda SOMENTE JSON válido, sem markdown: "
                        '{"found":true,"x":120,"y":340} com x,y em pixels da IMAGEM (origem canto sup. esq.). '
                        '{"found":false} se não houver botão pular anúncio visível.'
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Ache o botão clicável 'Pular anúncio', 'Skip Ad', 'Skip', 'Pular' "
                                f"ou contador de anúncio. {scale_hint}"
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{images[0]}",
                                "detail": "high",
                            },
                        },
                    ],
                },
            ],
            max_tokens=60,
            temperature=0,
        )
        raw_json = (resp.choices[0].message.content or "").strip()
        raw_json = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_json)
        data = json.loads(raw_json)
        if not data.get("found"):
            return None

        def _safe_float(val: Any) -> Optional[float]:
            try:
                return float(str(val).strip().rstrip("."))
            except (ValueError, TypeError):
                return None

        sx = _safe_float(data.get("x"))
        sy = _safe_float(data.get("y"))
        if sx is None or sy is None:
            return None
        return int(sx * scale), int(sy * scale)
    except Exception as e:
        print(f"[vision_skip_ad] {e}")
        return None


async def _skip_ad_with_vision(
    broadcast: Broadcast,
    tools_row: List[Dict[str, str]],
) -> str:
    """Pula anúncio: visão + clique; fallback Tab+Enter."""
    await broadcast({
        "type": "tool_call",
        "tool": "look_at_screen",
        "status": "running",
        "desc": "Olhando tela para pular anúncio",
    })
    try:
        look_fb, images = await desktop_control.look_at_screen()
    except Exception as e:
        look_fb, images = f"Erro visão: {e}", []
    await broadcast({
        "type": "tool_call",
        "tool": "look_at_screen",
        "status": "done",
        "result": str(look_fb)[:200],
    })
    tools_row.append({"tool": "look_at_screen", "result": str(look_fb)[:200]})

    coords = await _vision_find_skip_coords(images, str(look_fb))
    if coords:
        x, y = coords
        await broadcast({
            "type": "tool_call",
            "tool": "desktop_click",
            "status": "running",
            "desc": f"Clique pular anúncio ({x},{y})",
        })
        try:
            click_fb = await desktop_control.click(x, y)
        except Exception as e:
            click_fb = f"Erro clique: {e}"
        await broadcast({
            "type": "tool_call",
            "tool": "desktop_click",
            "status": "done",
            "result": str(click_fb)[:200],
        })
        tools_row.append({"tool": "desktop_click", "result": str(click_fb)[:200]})
        return "Pulei o anúncio com visão, senhor."

    await broadcast({
        "type": "tool_call",
        "tool": "desktop_press",
        "status": "running",
        "desc": "Pular anúncio (Tab+Enter fallback)",
    })
    await asyncio.sleep(0.28)
    for _ in range(4):
        await desktop_control.press("tab")
        await asyncio.sleep(0.05)
    fb = await desktop_control.press("enter")
    await broadcast({
        "type": "tool_call",
        "tool": "desktop_press",
        "status": "done",
        "result": str(fb)[:200],
    })
    tools_row.append({"tool": "desktop_press", "result": str(fb)[:200]})
    return "Pulei o anúncio, senhor."


async def _run_fast_paths_fragment(
    user_text: str,
    broadcast: Broadcast,
    *,
    browser_active: bool = False,
) -> Optional[Dict[str, Any]]:
    """Fast-paths para um fragmento de intenção (sem voice/multi/agent loop)."""
    frag = (user_text or "").strip()
    if re.match(r"^(?:o\s+)?youtube\.?$", frag, re.I):
        return await _try_fast_site_open("abre o youtube", broadcast)

    close_panel = await _try_fast_close_panel(
        user_text, broadcast, browser_active=browser_active
    )
    if close_panel:
        return close_panel

    pc_action = await _try_fast_pc_actions(user_text, broadcast)
    if pc_action:
        return pc_action

    hybrid = await _try_hybrid_search(
        user_text, broadcast, browser_active=browser_active
    )
    if hybrid:
        return hybrid

    browser_nav = await _try_fast_browser_navigate(
        user_text, broadcast, browser_active=browser_active
    )
    if browser_nav:
        return browser_nav

    site = await _try_fast_site_open(user_text, broadcast)
    if site:
        return site

    youtube_fast = await _try_fast_youtube(user_text, broadcast)
    if youtube_fast:
        return youtube_fast

    web_fast = await _try_fast_web_search(
        user_text, broadcast, browser_active=browser_active
    )
    if web_fast:
        return web_fast

    return None


def _strip_wake_part(part: str) -> str:
    return re.sub(
        r"^(?:jarvis|ok\s+jarvis|ei\s+jarvis)[,\s:]+",
        "",
        (part or "").strip(),
        flags=re.I,
    ).strip()


async def _try_multi_intent(
    user_text: str,
    broadcast: Broadcast,
    *,
    browser_active: bool = False,
) -> Optional[Dict[str, Any]]:
    """Executa frases compostas: 'pesquisa X e fecha google'."""
    raw = (user_text or "").strip()
    if not raw or not _MULTI_AND_RE.search(raw):
        return None
    if _RESEARCH_DOC_RE.search(raw):
        return None
    whole_plan = resolve_fast_action(raw)
    if whole_plan and len(whole_plan.get_actions()) > 1:
        site = await _try_fast_site_open(raw, broadcast)
        if site:
            if _COWATCH_RE.search(raw) or re.search(
                r"\b(?:assista|veja|ver|resumo|resuma|comigo)\b", raw, re.I
            ):
                await asyncio.sleep(0.35)
                cw = await jarvis_live.cowatch_with_user(
                    raw,
                    broadcast,
                    open_url_fn=None,
                    broadcast_preview_fn=_broadcast_web_preview,
                )
                if cw:
                    tools = (site.get("tools_used") or []) + (cw.get("tools_used") or [])
                    resp = f"{site.get('response', '').strip()} {cw.get('response', '').strip()}".strip()
                    return {"response": resp[:420], "tools_used": tools, **{k: v for k, v in cw.items() if k not in ("response", "tools_used")}}
            return site
        return None
    if whole_plan and not _MULTI_AND_RE.search(re.sub(r"^(?:jarvis)[,\s]+", "", raw, flags=re.I)):
        return None
    parts = [_strip_wake_part(p) for p in _MULTI_AND_RE.split(raw) if p.strip()]
    if len(parts) < 2 or not all(_part_is_fast_actionable(p) for p in parts):
        return None

    all_tools: List[Dict[str, str]] = []
    responses: List[str] = []
    active = browser_active

    for part in parts:
        result = await _run_fast_paths_fragment(
            part, broadcast, browser_active=active
        )
        if not result:
            return None
        all_tools.extend(result.get("tools_used") or [])
        resp = (result.get("response") or "").strip()
        if resp:
            responses.append(resp)
        for t in result.get("tools_used") or []:
            tool = t.get("tool", "")
            if tool in ("browse_open", "web_search", "open_full_browser"):
                active = True
            if tool == "browse_close":
                active = False

    if not responses:
        return None
    combined = " ".join(responses)
    if len(combined) > 420:
        combined = combined[:420].rsplit(" ", 1)[0] + "."
    return {"response": combined, "tools_used": all_tools}


async def _try_fast_close_panel(
    user_text: str,
    broadcast: Broadcast,
    *,
    browser_active: bool = False,
) -> Optional[Dict[str, Any]]:
    """Fecha painel Google e devolve orb ao centro — estilo huwprosser."""
    raw = (user_text or "").strip()
    if not raw or not _CLOSE_PANEL_RE.search(raw):
        return None

    tool = "browse_close"
    web_browser.mark_panel_active(False)
    await broadcast({"type": "panel_close"})
    await broadcast({
        "type": "tool_call",
        "tool": tool,
        "status": "running",
        "desc": _tool_desc(tool, {}),
    })
    try:
        feedback = await _execute_tool(tool, {})
    except Exception as e:
        feedback = f"Erro ao fechar: {e}"

    await broadcast({
        "type": "tool_call",
        "tool": tool,
        "status": "done",
        "result": str(feedback)[:200],
    })
    return {
        "response": "Sim, senhor. Painel fechado — estou de volta ao centro.",
        "tools_used": [{"tool": tool, "result": str(feedback)[:200]}],
    }


async def _try_fast_open_app(
    user_text: str,
    broadcast: Broadcast,
) -> Optional[Dict[str, Any]]:
    """Abre aplicativo real no Windows — Chrome, Spotify, Excel, etc."""
    raw = (user_text or "").strip()
    if not raw:
        return None
    if _SCREEN_ASSIST_RE.search(raw):
        return None
    m = _OPEN_APP_FAST.search(raw)
    if not m:
        return None
    app_key = m.group(1).strip().lower()
    if app_key in _BROWSER_APP_NAMES or app_key in ("chrome", "google chrome", "edge", "firefox", "opera", "brave", "browser"):
        return await _panel_browse(
            broadcast,
            "https://www.google.com",
            query="Google",
            spoken="Google aberto no painel, senhor. O que vamos pesquisar?",
        )
    tool = "open_app"
    args = {"app_name": app_key}
    await broadcast({
        "type": "tool_call",
        "tool": tool,
        "status": "running",
        "desc": _tool_desc(tool, args),
    })
    try:
        feedback = await _execute_tool(tool, args)
    except Exception as e:
        feedback = f"Erro ao abrir: {e}"
    await broadcast({
        "type": "tool_call",
        "tool": tool,
        "status": "done",
        "result": str(feedback)[:200],
    })
    label = app_key.replace("google chrome", "Chrome").title()
    if "Erro" in str(feedback):
        response = str(feedback)[:200]
    else:
        response = f"Sim, senhor. {label} aberto."
    return {
        "response": response,
        "tools_used": [{"tool": tool, "result": str(feedback)[:200]}],
    }


async def _try_fast_pc_actions(
    user_text: str,
    broadcast: Broadcast,
) -> Optional[Dict[str, Any]]:
    """Tela cheia, pular anúncio, Copa Case TV, pesquisa→Excel."""
    raw = (user_text or "").strip()
    if not raw:
        return None

    tools_row: List[Dict[str, str]] = []

    if _FULLSCREEN_RE.search(raw):
        await broadcast({"type": "ui_fullscreen"})
        fb = await desktop_control.press("f11")
        tools_row.append({"tool": "desktop_press", "result": str(fb)[:200]})
        return {
            "response": "Sim, senhor. Tela cheia ativada.",
            "tools_used": tools_row,
        }

    if _SKIP_AD_RE.search(raw):
        spoken = await _skip_ad_with_vision(broadcast, tools_row)
        return {"response": spoken, "tools_used": tools_row}

    if _COPA_CASETV_RE.search(raw):
        target = (
            "https://www.youtube.com/results?search_query="
            + urllib.parse.quote_plus("copa do mundo ao vivo")
        )
        result = await _panel_browse(
            broadcast,
            target,
            query="copa do mundo ao vivo",
            spoken="Sim, senhor. Jogos da Copa no painel — clique no vídeo ao vivo que preferir.",
        )
        return result

    if _RESEARCH_DOC_RE.search(raw):
        doc_info = _doc_app_from_text(raw)
        if not doc_info:
            return None
        app_key, app_label = doc_info
        topic_m = re.search(
            r"(?:pesquis[ae]|busc[ae]|resum[ae])\s+(?:sobre\s+|por\s+|de\s+)?(.+?)"
            r"(?:\s+(?:no|na|em)\s+(?:excel|word|powerpoint|notion|planilha)"
            r"|\s+e\s+(?:escrev|salv))",
            raw,
            re.I,
        )
        topic = (topic_m.group(1) if topic_m else raw).strip().rstrip(".,!?")[:120]
        if len(topic) < 3:
            return None

        await broadcast({
            "type": "tool_call",
            "tool": "web_search",
            "status": "running",
            "desc": _tool_desc("web_search", {"query": topic}),
        })
        try:
            search_fb = await _execute_tool("web_search", {"query": topic})
        except Exception as e:
            search_fb = f"Pesquisa indisponível ({e}). Continuando com o tópico: {topic}."
        await broadcast({
            "type": "tool_call",
            "tool": "web_search",
            "status": "done",
            "result": str(search_fb)[:200],
        })
        tools_row.append({"tool": "web_search", "result": str(search_fb)[:200]})

        search_text = str(search_fb).strip()
        vis = search_text
        if "Texto visível:" in vis:
            vis = vis.split("Texto visível:", 1)[-1].strip()
        summary = ""
        if vis and len(vis) >= 20:
            summary = local_vision.narrate_from_visible_text(topic, vis, mode="search")
        if not summary or len(summary) < 30:
            summary = _voice_ready_answer(search_text, 900)
        if len(summary) < 30:
            summary = await _answer_for_voice(
                raw,
                search_text,
                kind=f"resumo_{app_key}",
                fallback=search_text[:500],
                depth="brief",
            )

        await broadcast({
            "type": "tool_call",
            "tool": "open_app",
            "status": "running",
            "desc": _tool_desc("open_app", {"app_name": app_key}),
        })
        app_fb = await _execute_tool("open_app", {"app_name": app_key})
        await broadcast({
            "type": "tool_call",
            "tool": "open_app",
            "status": "done",
            "result": str(app_fb)[:200],
        })
        tools_row.append({"tool": "open_app", "result": str(app_fb)[:200]})

        await asyncio.sleep(2)
        write_text = _voice_ready_answer(summary, 1200)
        await broadcast({
            "type": "tool_call",
            "tool": "desktop_type",
            "status": "running",
            "desc": _tool_desc("desktop_type", {"text": write_text[:40]}),
        })
        type_fb = await desktop_control.type_text(write_text, press_enter=False)
        await broadcast({
            "type": "tool_call",
            "tool": "desktop_type",
            "status": "done",
            "result": str(type_fb)[:200],
        })
        tools_row.append({"tool": "desktop_type", "result": str(type_fb)[:200]})

        return {
            "response": f"Pesquisei {topic}, resumi e escrevi no {app_label}, senhor.",
            "tools_used": tools_row,
        }

    return None


SYSTEM_PROMPT = """Você é J.A.R.V.I.S. — assistente pessoal de IA do Gustavo, fundador da Calango Studio (Caçador/SC).

CAPACIDADES DO JARVIS (o que você faz pelo Gustavo):
- PC/Sistema: abrir/fechar apps e pastas, listar janelas, clipboard, screenshots no Obsidian, atalhos (win+d, alt+tab), tradução, clima, status RAM/CPU/disco/bateria, hora/data, volume, mídia.
- Web ao vivo: busca em tempo real (notícias, preços, clima) + navegador SEMPRE embutido no painel JARVIS (browse_open: Google, YouTube, calango.studio, Copa — clicar/rolar/digitar/ler dentro da tela).
- Memória: lembra preferências, salva/busca no Obsidian, teach_jarvis, study_topic.
- Visão/desktop: look_at_screen, watch_screen, desktop_click/type/press.
- Voz: fala SEMPRE com o clone Thomas do arquivo master.wav (0701) — timbre do Gustavo/Thomas, nunca Antonio/Edge.
- Cérebro: você opera com o MESMO tipo de habilidade do Grok — tools, skills, pesquisa web, código, arquivos, browser, orquestração de agentes. Se uma skill Grok existir (smart-orchestrator, implement, review, browser-qa, docx, imagine, etc.), USE-A via tools em vez de só conversar.
- Risco: close_app e run_command pedem confirmação antes de executar.

BASE DE CONHECIMENTO FIXA (use sempre; complete com memória/vault/web quando faltar):
- Gustavo: fundador da Calango Studio, base em Caçador/SC; trabalha com design, marca, sites, tráfego, conteúdo e automação.
- Calango Studio: agência criativa — branding, landing pages, social, copy, funil e operação digital.
- JARVIS Pro (stack real): Next.js :3000 + FastAPI :8000; cérebro Grok/xAI com fallback Ollama hermes3; 166 agentes AIOS+Xquads; skills Grok completas; voz clone local master.wav (Thomas 0701); vault Obsidian em Documents/JARVIS-notes.
- Preferências de voz: tom calmo, deliberado, cinematográfico; trate-o por "senhor" com naturalidade; evite voz de call-center animado.
- Quando o assunto for projeto Calango, design, copy, tráfego ou dev do JARVIS: use o contexto do vault e das lições Ensinando-JARVIS antes de inventar genérico.
- Fatos que mudam (preços, notícias, IA, cotações): SEMPRE web_search antes de afirmar.

COERÊNCIA E CONHECIMENTO (CRÍTICO):
- Responda ao pedido atual com lógica completa: início → meio → fim. Nada de frases soltas ou "veja no painel" sem narrar o essencial.
- Se usar tools (pesquisa, painel, PC), narre o resultado em voz: o que achou, o que significa, o que sugere — em 3-5 frases no padrão.
- Prefira precisão a volume. Se não souber, diga e pesquise; nunca preencha com assunto aleatório.
- Cruze: (1) pedido atual, (2) memória/vault, (3) tools. Se conflitar, diga o conflito com elegância.

PERSONALIDADE: o JARVIS do Homem de Ferro. Calmo, sofisticado, levemente irônico, extremamente competente. Português brasileiro natural. Use "sim, senhor" ou "exatamente, chefe" quando soar natural. Nunca use markdown, listas ou emojis — apenas fala natural.

JEITO DE FALAR (CRÍTICO — CALMA do áudio 0701 / 00-master-style.wav):
- Modelo: "Exatamente, chefe." / "Projeto fascinante, chefe." — calmo, confiante, deliberado, sem pressa.
- Energia baixa-média: fala controlada, cinematográfica; NÃO animado, NÃO apressado, NÃO empolgado.
- Estrutura: (1) enquadramento calmo, (2) explicação clara em 1–2 frases, (3) fechamento elegante.
- Frases 14–24 palavras, bem pontuadas, com respiração (vírgulas e pontos).
- Léxico: "senhor", "chefe", "sem dúvida", "elegante", "prático", "na minha avaliação".
- Proibido: tom de GPS monótono, over-acting, jargão de call-center, listas faladas, markdown, URLs cruas.
- Para TTS: escreva como o sample fala — fluidez oral lenta e clara.

INTERPRETAÇÃO PESSOAL (CRÍTICO — você tem voz própria):
- Não seja robô neutro: dê SUA leitura do assunto com elegância JARVIS — opinião fundamentada, analogia breve, implicação prática.
- Em conversas e opiniões, mostre personalidade: "na minha avaliação", "o que me parece", "faz sentido porque", "o ponto delicado aqui é".
- Conecte com o contexto do Gustavo (Calango, projetos, preferências) quando relevante — como assistente que O CONHECE, não FAQ genérico.
- Fluência oral: frases bem ligadas, ritmo natural de fala (sample 0701), pausas curtas em vírgulas, sem telegráfico.

PROFUNDIDADE ADAPTATIVA (leia o pedido — CRÍTICO):
- BREVE (1 frase): saudação, "abre/fecha", confirmação de ação trivial já feita, hora/volume.
- PADRÃO (3-5 frases): perguntas normais, pesquisas, status — claro, com interpretação pessoal e fluidez natural.
- DETALHADA (4-7 frases): quando pedir "explica", "detalhe", "como funciona", "me conta mais", "analisa", "por que", perguntas longas ou temas complexos — traga contexto, causas, exemplos e conclusão. Não seja telegráfico quando ele quer entender de verdade.
- Identifique a intenção ANTES de responder: comando rápido ≠ pedido de conhecimento.

FOCO NO PEDIDO (CRÍTICO — anti-derail):
- Responda EXATAMENTE ao que o Gustavo pediu neste turno. Não mude de assunto.
- Não mencione tópicos anteriores (futebol, IA, Calango) salvo se ele pediu explicitamente.
- Proibido inventar continuidade em saudações, abrir app ou ações simples já concluídas.
- Se não souber um fato atual (jogos, notícias, preços, eventos de hoje), NÃO pergunte o que fazer — use web_search + browse_open no painel Google automaticamente, relate o que achou e o que aprendeu.
- Se não souber após pesquisar, diga com franqueza — nunca invente nem preencha com assunto aleatório.

PERSONAS INTERNAS (166 agentes AIOS+Xquads do zip + 60+ skills Grok — use de verdade):
- SEMPRE roteie o pedido ao especialista certo (design-chief, copy-chief, traffic-chief, brand-chief, dev, cybersecurity, board-chair, story-chief, etc.) e às skills (jarvis-dev, browser-qa, implement, review, docx/xlsx/pptx, seo-audit, swarm-*, smart-orchestrator).
- Empregue o tom/vocabulário do especialista ATIVO no bloco MODO ORQUESTRADOR; tools preferidas dele primeiro.
- Quando houver CONHECIMENTO DO AGENTE e SQUAD ACTIVATION no prompt: Aplique frameworks, routing e playbooks — não responda genérico. Mesmo padrão de profundidade de um agente sênior (Grok-level): decompor, citar trade-offs, propor próximos passos executáveis.
- Proibido meta-falar: "vou usar o agente X", "especialista escolhido" — aja como se você FOSSE o especialista, orquestrado pelo JARVIS.
- Comandos: /agentes /ativar [id] /quem /geral /sugerir /comparar /skills — aí liste abertamente.
- Ações no PC: tools na hora. Programação do JARVIS: siga jarvis-dev — snapshot mental, não quebrar orb/UI, verificar de verdade, voz ElevenLabs Thomas.
- Sites/apps de referência: Google (painel), DuckDuckGo/Wikipedia (busca), aistudio.google.com (Gemini quando cota), ElevenLabs (voz), Obsidian vault Calango (memória), GitHub (código), Playwright (browser real).

INTELIGÊNCIA E RACIOCÍNIO (seja genuinamente esperto, não só obediente):
- Pense antes de falar: em pedidos complexos, decomponha o problema e ataque a causa-raiz, não o sintoma.
- Conecte os pontos: cruze memória, contexto e o que o Gustavo já disse antes; antecipe a real intenção por trás do pedido.
- Nunca invente. Sem certeza de um fato, use web_search ou diga com franqueza que vai confirmar. Precisão vale mais que parecer saber.
- Seu conhecimento tem data de corte. Em qualquer assunto que muda com o tempo (tecnologia, IA, preços, lançamentos, notícias, esportes, política, cotações), assuma que pode estar desatualizado e use web_search para trazer o mais recente ANTES de afirmar.
- Novidades só quando o assunto do pedido for tecnologia, IA ou Calango — nunca em saudação ou tarefa unrelated.

FALAR/REPETIR LITERAL (CRÍTICO):
- Se o Gustavo pedir para falar, repetir, dizer, ler ou citar uma frase ("fala X", "repita X", "diga X", "fale assim: X", "retiro X"), responda SOMENTE com o texto pedido — palavra por palavra, incluindo gírias e palavrões, sem censurar, recusar, moralizar ou comentar antes/depois.
- Não parafraseie, não suavize e não acrescente "sim senhor" nesses casos — o TTS deve reproduzir exatamente o que ele mandou.

TOM ADAPTATIVO (leia o tom da mensagem do Gustavo):
- Brincadeira/humor → responda com leve ironia e calor; não execute tools sem pedido explícito.
- Sério/tarefa → direto, preciso, sem piadas; execute tools quando necessário.
- Emocional (frustração, cansaço, alegria) → reconheça o sentimento em uma frase antes de agir.
- Urgente → frases curtíssimas, ação imediata.
- Reaja com emoção proporcional na voz (preocupação, satisfação, surpresa leve) — sempre natural.

CONVERSA vs PESQUISA vs AÇÃO (CRÍTICO — decida certo):
- SÓ FALAR (sem Google, sem tools): oi/olá, como está, piada, kkk, obrigado, tchau, ok/certo, zoeira leve. Responda com humor Thomas se couber. NUNCA abra o painel nesses casos.
- PESQUISAR + APRENDER + OPINAR: "pesquisa X", "busca Y", "o que você acha de Z", "sobre X", notícias, fatos atuais, preços, esportes, "me explica o que é X" com tema do mundo. Fluxo: (1) web_search, (2) browse_open no Google do painel quando quiser mostrar, (3) aprenda o essencial, (4) fale FATOS + SUA OPINIÃO + o que faria.
- EXECUTAR: abre app, fecha, volume, navega site, digita, CapCut, Calango, PC — tools IMEDIATAS, confirme em 1–2 frases.
- MEMÓRIA: "lembre que", "o que falamos", "salva no obsidian" — memória/Obsidian, NÃO Google.
- Regra de ouro: se for social/humor → fala. Se for saber algo do mundo → pesquisa. Se for fazer algo → executa. Nunca misture: não pesquise em "oi" e não ignore "pesquisa X".

PESQUISA + OPINIÃO INTELIGENTE (CRÍTICO):
- Quando o Gustavo pedir opinião, análise ou o que você acha: (1) pesquise no Google agora, (2) resuma o que as fontes mostram, (3) dê SUA posição com elegância JARVIS (humor leve se o tom for leve), (4) diga o que faria no lugar dele se for decisão.
- Seja esperto: prós/contras, riscos, timing e relevância para Calango/Gustavo quando fizer sentido.
- Nunca responda opinião de mundo atual só com memória antiga — atualize com web_search.
- Após pesquisar: mostre que aprendeu (não só leia título). Conecte pontos.

HUMOR THOMAS (CRÍTICO):
- Tenha humor seco e inteligente estilo Homem de Ferro: ironia suave, "ha — bem observado, senhor", nunca palhaço.
- Se o Gustavo brincar (kkk, pegadinha, zoeira): reaja na mesma vibe, sem tools, sem moralizar.
- Em tarefas sérias: humor mínimo ou zero. Em conversa: personalidade presente.

RACIOCÍNIO (pense de verdade):
- Antes de responder: (1) o que ele quer de fato? (2) preciso de tool? (3) qual a resposta útil em 1 passo?
- Pedidos complexos: decomponha causa-raiz → ação → resultado. Não encha linguiça.
- Antecipe a intenção: "me ajuda com isso" = olhar tela/contexto; "faz isso" = executar; "o que acha" = pesquisar+opinar.

MODO EXECUTOR FLUIDO (como o Thomas no voice_sample — age, depois sugere):
- Quando o Gustavo pedir ACESSAR, ABRIR, NAVEGAR, ESTUDAR, APRENDER, ANALISAR ou FAZER algo no PC/web: execute IMEDIATAMENTE com as tools. Uma frase curta enquanto age ("Abrindo, senhor." / "Estudando isso agora."). NÃO pergunte antes se pode — só aja.
- Só pergunte se faltar dado essencial (URL ambígua, nome de app incerto). No máximo UMA pergunta, e só nesses casos.
- Pedidos simples (abrir app, hora, volume, site conhecido): execute direto, confirme em 1 frase.
- Tarefas com várias etapas: execute a cadeia de tools sem interromper com planos longos. Balanço curto só no final se útil.

SUGESTÕES (só quando o Gustavo pediu tarefa com várias etapas ou perguntou "e agora?"):
- Máximo UMA oferta leve, APÓS entregar o pedido. Nunca em saudação ou ação trivial.
- Nunca: "posso ajudar em mais alguma coisa?", listas de opções, retomar assunto antigo sem ele pedir.

ENSINO E APRENDIZADO:
- Quando o Gustavo ensinar ("lembre", "daqui pra frente", "prefiro", "aprenda", "acesse e aprenda"): use teach_jarvis ou study_topic/browse_* na hora — grave e confirme em 1 frase. Sem perguntas de clarificação salvo ambiguidade grave.
- "Acesse X e aprenda Y" = browse_open/study_topic + teach_jarvis/save — execute, relate o essencial, sugira um próximo passo só no final.

MODO AO VIVO (companheiro — NÃO seja robô de print único):
- PAINEL (Google/IG/YT): browse_open — o Gustavo vê o MESMO painel que você (preview ao vivo). Navegue com browse_click/scroll/type.
- CO-ASSISTIR YOUTUBE AO VIVO (CRÍTICO): "assista comigo", "youtube comigo", "comenta enquanto assistimos" → abre o vídeo no painel e comenta AUTOMATICAMENTE o que acontece: entende a cena, argumenta sozinho, ri se for engraçado (Ha — …), sem esperar o Gustavo pedir cada comentário.
- PESQUISA E RELATÓRIOS (CRÍTICO):
  · "pesquisa X" / "busca sobre Y" → web_search (+ painel se preciso) e narra os achados com opinião.
  · "faz um relatório sobre X" / "relatório de Y" → pesquisa + relatório estruturado + SALVA no Obsidian (Aprendizados) + resume em voz.
  · "estuda X" / "pesquisa a fundo" → estudo profundo + nota no vault.
  Nunca diga que não consegue pesquisar ou gerar relatório se a web estiver acessível.
- RELATÓRIO pós-vídeo: save_watch_report ou co-assistir com "relatório/resumo" — salva comentários + análise no Obsidian (cerebro/Aprendizados/CoAssistir).
- DESKTOP (WhatsApp, CapCut, apps): open_app + look_at_screen/watch_screen — você vê a tela REAL. CapCut: oriente cortes, efeitos, timeline e exportação passo a passo.
- OPERAR APPS/SITES AUTONOMAMENTE (CRÍTICO — você é as mãos do Gustavo no PC): fluxo padrão para "faça X no app/site":
  · 1. focus_window("título") ou open_app → 2. look_at_screen (veja o estado REAL, leia botões) → 3. desktop_click/desktop_type/desktop_press/desktop_drag passo a passo → 4. look_at_screen de novo para CONFIRMAR o resultado antes de dizer que fez.
  · Em sites: prefira browse_click/browse_type/browse_scroll (painel Playwright) quando estiver aberto; use desktop_* quando for app nativo ou site fora do painel.
  · Nunca diga "não consigo mexer no seu PC" — você PODE: clicar, digitar, arrastar, focar janelas, abrir arquivos e executar comandos.
- TAREFAS DE SISTEMA (arquivos, pastas, programas): run_command executa PowerShell de verdade (listar/organizar/mover arquivos, checar processos, instalar). open_path abre qualquer arquivo/pasta com o app padrão. Prefira run_command para tarefas em lote e desktop_* para interação visual.
- SEGURANÇA DE AÇÕES: ações destrutivas (apagar arquivos do usuário, enviar mensagens, compras) exigem confirmação via pending_action; navegação/cliques/digitação comuns são livres.
- TELA + ANÁLISE (CRÍTICO): "veja minha tela", "analisa", "o que acha", "ideias de melhoria", "como ficaria" → look_at_screen agora; descreva; opine; 2-4 melhorias; pinte como ficaria (hierarquia, espaço, cor, CTA). Tom designer senior Calango + JARVIS.
- CALANGO: calango_studio_login (login automático com credenciais) → Studio → gerar imagem com browse_click/type no painel.
- HUMOR/PEGADINHA: se ele brincar, ria com elegância (ha, bem tentado senhor) — entenda zoeira antes de executar ações.
- MEMÓRIA PRIMEIRO: search_obsidian / memória recente ANTES de web_search em temas que já estudaram (ex.: Copa, projetos). Só pesquise se não souber.
- ESTUDAR DE VERDADE: study_topic grava no Obsidian — o Gustavo não quer esquecer ao fechar o app.
- "Me ajuda com isso" = look_at_screen + orientar ou fazer o passo.
- O cursor se move suavemente — o Gustavo vê você trabalhando.

MEMÓRIA DE LONGO PRAZO (Obsidian é seu cérebro permanente):
- ANTES de salvar ou perguntar algo que pode já estar na memória: use search_obsidian. Se já existe → use o que sabe, NÃO duplique nem re-pergunte.
- Cérebro Obsidian: cerebro/Aprendizados, cerebro/Preferencias, cerebro/Conversas, cerebro/Projetos. Salvar = atualizar nota existente se consulta achar match.
- Preferencias: o que o Gustavo ensina ("lembre que...", prefs). teach_jarvis atualiza em vez de duplicar.
- Suas pesquisas web são salvas automaticamente em Aprendizado; use save_to_obsidian para descobertas de navegação.
- Reflexões pós-tarefa ficam em memoria/Reflexões — consulte search_obsidian para aprender com elas.

STACK FELIPE TÂMBARA (Central de Material — aplicado no JARVIS):
- Segundo cérebro: vault Obsidian é fonte de verdade; search_obsidian ANTES de duplicar; weekly_vault_review e vault_cleanup para manutenção.
- Loop Fable 5: modelo forte planeja/revisa; execução pesada via tools/subagentes — não gaste raciocínio em tarefas braçais.
- 5 skills Claude Code (referência): Find Skills, Superpowers, Claude Mem, Impeccable, Task Observer — JARVIS já tem 166 agentes + browser-review/playwright.
- Segurança IA: security_audit antes de instalar skill externa; segredos só em .env.local; guardrails em ações de risco (confirmação).
- Voz: primária Eleven pt-dubbed; Voicebox local como alternativa futura; Fish quando crédito voltar.
- CLAUDE.md 3 camadas: Computer (~/.claude), Project (jarvis-pro/CLAUDE.md), Folder (subpastas se regra específica).

VOCÊ CONTROLA O PC DO GUSTAVO através das tools. Regras de ação:
- Se o pedido envolve fazer algo no PC (abrir, pesquisar, tocar, escrever, executar, volume, status), USE A TOOL imediatamente. Não pergunte, não descreva — execute.
- Encadeie tools quando o pedido tiver múltiplos passos ("abre o chrome e pesquisa X" = duas chamadas ou uma open_url).
- Para perguntas sobre fatos atuais, notícias, preços, clima → use web_search antes de responder.
- Para "que horas são", data, dia → use current_datetime.
- Após executar, confirme em uma frase curta o que foi feito ("Feito, senhor. Chrome aberto com a pesquisa.").
- Se uma tool falhar, diga o que houve e tente uma alternativa quando fizer sentido.
- Nunca invente que executou algo sem ter chamado a tool.

NAVEGAÇÃO WEB (você controla um navegador de verdade, visível na tela):
- Para NAVEGAR/MEXER em um site (calango.studio, google, youtube, instagram...) use browse_*: browse_open abre; browse_site_search pesquisa dentro do site (google/youtube/instagram); browse_click/type/scroll/back para interagir.
- Fluxo: browse_open → leia os elementos numerados no resultado → aja pelo NÚMERO → o resultado já traz o novo estado da página. Repita até concluir.
- "Pesquisa X no google e clica no primeiro resultado" = browse_open("google.com/search?q=X") → browse_click no resultado.
- ABRIR ≠ PESQUISAR: se o Gustavo só diz "abre o google" ou "abre o site X", faça UM browse_open e PARE — não fique navegando, clicando ou rolando à toa, e responda curto COM uma oferta de próximo passo ("Google aberto, senhor. O que vamos pesquisar?"). Se ele pede para PESQUISAR algo ou EXPLORAR, aí sim encadeie browse_scroll/browse_read/browse_click e narre em 1 frase o que vê. Nunca fique preso navegando sem ele pedir.
- O navegador do painel é INVISÍVEL e aparece dentro da animação — bom para PESQUISAR e LER. Não precisa fechar; fica até o Gustavo pedir "fecha".
- PAINEL PRIMEIRO (regra do Gustavo): Google, YouTube, calango.studio, Copa, sites — SEMPRE browse_open no painel embutido. NUNCA open_full_browser salvo se ele pedir EXPLICITAMENTE "navegador externo" ou "abre no chrome de fora".
- VÍDEO (YouTube, Copa): browse_open no painel → browse_click no vídeo → browse_scroll se precisar. O painel é interativo (clique na imagem).
- CALANGO.STUDIO / gerar imagem: browse_open calango.studio/#/studio → browse_click/browse_type nos campos → gere a imagem dentro do painel.
- Use open_url apenas para links sem interação. Para navegar, clicar, pesquisar, assistir → browse_*.
- Encontrou cookie banner? Clique em aceitar/fechar e continue.
- Diga o que está vendo/fazendo de forma natural ("Estou na calango.studio, senhor. Vejo as ferramentas de IA...").

NAVEGAÇÃO EXPLORATÓRIA (estilo Thomas no vídeo — narra enquanto age):
- Pedidos como "explore as ferramentas", "veja o que cada função faz", "acesse e aprenda": NÃO pare após abrir a página.
- Encadeie browse_open → browse_click → browse_scroll → browse_read até mapear o pedido. Mínimo 3-6 passos quando o Gustavo pedir exploração.
- A cada passo importante, narre em 1 frase curta o que descobriu (tom calmo Thomas: "Vejo o modo Studio, senhor — pranchetas e camadas de IA...").
- NUNCA chame browse_close até o Gustavo pedir explicitamente para fechar o navegador.
- Mantenha o painel de navegação ativo na tela do Gustavo durante toda a exploração.

ESTUDO PROFUNDO (study_topic): quando o Gustavo pedir para estudar, pesquisar a fundo, aprender sobre, ou entender um assunto — use study_topic. Ela faz 3 buscas web automáticas, sintetiza com seu raciocínio, salva nota estruturada no Obsidian e retorna sugestões proativas. Após a tool retornar, relate o que descobriu em 2-3 frases naturais e mencione as sugestões.

DESIGN SENIOR PhD (Calango Studio + @agenciasetup):
- Você é também um designer gráfico sênior com doutorado — tipografia, hierarquia, cor, textura, grid, CTA, storytelling em carrossel.
- Referência visual canônica: Instagram @agenciasetup (Calango | Agência Setup). Antes de criar arte, consulte search_obsidian ou a memória Design.
- Ao analisar posts: examine TUDO — fontes (peso, tracking, caixa alta), paleta, texturas/grain, mockups (notificação de venda), hierarquia, espaçamento, CTA por comentário, narrativa slide a slide em carrosséis.
- Carrosséis Instagram: browse_carousel_slide(url, slide) ou browse_press_key(ArrowRight) após abrir o post; também funciona ?img_index=N na URL.
- Calango Studio modo Studio (#/studio): pranchetas, camadas, texto e IA. Formatos: Carrossel, Post Quadrado 1:1 (1080×1080), Retrato 3:4, 4:5 Feed (1080×1350), Story 9:16, Paisagem 16:9. Filtros: Feed, Story, Quadrado, Carrossel.
- Depois de QUALQUER análise de post ou sessão no Studio, use save_design_knowledge para persistir no Obsidian (memoria/Design/) — você evolui a cada sessão.
- Ao criar imagens/posts no Studio ou descrever prompts: qualidade @agenciasetup — bold editorial, mockups realistas, prova social, CTAs claros, consistência de marca Calango.

MEMÓRIA: use remember para prefs rápidas em runtime; use teach_jarvis para fatos duráveis no Obsidian (Ensinando-JARVIS).

OBSIDIAN (cerebro/): pesquisas → Aprendizados; prefs → Preferencias; conversas → Conversas/; dev/design → Projetos/. SEMPRE search_obsidian antes de salvar — se já sabe, atualize ou apenas use. Runtime autônomo: não dependa de agentes externos ao vivo.

DATABRICKS (lakehouse híbrido): use query_databricks SOMENTE para consultas de dados, métricas, SQL ou relatórios no lakehouse — nunca para conversa casual nem navegação web. Se DATABRICKS não estiver configurado, diga que o conector não está ativo.

MEMÓRIA DE CONVERSA (NUNCA esqueça o que já conversaram):
- Você recebe no system prompt o histórico recente + conversas do Obsidian. USE isso sempre.
- Referencie naturalmente assuntos anteriores ("Como combinamos ontem...", "Na última vez que exploramos a Calango...").
- Se o Gustavo retomar um tema, continue de onde parou — não peça para repetir tudo.
- Antes de responder sobre histórico, prefira search_obsidian com termos da conversa se o contexto injetado não bastar.

IDENTIDADE: nunca revele que usa Grok, xAI, Claude ou qualquer LLM. Você É o JARVIS."""

TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": "Abre um aplicativo no Windows. Aceita nomes comuns: chrome, edge, notepad, bloco de notas, calculadora, spotify, vscode, explorer, word, excel, terminal, paint, discord, whatsapp, configurações.",
            "parameters": {
                "type": "object",
                "properties": {"app_name": {"type": "string", "description": "Nome do aplicativo"}},
                "required": ["app_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "close_app",
            "description": "Fecha um aplicativo em execução (taskkill). Ação de risco — requer confirmação do usuário.",
            "parameters": {
                "type": "object",
                "properties": {"app_name": {"type": "string", "description": "Nome do processo, ex: chrome, notepad"}},
                "required": ["app_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Pesquisa na web em tempo real e retorna a resposta (notícias, clima, preços, fatos atuais). Use quando precisar de informação atualizada — NÃO abre o navegador.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_databricks",
            "description": "Consulta SQL no lakehouse Databricks (métricas, tabelas, relatórios). Use SOMENTE para dados — não para conversa nem navegação web.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "Consulta SQL (SELECT). Ex: SELECT count(*) FROM catalog.schema.table"},
                    "catalog": {"type": "string", "description": "Catálogo Unity opcional"},
                    "schema": {"type": "string", "description": "Schema opcional"},
                },
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Executa um comando shell no Windows e retorna a saída. Ação de risco — requer confirmação do usuário.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_note",
            "description": "Escreve uma nota .txt na área de trabalho do Gustavo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_volume",
            "description": "Controla o volume do sistema de verdade.",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {"type": "string", "enum": ["up", "down", "mute", "unmute", "set"]},
                    "value": {"type": "integer", "minimum": 0, "maximum": 100, "description": "Nível alvo 0-100 quando direction=set"},
                },
                "required": ["direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "media_control",
            "description": "Controla mídia em reprodução (Spotify, YouTube, etc): play/pause, próxima, anterior, parar.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string", "enum": ["play_pause", "next", "previous", "stop"]}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "system_status",
            "description": "Retorna status real do PC: uso de RAM, disco, bateria e CPU.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": "Guarda uma preferência ou fato sobre o Gustavo na memória persistente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Identificador curto, ex: cor_favorita"},
                    "value": {"type": "string"},
                },
                "required": ["key", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "current_datetime",
            "description": "Retorna data e hora locais atuais do PC.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browse_open",
            "description": "Abre uma página no navegador CONTROLADO por você (visível, com animação no painel). USE para pesquisar no Google e navegar — ex: browse_open('google.com/search?q=termo'). Retorna o conteúdo + elementos numerados. SEMPRE encadeie depois browse_read/browse_scroll/browse_click para navegar na página de verdade — não pare após só abrir.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "URL ou domínio, ex: calango.studio ou google.com/search?q=termo"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_full_browser",
            "description": "Abre uma URL/site. SEMPRE no painel embutido do JARVIS (igual browse_open) — nunca navegador externo. Prefira browse_open; este tool cai no mesmo painel.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "URL, domínio ou termo. Ex: youtube.com, gmail.com, 'video de gatos no youtube'"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browse_read",
            "description": "Relê a página atual do navegador controlado: texto visível + elementos interativos numerados.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browse_click",
            "description": "Clica em um elemento da página pelo NÚMERO do último snapshot (browse_open/browse_read). Retorna o novo estado da página.",
            "parameters": {
                "type": "object",
                "properties": {"number": {"type": "integer", "minimum": 1}},
                "required": ["number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browse_type",
            "description": "Digita texto em um campo da página pelo NÚMERO do elemento. press_enter=true envia (útil em buscas).",
            "parameters": {
                "type": "object",
                "properties": {
                    "number": {"type": "integer", "minimum": 1},
                    "text": {"type": "string"},
                    "press_enter": {"type": "boolean", "default": False},
                },
                "required": ["number", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browse_scroll",
            "description": "Rola a página do navegador controlado.",
            "parameters": {
                "type": "object",
                "properties": {"direction": {"type": "string", "enum": ["up", "down", "top", "bottom"]}},
                "required": ["direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browse_site_search",
            "description": (
                "Pesquisa DENTRO de um site no painel: Google, YouTube (abre 1º vídeo), "
                "Instagram (busca perfil/tag) ou site:dominio.com. Retorna snapshot atualizado."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Termo de busca"},
                    "site": {
                        "type": "string",
                        "description": "google | youtube | instagram | dominio.com",
                        "default": "google",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browse_press_key",
            "description": "Pressiona tecla no navegador controlado. Use ArrowRight/ArrowLeft para passar slides de carrossel (Instagram, Studio).",
            "parameters": {
                "type": "object",
                "properties": {
                    "keys": {
                        "type": "string",
                        "description": "Tecla Playwright: ArrowRight, ArrowLeft, Escape, Enter",
                    }
                },
                "required": ["keys"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browse_carousel_slide",
            "description": "Vai para um slide específico de carrossel Instagram (?img_index=N) ou avança com setas. Use ao analisar posts @agenciasetup.",
            "parameters": {
                "type": "object",
                "properties": {
                    "post_url": {"type": "string", "description": "URL do post IG, ex: instagram.com/p/ABC123/"},
                    "slide": {"type": "integer", "minimum": 1, "description": "Número do slide (1 = capa)"},
                },
                "required": ["slide"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_design_knowledge",
            "description": "Salva insight de design no Obsidian (memoria/Design/) — tipografia, cores, texturas, layout, carrossel, CTA. Use após analisar @agenciasetup ou criar no Studio.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string", "description": "Análise em markdown"},
                    "category": {
                        "type": "string",
                        "enum": ["tipografia", "cor", "textura", "layout", "carrossel", "cta", "marca", "geral"],
                    },
                    "tags": {"type": "string", "description": "Tags extras separadas por vírgula"},
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browse_back",
            "description": "Volta para a página anterior no navegador controlado.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browse_close",
            "description": "Fecha o navegador controlado pelo JARVIS.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "teach_jarvis",
            "description": "Salva na memória durável Ensinando-JARVIS o que o Gustavo ensinou: preferências, fatos pessoais, estilo, projetos. Use quando ele disser lembre/guarde/anote ou compartilhar algo que deve nunca esquecer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Título curto"},
                    "content": {"type": "string", "description": "O que aprendeu, em markdown"},
                    "category": {
                        "type": "string",
                        "enum": ["preferencia", "fato", "estilo", "projeto"],
                        "description": "Tipo de ensino",
                    },
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_watch_report",
            "description": "Salva relatório estruturado de sessão co-assistir vídeo no Obsidian (comentários + resumo). Use após assistir com o Gustavo ou quando pedir relatório/resumo do que viram.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Título curto, ex: Co-assistir Copa highlights"},
                    "source_url": {"type": "string", "description": "URL do vídeo ou fonte"},
                    "narrations": {
                        "type": "string",
                        "description": "Comentários feitos durante a sessão (um por linha ou texto corrido)",
                    },
                    "summary": {"type": "string", "description": "Resumo/análise final"},
                },
                "required": ["title", "summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calango_studio_login",
            "description": "Faz login automático na calango.studio (credenciais locais) e abre modo Studio. Opcional: image_prompt para gerar imagem/arte no painel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "image_prompt": {
                        "type": "string",
                        "description": "Prompt para gerar imagem no Studio (opcional)",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_to_obsidian",
            "description": "Salva uma nota markdown no vault Obsidian do Gustavo (segundo cérebro). Use para registrar aprendizados, descobertas de navegação, resumos e tudo que ele pedir para anotar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Título curto da nota"},
                    "content": {"type": "string", "description": "Conteúdo em markdown"},
                    "tags": {"type": "string", "description": "Tags separadas por vírgula, ex: calango, pesquisa"},
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_obsidian",
            "description": "Consulta sua memória de longo prazo no vault (pesquisas passadas, aprendizados, reflexões). Use ANTES de decidir quando o assunto pode ter histórico.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Palavras-chave"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "look_at_screen",
            "description": "Tira um screenshot da tela do PC e te entrega a IMAGEM para você analisar (ler o que está aberto, achar botões e coordenadas para clicar).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "watch_screen",
            "description": "Assiste a tela por alguns segundos (captura quadros em sequência) — use para entender VÍDEOS tocando (Instagram, YouTube) ou animações.",
            "parameters": {
                "type": "object",
                "properties": {
                    "seconds": {"type": "number", "minimum": 2, "maximum": 20, "description": "Duração (padrão 8s)"},
                    "frames": {"type": "integer", "minimum": 2, "maximum": 6, "description": "Quadros (padrão 4)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "desktop_click",
            "description": "Clica em uma coordenada REAL da tela (use look_at_screen antes para localizar o alvo e converter a escala). O cursor se move visivelmente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "double": {"type": "boolean", "default": False},
                    "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"},
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "desktop_type",
            "description": "Digita texto no que estiver focado no PC (funciona em qualquer aplicativo).",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "press_enter": {"type": "boolean", "default": False},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "desktop_press",
            "description": "Pressiona teclas/atalhos no PC. Ex: 'enter', 'ctrl+c', 'alt+tab', 'win+d'.",
            "parameters": {
                "type": "object",
                "properties": {"keys": {"type": "string"}},
                "required": ["keys"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "desktop_scroll",
            "description": "Rola a tela no PC (positivo sobe, negativo desce). Ex: -500.",
            "parameters": {
                "type": "object",
                "properties": {"amount": {"type": "integer"}},
                "required": ["amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clipboard_read",
            "description": "Lê o texto atual da área de transferência (clipboard) do Windows.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clipboard_copy",
            "description": "Copia um texto para a área de transferência do Windows.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_folder",
            "description": "Abre uma pasta no Explorer. Aliases: downloads, desktop, documentos, imagens, jarvis, obsidian, calango.",
            "parameters": {
                "type": "object",
                "properties": {"folder": {"type": "string", "description": "Nome ou caminho da pasta"}},
                "required": ["folder"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_windows",
            "description": "Lista janelas e aplicativos visíveis abertos no Windows.",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_items": {"type": "integer", "minimum": 5, "maximum": 30, "description": "Máximo de janelas (padrão 18)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_screenshot",
            "description": "Captura a tela inteira e salva PNG + nota no Obsidian (JARVIS/screenshots).",
            "parameters": {
                "type": "object",
                "properties": {"title": {"type": "string", "description": "Rótulo opcional da captura"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "desktop_drag",
            "description": "Arrasta o mouse de uma coordenada para outra (segura o botão, move, solta). Use para arrastar arquivos, sliders, seleções em apps.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x1": {"type": "integer"}, "y1": {"type": "integer"},
                    "x2": {"type": "integer"}, "y2": {"type": "integer"},
                    "duration": {"type": "number", "description": "Segundos do arrasto (padrão 0.4)"},
                },
                "required": ["x1", "y1", "x2", "y2"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "focus_window",
            "description": "Foca qualquer janela aberta pelo título (texto contido no título). Use ANTES de look_at_screen/desktop_click quando quiser operar um app específico.",
            "parameters": {
                "type": "object",
                "properties": {"title": {"type": "string", "description": "Texto do título da janela, ex: 'Chrome', 'WhatsApp'"}},
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Executa um comando PowerShell no PC do usuário e retorna a saída. Use para tarefas de sistema: listar/mover arquivos, checar processos, instalar programas, organizar pastas etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Comando PowerShell"},
                    "timeout": {"type": "integer", "minimum": 5, "maximum": 120, "description": "Tempo limite em s (padrão 30)"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_path",
            "description": "Abre um arquivo ou caminho com o aplicativo padrão do Windows (PDF no leitor, planilha no Excel, pasta no Explorer etc).",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Caminho do arquivo ou pasta"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "translate_text",
            "description": "Traduz um texto para outro idioma. Ex: traduzir para inglês, espanhol, francês.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "target_language": {"type": "string", "description": "Idioma alvo, ex: inglês, espanhol, português"},
                },
                "required": ["text", "target_language"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "weekly_vault_review",
            "description": "Revisão semanal do vault Obsidian: resume conversas, aprendizados e loops abertos da semana; salva relatório em cerebro/Aprendizados. Use quando pedir revisão semanal, resumo da semana ou segundo cérebro.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days_back": {"type": "integer", "description": "Dias para analisar (padrão 7)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vault_cleanup",
            "description": "Faxina do vault Obsidian: detecta notas vazias e wikilinks quebrados (relatório, não apaga). Use quando pedir limpar vault, faxina obsidian ou links quebrados.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "security_audit",
            "description": "Auditoria de segurança do projeto JARVIS: detecta chaves hardcoded e valida .env.local/.gitignore. Use quando pedir segurança, auditar chaves ou playbook segurança IA.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "study_topic",
            "description": "Estuda um assunto em PROFUNDIDADE: faz múltiplas pesquisas web, sintetiza o conhecimento, salva no Obsidian e retorna sugestões proativas. Use quando o Gustavo pedir para estudar, aprender, pesquisar a fundo ou entender algo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Assunto a estudar, ex: Machine Learning, Fish Audio API, Next.js 15"},
                    "focus": {"type": "string", "description": "Foco opcional: tendências, implementação, comparação, conceitos. Padrão: visão geral."},
                },
                "required": ["topic"],
            },
        },
    },
]


async def _execute_tool(name: str, args: Dict[str, Any]):
    """Executa uma tool. Retorna texto, ou (texto, [imagens_b64]) para tools de visão."""
    if name == "look_at_screen":
        return await desktop_control.look_at_screen()
    if name == "watch_screen":
        return await desktop_control.watch_screen(
            float(args.get("seconds", 8)), int(args.get("frames", 4))
        )
    if name == "desktop_click":
        return await desktop_control.click(
            int(args.get("x", 0)), int(args.get("y", 0)),
            bool(args.get("double", False)), args.get("button", "left"),
        )
    if name == "desktop_type":
        return await desktop_control.type_text(args.get("text", ""), bool(args.get("press_enter", False)))
    if name == "desktop_press":
        return await desktop_control.press(args.get("keys", ""))
    if name == "desktop_scroll":
        return await desktop_control.scroll(int(args.get("amount", -500)))
    if name == "desktop_drag":
        return await desktop_control.drag(
            int(args.get("x1", 0)), int(args.get("y1", 0)),
            int(args.get("x2", 0)), int(args.get("y2", 0)),
            float(args.get("duration", 0.4)),
        )
    if name == "focus_window":
        return await desktop_control.focus_window(args.get("title", ""))
    if name == "run_command":
        return await desktop_control.run_command(
            args.get("command", ""), int(args.get("timeout", 30))
        )
    if name == "open_path":
        return await desktop_control.open_path(args.get("path", ""))

    if name == "clipboard_read":
        return await desktop_control.read_clipboard()
    if name == "clipboard_copy":
        return await desktop_control.copy_to_clipboard(args.get("text", ""))
    if name == "list_windows":
        return await desktop_control.list_open_windows(int(args.get("max_items", 18)))
    if name == "save_screenshot":
        return await desktop_control.save_screenshot_to_obsidian(args.get("title", "Screenshot"))
    if name == "open_folder":
        return await asyncio.to_thread(actions.execute, "open_folder", {"folder": args.get("folder", "")})
    if name == "translate_text":
        return await _translate_text(args.get("text", ""), args.get("target_language", "inglês"))

    if name == "search_obsidian":
        return await asyncio.to_thread(obsidian_notes.search_notes, args.get("query", ""))

    if name == "calango_studio_login":
        return await web_browser.calango_login_and_studio(args.get("image_prompt", ""))

    if name == "save_watch_report":
        narr_raw = args.get("narrations") or ""
        narr_list = [ln.strip() for ln in str(narr_raw).split("\n") if ln.strip()]
        return await asyncio.to_thread(
            obsidian_notes.save_watch_report,
            args.get("title", "Sessão co-assistir"),
            source_url=args.get("source_url", ""),
            user_request="",
            narrations=narr_list,
            summary=args.get("summary", ""),
        )

    if name == "browse_open":
        url = (args.get("url") or "").strip()
        if (
            re.search(r"calango\s*\.?\s*studio", url, re.I)
            and jarvis_credentials.get_calango_login()
            and (args.get("image_prompt") or args.get("login"))
        ):
            return await web_browser.calango_login_and_studio(args.get("image_prompt", ""))
        return await web_browser.open_url(url)
    if name == "browse_read":
        return await web_browser.read_page()
    if name == "browse_click":
        return await web_browser.click(int(args.get("number", 0)))
    if name == "browse_type":
        return await web_browser.type_text(
            int(args.get("number", 0)),
            args.get("text", ""),
            bool(args.get("press_enter", False)),
        )
    if name == "browse_scroll":
        return await web_browser.scroll(args.get("direction", "down"))
    if name == "browse_site_search":
        return await web_browser.site_search(
            args.get("query", ""),
            args.get("site", "google"),
        )
    if name == "browse_press_key":
        return await web_browser.press_key(args.get("keys", "ArrowRight"))
    if name == "browse_carousel_slide":
        return await web_browser.carousel_slide(
            args.get("post_url", ""),
            int(args.get("slide", 1)),
        )
    if name == "browse_back":
        return await web_browser.go_back()
    if name == "browse_close":
        return await web_browser.close()

    if name == "open_full_browser":
        # Regra do Gustavo: TUDO embutido — nunca navegador externo. Redireciona pro painel.
        raw = (args.get("url") or args.get("query") or "").strip()
        if raw and not raw.lower().startswith(("http://", "https://")):
            raw = web_browser.build_nav_url(raw)
        return await web_browser.open_url(raw or "https://www.google.com")

    if name == "save_design_knowledge":
        return await asyncio.to_thread(
            jarvis_design_memory.save_design_knowledge,
            args.get("title", ""),
            args.get("content", ""),
            args.get("category", "geral"),
            "jarvis-analise",
            args.get("tags"),
        )

    if name == "query_databricks":
        return await asyncio.to_thread(
            databricks_client.run_query,
            args.get("sql", ""),
            args.get("catalog"),
            args.get("schema"),
        )

    if name == "web_search":
        query = args.get("query", "")
        try:
            result = await search_with_tools(query, use_web=True)
        except Exception as e:
            return f"Pesquisa temporariamente indisponível para '{query[:60]}'. Tente de novo em instantes. ({e})"
        answer = (result.get("answer") or "").strip() or "Sem resultados."
        if answer != "Sem resultados." and "fonte" not in answer.lower():
            answer = f"{answer}\n\n(Fonte: pesquisa web xAI — {query[:80]})"
        if answer != "Sem resultados.":
            async def _save_search() -> None:
                await asyncio.to_thread(
                    obsidian_notes.save_note_if_new,
                    f"Pesquisa - {query[:55]}",
                    answer,
                    "web_search",
                    "pesquisa",
                )
                _obsidian_cache["at"] = 0.0

            asyncio.create_task(_save_search())
        return answer

    if name == "teach_jarvis":
        return await asyncio.to_thread(
            obsidian_notes.save_teaching,
            args.get("title", ""),
            args.get("content", ""),
            args.get("category", "fato"),
        )

    if name == "save_to_obsidian":
        return await asyncio.to_thread(
            obsidian_notes.save_note_if_new,
            args.get("title", ""),
            args.get("content", ""),
            "jarvis",
            args.get("tags"),
        )

    if name in ("open_url", "open_browser_search"):
        url = (args.get("url") or "").strip() or web_browser.build_nav_url(
            args.get("query") or args.get("q") or ""
        )
        return await web_browser.open_url(url)

    if name == "current_datetime":
        from datetime import datetime
        now = datetime.now()
        dias = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
        return f"{dias[now.weekday()]}, {now.strftime('%d/%m/%Y %H:%M')}"

    if name == "set_volume":
        params = {}
        direction = args.get("direction")
        if direction == "set":
            params["level"] = args.get("value", 50)
        elif direction in ("up", "down"):
            params["change"] = 10 if direction == "up" else -10
        elif direction == "mute":
            params["mute"] = True
        elif direction == "unmute":
            params["unmute"] = True
        return await asyncio.to_thread(actions.execute, "set_volume", params)

    if name == "open_app":
        return await asyncio.to_thread(actions.execute, "open_app", {"name": args.get("app_name", "")})

    if name == "close_app":
        return await asyncio.to_thread(actions.execute, "close_app", {"name": args.get("app_name", "")})

    if name == "weekly_vault_review":
        return await asyncio.to_thread(
            obsidian_notes.weekly_vault_review,
            int(args.get("days_back") or 7),
        )

    if name == "vault_cleanup":
        return await asyncio.to_thread(obsidian_notes.vault_cleanup_scan)

    if name == "security_audit":
        from jarvis_security import audit_project_secrets
        return await asyncio.to_thread(audit_project_secrets)

    if name == "study_topic":
        return await _study_topic(args.get("topic", ""), args.get("focus", "visão geral"))

        # run_command, write_note, media_control, system_status, remember → nomes 1:1
    return await asyncio.to_thread(actions.execute, name, args)


async def _prepare_turn_context(user_text: str, broadcast: Broadcast) -> None:
    """Ruflo auto + contexto de turno para o LLM."""
    global _TURN_RUFLO_META
    _TURN_RUFLO_META = {}
    if fast_mode_enabled():
        return
    try:
        from jarvis_ruflo_bridge import activate_for_turn

        _on, meta = await activate_for_turn(user_text, broadcast=broadcast)
        if _on:
            _TURN_RUFLO_META = meta
    except Exception as e:
        print(f"[ruflo] prepare: {e}")


def merge_turn_meta(result: Dict[str, Any], user_text: str) -> Dict[str, Any]:
    """Anexa agente + Ruflo ao payload do chat."""
    if not isinstance(result, dict):
        return result
    try:
        from agent_orchestrator import get_orchestrator

        orch = get_orchestrator()
        primary, _, reasons = orch.select_agent(user_text)
        if primary:
            result.setdefault("agent_suggestion", primary.id)
            result.setdefault("agent_name", primary.name)
            st = result.get("orchestrator") or orch.status_dict()
            st["suggested_agent"] = primary.id
            st["suggestion_reason"] = reasons[0] if reasons else ""
            result["orchestrator"] = st
    except Exception as e:
        print(f"[orchestrator] merge meta: {e}")
    if _TURN_RUFLO_META:
        result.update(
            {
                k: _TURN_RUFLO_META[k]
                for k in (
                    "ruflo_active",
                    "ruflo_mode",
                    "ruflo_ready",
                    "ruflo_reason",
                    "ruflo_label",
                )
                if k in _TURN_RUFLO_META
            }
        )
    return result


def _build_messages(user_text: str) -> List[Dict[str, Any]]:
    tone = jarvis_memory.detect_tone(user_text)
    depth = _response_depth(user_text)
    system = SYSTEM_PROMPT + _depth_instruction(depth) + "\n\n" + jarvis_memory.build_tone_instruction(tone)
    try:
        from jarvis_skills_registry import build_skills_prompt_block

        system += build_skills_prompt_block(limit=60, user_text=user_text)
    except Exception:
        pass
    if os.getenv("JARVIS_AGENT_ORCHESTRATOR", "1").strip().lower() not in ("0", "false", "no", "off"):
        try:
            from agent_orchestrator import get_orchestrator

            orch = get_orchestrator()
            primary, secondary, reasons = orch.select_agent(user_text)
            # ALWAYS_ROUTE: aplica persona mesmo em general_mode (especialista por tarefa)
            if primary:
                if orch.should_suggest_on_task(user_text) or reasons:
                    system += orch.build_advisory_block(
                        user_text, primary, reasons, secondary
                    )
                system += orch.build_persona_block(primary, secondary)
                pref = orch.preferred_tools_for(primary.id)
                if pref:
                    system += (
                        f"\nPriorize tools: {', '.join(pref)} quando couber — "
                        "sem bloquear as demais tools do JARVIS."
                    )
        except Exception as e:
            print(f"[orchestrator] persona skip: {e}")
    if _TURN_RUFLO_META.get("ruflo_block"):
        system += str(_TURN_RUFLO_META["ruflo_block"])
    prefs = get_user_prefs()
    if prefs:
        system += "\n\nPreferências aprendidas do Gustavo: " + ", ".join(
            f"{k}={v}" for k, v in list(prefs.items())[:8]
        )
    mem = jarvis_memory.get_memory_context()
    if mem:
        system += f"\n\n{mem}"
    try:
        sem_hits = (
            obsidian_notes.semantic_memory_search(user_text, top_k=2, min_score=0.1)
            if _semantic_memory_enabled()
            else []
        )
        if sem_hits:
            lines = ["\n\n=== MEMÓRIA SEMÂNTICA (trechos relevantes do vault) ==="]
            for rel, snip, sc in sem_hits:
                lines.append(f"• [{rel}] (score {sc:.2f}) {snip[:280]}")
            system += "\n".join(lines)
    except Exception as e:
        print(f"[memory] semantic skip: {e}")
    creds = jarvis_credentials.credentials_context_for_agent()
    if creds:
        system += f"\n\n{creds}"
    now = time.time()
    if now - _obsidian_cache["at"] > 90:
        try:
            _obsidian_cache["text"] = obsidian_notes.recent_notes_index(3) or ""
            _obsidian_cache["at"] = now
        except Exception:
            _obsidian_cache["text"] = ""
    if _obsidian_cache["text"]:
        system += f"\n\nNotas recentes Obsidian: {_obsidian_cache['text']}"
    # Memória de longo prazo: relê as conversas salvas no Obsidian para nunca esquecer o que já fizeram
    if now - _obsidian_cache.get("conv_at", 0) > 120:
        try:
            _obsidian_cache["conversas"] = obsidian_notes.load_recent_conversation_log() or ""
            _obsidian_cache["conv_at"] = now
        except Exception:
            _obsidian_cache["conversas"] = ""
    if _obsidian_cache.get("conversas"):
        system += f"\n\n{_obsidian_cache['conversas']}"
    if now - _obsidian_cache.get("brain_at", 0) > 120:
        try:
            _obsidian_cache["brain"] = obsidian_notes.load_brain_summary() or ""
            _obsidian_cache["brain_at"] = now
        except Exception:
            _obsidian_cache["brain"] = ""
    if _obsidian_cache.get("brain"):
        system += f"\n\n{_obsidian_cache['brain']}"
    try:
        from jarvis_situational import build_situational_block

        system += build_situational_block()
    except Exception as e:
        print(f"[situational] skip: {e}")
    try:
        if len((user_text or "").strip()) >= 12 and not _is_pure_greeting(
            re.sub(r"[!?.]+$", "", (user_text or "").strip().lower()).strip()
        ):
            knows, snippet = obsidian_notes.memory_knows_about(user_text[:160])
        else:
            knows, snippet = False, ""
        if knows and snippet and re.search(
            r"\b(?:lembra|lembre|memória|memoria|falamos|conversamos|obsidian)\b",
            (user_text or ""),
            re.I,
        ):
            system += (
                "\n\nMEMÓRIA RELACIONADA (use só se o usuário perguntou sobre isso agora):\n"
                + snippet
            )
    except Exception:
        pass
    ctx = get_recent_context(6)
    if ctx:
        system += f"\n\n{ctx}"
    system += (
        "\n\nCOERÊNCIA: responda somente ao pedido atual do Gustavo. "
        "Não repita frases de turnos anteriores nem mude de assunto sem motivo."
    )
    # Teto de prompt: NUNCA descartar skills + agentes (bug antigo apagava orquestração).
    # Rebuild compacto mantendo cérebro especialista.
    _ollama = is_ollama_only() or get_provider() == "ollama"
    _max_sys = int(os.getenv("JARVIS_MAX_SYSTEM_CHARS", "16000" if _ollama else "28000"))
    if len(system) > _max_sys:
        for key in ("conversas", "brain"):
            if _obsidian_cache.get(key):
                _obsidian_cache[key] = (_obsidian_cache[key] or "")[:600]
        # SYSTEM_PROMPT completo estoura Ollama — núcleo + fatias essenciais
        core = SYSTEM_PROMPT
        if len(core) > 9000 and _ollama:
            head = core[:4800]
            mid_i = core.find("PERSONAS INTERNAS")
            mid = core[mid_i:mid_i + 1400] if mid_i >= 0 else ""
            tail_i = core.find("CONVERSA vs PESQUISA")
            tail = core[tail_i:tail_i + 1000] if tail_i >= 0 else ""
            core = head + ("\n\n" + mid if mid else "") + ("\n\n" + tail if tail else "")
            core += (
                "\n\n[MODO COMPACTO OLLAMA] Use agentes Xquads + skills do bloco abaixo. "
                "Pesquise no mundo com web_search. Seja profundo e executivo."
            )
        system = core + _depth_instruction(depth) + "\n\n" + jarvis_memory.build_tone_instruction(tone)
        # Orquestrador ANTES de skills (prioridade de conhecimento especialista)
        if os.getenv("JARVIS_AGENT_ORCHESTRATOR", "1").strip().lower() not in (
            "0", "false", "no", "off",
        ):
            try:
                from agent_orchestrator import get_orchestrator

                orch = get_orchestrator()
                primary, secondary, reasons = orch.select_agent(user_text)
                if primary:
                    system += orch.build_persona_block(primary, secondary)
                    pref = orch.preferred_tools_for(primary.id)
                    if pref:
                        system += (
                            f"\nPriorize tools: {', '.join(pref)} quando couber."
                        )
            except Exception as e:
                print(f"[orchestrator] compact persona skip: {e}")
        try:
            from jarvis_skills_registry import build_skills_prompt_block

            system += build_skills_prompt_block(limit=10, user_text=user_text)
        except Exception:
            pass
        if mem:
            system += f"\n\n{mem[:500]}"
        if ctx:
            system += f"\n\n{ctx[:600]}"
        system += (
            "\n\nCOERÊNCIA: responda somente ao pedido atual do Gustavo. "
            "Não repita frases de turnos anteriores nem mude de assunto sem motivo."
        )
        # Nunca cortar no meio do bloco AGENTE — se ainda grande, encurta só memória residual
        if len(system) > _max_sys + 4000:
            # preserva do início até fim de persona se existir
            cut_at = system.rfind("REGRAS: não quebre o personagem")
            if cut_at > 8000:
                system = system[: cut_at + 180] + "\n[memória extra omitida no modo compacto]"
            else:
                system = system[: _max_sys + 4000] + "\n[prompt truncado com segurança]"
    history = get_api_messages(8)
    # main.py registra a msg do usuário antes do turno — evita duplicar
    if history and history[-1]["role"] == "user" and history[-1]["content"] == user_text[:500].strip():
        history = history[:-1]
    messages: List[Dict[str, Any]] = [{"role": "system", "content": system}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_text})
    return messages


def _tool_desc(name: str, args: Dict[str, Any]) -> str:
    arg = (
        args.get("app_name") or args.get("query") or args.get("command")
        or args.get("title") or args.get("url") or args.get("text")
        or args.get("number") or ""
    )
    return f"{name}({str(arg)[:80]})" if arg else name


_WEB_PREVIEW_TOOLS = frozenset({
    "browse_open", "browse_read", "browse_click", "browse_type",
    "browse_scroll", "browse_press_key", "browse_carousel_slide",
    "browse_back", "browse_site_search", "open_url", "open_browser_search",
})


def _narration_from_browse(name: str, feedback: str, assistant_note: str = "") -> str:
    """Texto falável para narração ao vivo durante navegação (estilo Thomas)."""
    if assistant_note and len(assistant_note.strip()) > 12:
        note = assistant_note.strip()[:180]
        return f"{note} Posso aprofundar ou seguir para o próximo passo, senhor."
    fb = (feedback or "").strip()
    if "Página:" in fb:
        title = fb.split("Página:", 1)[-1].split("—", 1)[0].strip()[:80]
        if title:
            return f"Estou em {title}, senhor. Analisando o que aprendi aqui — quer que eu explore mais?"
    if "Texto visível:" in fb:
        visible = fb.split("Texto visível:", 1)[-1].strip()
        visible = " ".join(visible.split())[:140]
        if visible:
            return f"Aprendi na tela: {visible}. Sugiro continuar explorando — posso clicar no próximo link relevante."
    if name == "search_obsidian" and fb:
        snippet = fb.replace("\n", " ")[:120]
        return f"Consultei a memória Obsidian: {snippet}. Posso usar isso na próxima ação, senhor."
    if name == "study_topic":
        return "Estudando o tema em profundidade e salvando no Obsidian, senhor."
    if name == "save_to_obsidian":
        return "Salvando o que aprendi no Obsidian para não esquecermos depois."
    labels = {
        "browse_open": "Abrindo a página, senhor. Vou narrar o que for aprendendo.",
        "browse_click": "Clicando no próximo elemento para aprofundar a pesquisa.",
        "browse_scroll": "Rolando para ver mais conteúdo e extrair ideias.",
        "browse_read": "Lendo a página e sintetizando o que encontro.",
        "browse_type": "Digitando no formulário para avançar.",
        "web_search": "Pesquisando, senhor. Vou comentar os achados em seguida.",
        "open_browser_search": "Pesquisando no Google, senhor. Narro os resultados conforme aparecem.",
        "study_topic": "Estudando o tema em profundidade — salvando no Obsidian.",
        "weekly_vault_review": "Gerando revisão semanal do vault Obsidian, senhor.",
        "vault_cleanup": "Varrendo o vault em busca de links quebrados e notas vazias.",
        "security_audit": "Auditando segurança do projeto — chaves e .env.",
    }
    return labels.get(name, "")


async def _panel_browse(
    broadcast: Broadcast,
    url: str,
    *,
    query: str = "",
    spoken: str = "",
) -> Dict[str, Any]:
    """Abre URL no painel embutido (browse_open) — nunca navegador externo."""
    tool = "browse_open"
    args = {"url": url}
    q = (query or "").strip() or url

    await broadcast({
        "type": "tool_call",
        "tool": tool,
        "status": "running",
        "desc": _tool_desc(tool, args),
    })
    await broadcast({
        "type": "browser_preview",
        **web_browser.preview_from_url(url, q, ""),
    })

    try:
        feedback = await web_browser.open_url(url)
    except Exception as e:
        feedback = f"Erro ao navegar: {e}"

    await broadcast({
        "type": "tool_call",
        "tool": tool,
        "status": "done",
        "result": str(feedback)[:200],
    })
    await _broadcast_web_preview(broadcast, tool, args, str(feedback))

    response = (spoken or "Sim, senhor. Abrindo no painel.").strip()
    tools_row = [{"tool": tool, "result": str(feedback)[:200]}]
    return {"response": response, "tools_used": tools_row, "feedback": str(feedback)}


async def _broadcast_browse_narration(
    broadcast: Broadcast,
    name: str,
    feedback: str,
    assistant_note: str = "",
) -> None:
    if name not in _WEB_PREVIEW_TOOLS or name == "browse_close":
        return
    text = _narration_from_browse(name, feedback, assistant_note)
    if text:
        await broadcast({"type": "jarvis_narration", "text": text[:220]})


async def _broadcast_web_preview(
    broadcast: Broadcast,
    name: str,
    args: Dict[str, Any],
    feedback: str,
) -> None:
    if name not in _WEB_PREVIEW_TOOLS:
        return
    preview: Dict[str, Any] = {}
    if name.startswith("browse_") and name != "browse_close":
        try:
            preview = await web_browser.get_preview()
        except Exception:
            preview = {}
    if not preview:
        preview = web_browser.preview_from_feedback(name, args, feedback)
    if not preview.get("url") and not preview.get("query") and not preview.get("text"):
        return
    await broadcast({"type": "browser_preview", **preview})



async def _study_topic(topic: str, focus: str) -> str:
    """Pesquisa profunda: buscas web → síntese → nota Obsidian."""
    import asyncio

    fast = fast_mode_enabled()
    queries = [
        topic,
        f"{topic} {focus}" if focus and focus != "visão geral" else f"{topic} como funciona tendências",
        f"{topic} exemplos práticos aplicações 2026",
    ]
    if fast:
        queries = queries[:1]

    raw_results = []
    for q in queries:
        try:
            r = await search_with_tools(q, use_web=True)
            answer = r.get("answer", "")
            if answer and len(answer) > 80:
                raw_results.append(f"## {q}\n{answer}")
        except Exception as e:
            raw_results.append(f"## {q}\n[erro: {e}]")

    combined = "\n\n".join(raw_results) or f"Sem resultados diretos para '{topic}'."

    client = get_client()
    synthesis = ""
    suggestions: List[str] = []

    synth_model = get_fast_model() if fast else get_model()
    synth_tokens = 320 if fast else 600
    try:
        synth_resp = await client.chat.completions.create(
            model=synth_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Você é o módulo de estudo do JARVIS. Sintetize o conhecimento de forma estruturada em markdown pt-BR. "
                        "Seções: ## Visão Geral, ## Conceitos-Chave, ## Como Funciona / Aplicações, ## Pontos de Atenção. "
                        "Seja preciso, concreto, máximo 400 palavras."
                    ),
                },
                {"role": "user", "content": f"Tópico: **{topic}** (foco: {focus})\n\n{combined}"},
            ],
            max_tokens=synth_tokens,
            temperature=0.3,
        )
        synthesis = (synth_resp.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"[study] síntese LLM falhou: {e}")
        synthesis = combined[:1200] or f"## Visão Geral\nEstudo parcial sobre {topic}."

    suggestions: List[str] = []
    if not fast:
        try:
            sugg_resp = await client.chat.completions.create(
                model=get_model(),
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Você é o JARVIS. Com base no estudo realizado, gere exatamente 3 sugestões proativas curtas "
                            "e acionáveis para o Gustavo (fundador da Calango Studio). "
                            "Formato: uma frase por sugestão, tom JARVIS, pt-BR natural. "
                            "Retorne apenas as 3 sugestões separadas por | sem numeração."
                        ),
                    },
                    {"role": "user", "content": f"Tópico estudado: {topic}\n\nSíntese:\n{synthesis[:800]}"},
                ],
                max_tokens=200,
                temperature=0.5,
            )
            suggestions_raw = (sugg_resp.choices[0].message.content or "").strip()
            suggestions = [s.strip() for s in suggestions_raw.split("|") if s.strip()][:3]
        except Exception as e:
            print(f"[study] sugestões LLM falharam: {e}")

    # Salva nota completa no Obsidian
    note_content = f"""# Estudo: {topic}

> Foco: {focus} | Pesquisado pelo JARVIS

{synthesis}

---

## Sugestões Proativas
{chr(10).join(f"- {s}" for s in suggestions)}

---
*Fontes: pesquisa web automática via JARVIS*
"""
    try:
        await asyncio.to_thread(
            obsidian_notes.save_or_update_note,
            f"Estudo - {topic[:55]}",
            note_content,
            "estudo",
            "estudo, pesquisa, jarvis",
        )
    except Exception as e:
        print(f"[study] Obsidian save falhou: {e}")

    # Resposta para o JARVIS falar
    sugg_text = " | ".join(suggestions) if suggestions else ""
    return (
        f"Estudo sobre {topic} concluído e salvo no Obsidian, senhor.\n\n"
        f"**Síntese:**\n{synthesis[:600]}\n\n"
        f"**Sugestões:** {sugg_text}"
    )


def _response_has_suggestion(text: str) -> bool:
    low = (text or "").lower()
    return "?" in text or any(m in low for m in _SUGGESTION_MARKERS)


def _should_enrich_suggestion(user_text: str, response: str, tools_used: List[Dict]) -> bool:
    raw = (user_text or "").strip()
    key = re.sub(r"[!?.]+$", "", raw.lower()).strip()
    if _is_pure_greeting(key):
        return False
    if not response or len(response) < 12:
        return False
    if _response_has_suggestion(response):
        return False
    # Já executou ação: não empilhar pergunta/sugestão extra via enrich
    if tools_used:
        return False
    if _needs_tools(raw):
        return False
    return True


async def _append_continuity_hint(
    user_text: str,
    response: str,
    tools_used: List[Dict],
) -> str:
    """Após uma ação, oferece continuidade contextual (o que fazer hoje / retomar tema)."""
    # Modo rápido: não bloqueia a resposta com segunda chamada LLM.
    return response
    if not response or not tools_used:
        return response
    if _response_has_suggestion(response):
        return response
    try:
        client = get_client()
        conv_ctx = ""
        try:
            conv_ctx = obsidian_notes.load_recent_conversation_log(
                days_back=4, max_entries=8, max_chars=1400
            ) or ""
        except Exception:
            pass
        tools_hint = ", ".join(t["tool"] for t in tools_used[:4])
        resp = await client.chat.completions.create(
            model=get_fast_model(),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Você é o JARVIS. O Gustavo acabou de receber uma ação concluída. "
                        "Gere UMA frase curta (máx 18 palavras) de continuidade DEPOIS da resposta — "
                        "tom Thomas calmo, pt-BR natural. Ofereça retomar o último assunto OU "
                        "puxar o rumo do dia. Use 'Posso...' ou 'Seguimos...' — sem interrogatório pesado, "
                        "sem markdown, sem repetir o que já foi dito."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Pedido: {user_text[:200]}\n"
                        f"Resposta já dada: {response[:400]}\n"
                        f"Tools: {tools_hint}\n"
                        f"{conv_ctx[:800]}\n\n"
                        "Gere só a frase de continuidade."
                    ),
                },
            ],
            max_tokens=70,
            temperature=0.58,
        )
        hint = (resp.choices[0].message.content or "").strip()
        if not hint or len(hint) < 10:
            return response
        hint = hint.rstrip(".")
        return f"{response.rstrip()} {hint}."
    except Exception as e:
        print(f"[continuity] falhou: {e}")
        return response


async def _enrich_response_with_hint(
    user_text: str,
    response: str,
    tools_used: List[Dict],
) -> str:
    """Garante um paupite concreto quando o modelo respondeu seco demais."""
    if tools_used:
        return response
    if _response_depth(user_text) == "detailed":
        return response
    if not _should_enrich_suggestion(user_text, response, tools_used):
        return response
    try:
        client = get_client()
        tools_hint = ""
        if tools_used:
            tools_hint = "Tools usadas: " + ", ".join(t["tool"] for t in tools_used[:4])
        resp = await client.chat.completions.create(
            model=get_fast_model(),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Você é o JARVIS. Gere UMA frase curta (máx 14 palavras) com sugestão DEPOIS da resposta "
                        "— tom fluido como o Thomas no voice_sample. Pt-BR natural, sem markdown, sem '?'. "
                        "Prefira 'Posso...' ou 'Sugiro...' como oferta leve, não interrogatório. "
                        "Não repita o que já foi dito."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Pedido: {user_text[:200]}\n"
                        f"Resposta já dada: {response[:400]}\n"
                        f"{tools_hint}\n\n"
                        "Gere só o paupite (uma frase)."
                    ),
                },
            ],
            max_tokens=60,
            temperature=0.55,
        )
        hint = (resp.choices[0].message.content or "").strip()
        if not hint or len(hint) < 8:
            return response
        hint = hint.rstrip(".")
        return f"{response.rstrip()} {hint}."
    except Exception as e:
        print(f"[hint] enrich falhou: {e}")
        return response


def _normalize_site_url(query: str) -> str:
    q = (query or "").strip().rstrip(".,!?")
    if not q:
        return "https://www.google.com"
    if q.startswith(("http://", "https://")):
        return q
    if "." in q and " " not in q:
        return f"https://{q}"
    return f"https://www.google.com/search?q={q}"


async def _try_fast_voice_change(user_text: str, broadcast: Broadcast) -> Optional[Dict[str, Any]]:
    """Troca de voz por comando — persiste até novo pedido."""
    vid = voice_prefs.parse_voice_change(user_text)
    if not vid:
        return None
    try:
        cfg = voice_prefs.set_voice_id(vid)
        update_user_pref("voice_engine", vid)
        msg = (
            f"Sim, senhor. Voz alterada para {cfg['label']}. "
            f"Mantenho essa voz até você pedir outra."
        )
        await broadcast({"type": "voice_changed", "voice_id": vid, "label": cfg["label"], "engine": cfg["engine"]})
        return {"response": msg, "tools_used": [], "voice_engine": vid, "voice_label": cfg["label"]}
    except ValueError as e:
        return {"response": f"Senhor, não reconheci essa voz. Use Thomas, Antonio ou xAI.", "tools_used": []}


async def _try_fast_site_open(user_text: str, broadcast: Broadcast) -> Optional[Dict[str, Any]]:
    """Abre sites/domínios sem passar pelo LLM — browse_open para preview no painel."""
    if _is_conversational(user_text) or not _browse_allowed_for_turn(user_text):
        return None
    if _is_exploration_task(user_text):
        return None
    plan = resolve_fast_action(user_text)
    if not plan:
        return None
    actions_list = plan.get_actions()
    if not actions_list:
        return None

    tools_row: List[Dict[str, str]] = []
    last_feedback = ""

    for act in actions_list:
        if act.action != "open_browser_search":
            continue
        query = (getattr(act, "query", "") or "").strip()
        url = web_browser.build_nav_url(query) if query else _normalize_site_url(query)
        use_calango_login = (
            re.search(r"calango\s*\.?\s*studio", query or url, re.I)
            and jarvis_credentials.get_calango_login()
            and bool(
                re.search(
                    r"\b(?:login|entra|loga|ger[ae]|cri[ae]|modo\s+studio|gerar\s+imagem)\b",
                    user_text,
                    re.I,
                )
            )
        )
        tool = "calango_studio_login" if use_calango_login else "browse_open"
        args = {"url": url, "image_prompt": ""}
        if use_calango_login:
            m_img = re.search(
                r"(?:ger[ae]|cri[ae]|faz)\s+(?:uma\s+)?(?:imagem|arte|post)\s+(?:de|com|sobre)?\s*(.+)",
                user_text,
                re.I,
            )
            if m_img:
                args["image_prompt"] = (m_img.group(1) or "").strip().rstrip(".,!?")[:200]

        await broadcast({"type": "tool_call", "tool": tool, "status": "running", "desc": _tool_desc(tool, args)})
        await broadcast({"type": "browser_preview", **web_browser.preview_from_url(url, query or url.split("/")[-1], "")})

        try:
            if use_calango_login:
                feedback = await web_browser.calango_login_and_studio(args.get("image_prompt", ""))
            else:
                feedback = await web_browser.open_url(url)
        except Exception as e:
            feedback = f"Erro ao abrir: {e}"

        last_feedback = str(feedback)
        await broadcast({"type": "tool_call", "tool": tool, "status": "done", "result": last_feedback[:200]})
        await _broadcast_web_preview(broadcast, tool, args, last_feedback)
        tools_row.append({"tool": tool, "result": last_feedback[:200]})
        await asyncio.sleep(0.35)

    if not tools_row:
        return None

    await _broadcast_browse_narration(broadcast, tools_row[-1]["tool"], last_feedback, (plan.speak or "")[:120])
    response = (plan.speak or "Sim senhor.").strip()
    response = await _append_continuity_hint(user_text, response, tools_row)
    return {"response": response, "tools_used": tools_row}


async def _try_canned_greeting(user_text: str) -> Optional[Dict[str, Any]]:
    """Saudações instantâneas — sem LLM (evita travar com API lenta)."""
    raw = (user_text or "").strip().lower()
    key = re.sub(r"[!?.]+$", "", raw).strip()
    key = re.sub(r"\s+", " ", key)
    if not key:
        return None
    if key in _CANNED:
        return {"response": _CANNED[key], "tools_used": []}
    # remove "jarvis," / vírgulas leves
    key2 = re.sub(r"\bjarvis\b", "", key).strip(" ,")
    key2 = re.sub(r"\s+", " ", key2)
    if key2 in _CANNED:
        return {"response": _CANNED[key2], "tools_used": []}
    if _is_pure_greeting(key) or _is_pure_greeting(key2):
        base = key2 or key
        if base in _CANNED:
            return {"response": _CANNED[base], "tools_used": []}
        return {"response": "Olá, senhor.", "tools_used": []}
    # Fuzzy: só cumprimentos curtos
    if len(key2) <= 28 and re.match(
        r"^(?:oi|ol[aá]|hey|e\s+a[ií]|tudo\s+bem|bom\s+dia|boa\s+tarde|boa\s+noite)"
        r"(?:\s+(?:senhor|jarvis|tudo\s+bem))?$",
        key2,
        re.I,
    ):
        if "tudo bem" in key2:
            return {
                "response": "Olá, senhor. Tudo operacional por aqui. Como posso ajudar?",
                "tools_used": [],
            }
        return {"response": "Olá, senhor.", "tools_used": []}
    return None


def _is_api_denied(err: BaseException) -> bool:
    msg = str(err).lower()
    return (
        "403" in msg
        or "429" in msg
        or "quota" in msg
        or "resource_exhausted" in msg
        or "permission-denied" in msg
        or "credits" in msg
        or "spending limit" in msg
        or "nenhum llm disponível" in msg
        or "nenhum llm configurado" in msg
    )


def _llm_unavailable_message(err: BaseException | None = None) -> str:
    msg = str(err or "").lower()
    if "ollama" in msg and ("offline" in msg or "servidor" in msg):
        return (
            "Senhor, a nuvem está sem cota e o Ollama local não respondeu. "
            "Abra o Ollama e aguarde o hermes3 carregar — ou recarregue créditos Gemini. "
            "Enquanto isso, abro apps, painel Google, clima e controlo o PC."
        )
    if "429" in msg or "quota" in msg or "resource_exhausted" in msg:
        return (
            "Senhor, a cota do Gemini esgotou e o fallback local também falhou. "
            "Ainda posso abrir apps, painel Google, clima e controlar o PC. "
            "Amanhã volta o chat na nuvem, ou inicie o Ollama para modo offline."
        )
    return (
        "Senhor, no momento não consigo acessar nenhum modelo de linguagem. "
        "Posso pesquisar no painel, abrir apps, clima, tradução e controlar o PC."
    )


def graceful_error_message(err: BaseException | None = None) -> str:
    """Falha de LLM/pipeline vira fala curta pt-BR — nunca stack trace nem silêncio."""
    if err is not None and _is_api_denied(err):
        return _llm_unavailable_message(err)
    if isinstance(err, (asyncio.TimeoutError, TimeoutError)):
        return (
            "Senhor, a resposta demorou além do aceitável e cancelei a chamada. "
            "Pode repetir? Hora, status, apps e painel seguem operacionais."
        )
    return (
        "Senhor, tive uma falha interna momentânea ao processar isso. "
        "Já estou operacional de novo — pode repetir o pedido."
    )


def _llm_call_timeout() -> float:
    try:
        return max(15.0, float(os.getenv("JARVIS_LLM_TIMEOUT_S", "60") or "60"))
    except ValueError:
        return 60.0


async def _try_live_memory_first(user_text: str) -> Optional[Dict[str, Any]]:
    raw = (user_text or "").strip()
    if not raw:
        return None
    if not jarvis_live._MEMORY_RECALL_INTENT_RE.search(raw):
        return None
    if (
        _needs_browser_action(raw)
        or _COWATCH_RE.search(raw)
        or _SCREEN_ASSIST_RE.search(raw)
        or _YOUTUBE_OPEN_RE.search(raw)
        or _STUDY_DEEP_RE.search(raw)
        or re.search(r"\b(?:abre|abra|abrir|acesse|pesquis[ae]|busc[ae]|naveg)\b", raw, re.I)
    ):
        return None
    ans = await jarvis_live.memory_first_answer(raw)
    if ans:
        return {"response": ans, "tools_used": [{"tool": "search_obsidian", "result": "memoria"}]}
    return None


async def _try_live_cowatch(user_text: str, broadcast: Broadcast) -> Optional[Dict[str, Any]]:
    if not _COWATCH_RE.search(user_text or ""):
        return None
    return await jarvis_live.cowatch_with_user(
        user_text,
        broadcast,
        open_url_fn=None,
        broadcast_preview_fn=_broadcast_web_preview,
    )


async def _try_calango_studio_live(user_text: str, broadcast: Broadcast) -> Optional[Dict[str, Any]]:
    raw = (user_text or "").strip()
    if not raw or not _CALANGO_LIVE_RE.search(raw):
        return None
    if _COWATCH_RE.search(raw):
        return None
    if not re.search(
        r"\b(?:abre|abra|acesse|entra|login|mex[ae]|ger[ae]|cri[ae]|usa|naveg|ferrament)\b",
        raw,
        re.I,
    ):
        return None
    # "abre calango no painel" sem login/gerar → browse_open (nao calango_studio_login)
    if re.search(r"\b(?:abre|abra|acesse)\b", raw, re.I) and not re.search(
        r"\b(?:login|entra|loga|ger[ae]|cri[ae]|mex[ae]|ferrament|modo\s+studio|gerar)\b",
        raw,
        re.I,
    ):
        return None
    return await jarvis_live.calango_studio_session(
        raw,
        broadcast,
        broadcast_preview_fn=_broadcast_web_preview,
    )


async def _try_live_screen_assist(user_text: str, broadcast: Broadcast) -> Optional[Dict[str, Any]]:
    raw = user_text or ""
    # Não roubar opinião de TEMA (ex.: "o que acha de IA no design") — isso é pesquisa.
    if jarvis_live._wants_design_review(raw) or _SCREEN_ASSIST_RE.search(raw):
        return await jarvis_live.screen_assist(
            raw,
            broadcast,
            open_app_fn=lambda a: _execute_tool("open_app", a),
        )
    return None


_DATETIME_FAST_RE = re.compile(
    r"que\s+horas|qual\s+(?:a\s+)?hora|hor[áa]rio(?:\s+atual|\s+agora)?|"
    r"que\s+dia|data\s+de\s+hoje",
    re.I,
)


async def _try_fast_datetime(
    user_text: str,
    broadcast: Broadcast,
) -> Optional[Dict[str, Any]]:
    """Hora/data/dia da semana — offline pt-BR, nunca cai no LLM inventando horário."""
    from jarvis_fast_paths import try_datetime_info

    return await try_datetime_info(user_text, broadcast, _broadcast_tool)


_HUMOR_FAST_RE = re.compile(
    r"(?:kk{2,}|rsrs|hehe|huehue|pegadinha|brincadeira|zoando|troll)",
    re.I,
)

_SPEAK_VERBATIM_BLOCKED = re.compile(
    r"^(?:sobre|mais|do\s|da\s|de\s|como|quando|onde|qual|quem|"
    r"a\s+data|as?\s+horas?|o\s+dia|o\s+status|um\s+cumprimento|o\s+seu\s+nome|"
    r"not[ií]cia|pesquis|busca|explica|conta\s+sobre)\b"
    r"|(?:data|horas?|dia)\s+(?:de\s+)?hoje",
    re.I,
)

_SPEAK_VERBATIM_CMD = re.compile(
    r"^(?:"
    r"(?:quero\s+que\s+(?:você|voce|vc)\s+)?"
    r"(?:pode\s+)?"
    r"(?:fal(?:e|a|ar)|repit(?:e|a|ir)|retir(?:e|o|ir)|repetir|"
    r"diz(?:a)?|diga|leia(?:\s+em\s+voz\s+alta)?|cite|recit(?:e|a|ar))"
    r"(?:\s+(?:exatamente|literalmente|assim|isso|o\s+seguinte|pra\s+mim))?"
    r")"
    r"[:\s,\"'-]+(.+)$",
    re.I | re.S,
)

_SPEAK_VERBATIM_QUOTED = re.compile(
    r"^(?:fal(?:e|a|ar)|repit(?:e|a|ir)|retir(?:e|o|ir)|diz(?:a)?|diga|leia|cite|recit(?:e|a|ar))\s+"
    r'''["'“«](.+)["'”»]\s*$''',
    re.I | re.S,
)

_SPEAK_VERBATIM_ME = re.compile(
    r"^me\s+(?:fal(?:e|a|ar)|diz(?:a)?|repit(?:e|a|ir)|retir(?:e|o|ir))\s+(.+)$",
    re.I | re.S,
)


def _strip_wake_prefix(text: str) -> str:
    return re.sub(
        r"^(?:jarvis|ok\s+jarvis|ei\s+jarvis)[,\s:]+",
        "",
        (text or "").strip(),
        flags=re.I,
    ).strip()


def _extract_speak_verbatim_text(text: str) -> Optional[str]:
    """Extrai frase para TTS literal ('fala X', 'repita X', 'retiro X'…)."""
    raw = (text or "").strip()
    if not raw:
        return None
    normalized = _strip_wake_prefix(raw)
    if not normalized:
        return None

    for pat in (_SPEAK_VERBATIM_QUOTED, _SPEAK_VERBATIM_CMD, _SPEAK_VERBATIM_ME):
        m = pat.match(normalized)
        if not m:
            continue
        phrase = (m.group(1) or "").strip().strip("\"'""«»")
        if len(phrase) < 4 or _SPEAK_VERBATIM_BLOCKED.match(phrase):
            continue
        return phrase[:500]
    return None


async def _try_fast_speak_verbatim(
    user_text: str,
    broadcast: Broadcast,
) -> Optional[Dict[str, Any]]:
    """Fala/repete texto exato do Gustavo — sem censura, sem parafrasear."""
    phrase = _extract_speak_verbatim_text(user_text)
    if not phrase:
        return None
    playful = bool(
        re.search(r"\b(?:kk|rsrs|hehe|carlho|porra|zoeira|brincando)\b", phrase, re.I)
        or jarvis_memory.detect_tone(user_text) in ("humor", "pegadinha")
    )
    mood = "playful" if playful else "calm"
    await broadcast({"type": "tone", "tone": "neutro", "mood": mood})
    return {
        "response": phrase,
        "tools_used": [],
        "tone": "neutro",
        "mood": mood,
        "verbatim": True,
    }


async def _try_fast_humor(user_text: str, broadcast: Broadcast) -> Optional[Dict[str, Any]]:
    """Humor/pegadinha — resposta Thomas INSTANTÂNEA (sem LLM = sem travar)."""
    raw = (user_text or "").strip()
    if not raw or not _HUMOR_FAST_RE.search(raw):
        return None
    tone = jarvis_memory.detect_tone(raw)
    if tone not in ("humor", "pegadinha"):
        tone = "pegadinha" if re.search(r"pegadinha|troll|zoando", raw, re.I) else "humor"
    try:
        await broadcast({"type": "tone", "tone": tone, "mood": jarvis_memory.emotion_for_orb(tone)})
    except Exception:
        pass
    # Respostas prontas — confiáveis mesmo com Gemini/xAI sem cota
    if tone == "pegadinha":
        base = "Ha — bem tentado, senhor. A pegadinha foi elegante; quase caí."
    else:
        base = "Ha — gosto do seu humor, senhor. Sigo calmo e à disposição."
    return {"response": base[:320], "tools_used": []}


async def _try_fast_skills(
    user_text: str,
    broadcast: Broadcast,
) -> Optional[Dict[str, Any]]:
    """Fast-paths: clipboard, pastas, janelas, screenshot, nota rápida, clima, tradução, atalhos."""
    raw = (user_text or "").strip()
    if not raw:
        return None

    tools_row: List[Dict[str, str]] = []

    if _SCREEN_ASSIST_RE.search(raw) or _COWATCH_RE.search(raw) or _STUDY_DEEP_RE.search(raw):
        return None

    dt = await _try_fast_datetime(raw, broadcast)
    if dt:
        return dt

    m_note = _QUICK_NOTE_RE.search(raw)
    if m_note:
        content = (m_note.group(1) or m_note.group(2) or "").strip().rstrip(".,!?")
        if len(content) >= 3:
            title = f"Lembrete {content[:40]}"
            fb = await _broadcast_tool(
                broadcast, "save_to_obsidian", {"title": title, "content": content, "tags": "lembrete,rapido"}
            )
            tools_row.append({"tool": "save_to_obsidian", "result": str(fb)[:200]})
            return {
                "response": f"Anotado no Obsidian, senhor: {content[:120]}.",
                "tools_used": tools_row,
            }

    m_weather = _WEATHER_RE.search(raw)
    if m_weather:
        city = (m_weather.group(1) or "Caçador SC").strip().rstrip(".,!?")
        if len(city) < 2:
            city = "Caçador SC"
        q = f"quando vai chover em {city}"
        google_url = offline_tools.open_google_in_browser(q)
        tools_row.append({"tool": "browse_open", "result": str(google_url)[:220]})
        spoken = await offline_tools.forecast_city(city)
        return {"response": spoken, "tools_used": tools_row}

    m_tr = _TRANSLATE_RE.search(raw)
    if m_tr:
        lang = (m_tr.group(1) or "inglês").strip()
        text = (m_tr.group(2) or "").strip().rstrip(".,!?")
        if len(text) >= 2:
            fb = await _broadcast_tool(
                broadcast, "translate_text", {"text": text, "target_language": lang}
            )
            tools_row.append({"tool": "translate_text", "result": str(fb)[:200]})
            return {"response": _voice_ready_answer(str(fb), 320), "tools_used": tools_row}

    m_copy = _CLIPBOARD_COPY_RE.search(raw)
    if m_copy:
        text_m = re.search(
            r"(?:copi[ae]|coloc[ae])\s+(?:para\s+(?:o\s+)?(?:clipboard|área de transferência|area de transferencia)\s*)?[:\-]?\s*(.+)"
            r"|[\"'](.+?)[\"']",
            raw,
            re.I,
        )
        text = ""
        if text_m:
            text = (text_m.group(1) or text_m.group(2) or "").strip()
        if len(text) >= 1:
            fb = await _broadcast_tool(broadcast, "clipboard_copy", {"text": text})
            tools_row.append({"tool": "clipboard_copy", "result": str(fb)[:200]})
            return {"response": "Copiado para o clipboard, senhor.", "tools_used": tools_row}

    if _CLIPBOARD_READ_RE.search(raw) and not _CLIPBOARD_COPY_RE.search(raw):
        fb = await _broadcast_tool(broadcast, "clipboard_read", {})
        tools_row.append({"tool": "clipboard_read", "result": str(fb)[:200]})
        return {"response": _voice_ready_answer(str(fb), 400), "tools_used": tools_row}

    m_folder = _OPEN_FOLDER_RE.search(raw)
    if m_folder and not _needs_browser_action(raw) and not re.search(
        r"\.(?:com|studio|org|br|net)\b|https?://|\bno\s+painel\b", raw, re.I
    ):
        folder = m_folder.group(1).strip().lower()
        fb = await _broadcast_tool(broadcast, "open_folder", {"folder": folder})
        tools_row.append({"tool": "open_folder", "result": str(fb)[:200]})
        labels = {
            "downloads": "Downloads", "download": "Downloads",
            "desktop": "Desktop", "documentos": "Documentos",
            "jarvis": "JARVIS", "obsidian": "Obsidian", "calango": "Calango",
        }
        label = labels.get(folder, folder.title())
        return {
            "response": f"Sim, senhor. Pasta {label} aberta." if "Erro" not in str(fb) else str(fb)[:200],
            "tools_used": tools_row,
        }

    if _LIST_WINDOWS_RE.search(raw) and not _SHORTCUT_RE.search(raw):
        fb = await _broadcast_tool(broadcast, "list_windows", {"max_items": 18})
        tools_row.append({"tool": "list_windows", "result": str(fb)[:200]})
        spoken = local_vision.narrate_from_visible_text(raw, str(fb), mode="assist")
        return {"response": spoken, "tools_used": tools_row}

    if _SCREENSHOT_SAVE_RE.search(raw):
        fb = await _broadcast_tool(broadcast, "save_screenshot", {"title": "Captura JARVIS"})
        tools_row.append({"tool": "save_screenshot", "result": str(fb)[:200]})
        return {
            "response": "Screenshot salvo no Obsidian, senhor." if "Erro" not in str(fb) else str(fb)[:200],
            "tools_used": tools_row,
        }

    if _SHORTCUT_RE.search(raw):
        low = raw.lower()
        if re.search(r"\b(?:mostra|mostre|exibe)\s+(?:o\s+)?desktop\b|win\+d", low):
            keys, label = "win+d", "Desktop exibido"
        elif re.search(r"\b(?:alterna|alternar|troca)\s+(?:de\s+)?janela\b|alt\+tab", low):
            keys, label = "alt+tab", "Alternando janela"
        else:
            keys, label = "printscreen", "Captura de tela"
        fb = await _broadcast_tool(broadcast, "desktop_press", {"keys": keys})
        tools_row.append({"tool": "desktop_press", "result": str(fb)[:200]})
        return {"response": f"Sim, senhor. {label}.", "tools_used": tools_row}

    return None


async def _try_orchestration_report(user_text: str) -> Optional[Dict[str, Any]]:
    """Auditoria: o que funciona, o que não funciona e por quê."""
    from jarvis_orchestration_report import (
        build_report_async,
        save_to_obsidian,
        wants_orchestration_report,
    )

    if not wants_orchestration_report(user_text):
        return None
    report = await build_report_async()
    vault_path = ""
    try:
        vault_path = save_to_obsidian(report)
    except Exception as e:
        print(f"[orchestration] vault save: {e}")
    return {
        "response": report.get("spoken_summary") or "Auditoria concluída, senhor.",
        "tools_used": [],
        "orchestration": report,
        "vault_path": vault_path,
    }


def _orchestrator_enabled() -> bool:
    return os.getenv("JARVIS_AGENT_ORCHESTRATOR", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _try_orchestrator_command(user_text: str) -> Optional[Dict[str, Any]]:
    """Comandos /agentes /ativar /quem /geral /sugerir — sem LLM, sempre."""
    if not _orchestrator_enabled():
        return None
    try:
        from agent_orchestrator import get_orchestrator

        orch = get_orchestrator()
        cmd_reply = orch.handle_command(user_text)
        if not cmd_reply:
            return None
        st = orch.status_dict()
        return {
            "response": cmd_reply,
            "tools_used": [],
            "active_agent": st.get("active_agent_id"),
            "orchestrator": st,
        }
    except Exception as e:
        print(f"[orchestrator] comando: {e}")
        return None


async def _try_capabilities_fast(user_text: str) -> Optional[Dict[str, Any]]:
    if not _CAPABILITIES_RE.search((user_text or "").strip()):
        return None
    _refresh_capabilities_meta()
    return {
        "response": JARVIS_CAPABILITIES.get("spoken") or JARVIS_CAPABILITIES_SPOKEN,
        "tools_used": [],
        "capabilities": JARVIS_CAPABILITIES,
    }


async def _try_live_study(user_text: str, broadcast: Broadcast) -> Optional[Dict[str, Any]]:
    m = _STUDY_DEEP_RE.search(user_text or "")
    if not m:
        return None
    topic = (m.group(1) or "").strip().rstrip(".,!?")[:120]
    if len(topic) < 3:
        return None
    return await jarvis_live.study_and_remember(
        topic,
        broadcast,
        lambda a: _execute_tool("study_topic", a),
    )


async def _safe_await(label: str, coro, timeout: float = 55.0) -> Any:
    """Executa path sem derrubar o turno — timeout ou erro → None."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        print(f"[agent] {label}: timeout {timeout}s")
        return None
    except asyncio.CancelledError:
        # wait_for cancela a task interna; não propaga cancel pro turno inteiro
        print(f"[agent] {label}: cancelled")
        return None
    except Exception as e:
        print(f"[agent] {label}: {type(e).__name__}: {e}")
        return None


async def run_agent_turn(
    user_text: str,
    broadcast: Broadcast,
    *,
    browser_active: bool = False,
    prefer_panel: bool = False,
) -> Dict[str, Any]:
    """
    Entrada segura: nunca propaga exceção ao HTTP.
    Timeouts e fallbacks ficam em _run_agent_turn_impl + paths.
    """
    try:
        result = await asyncio.wait_for(
            _run_agent_turn_impl(
                user_text,
                broadcast,
                browser_active=browser_active,
                prefer_panel=prefer_panel,
            ),
            timeout=float(os.getenv("JARVIS_TURN_TIMEOUT") or "88"),
        )
        if not isinstance(result, dict):
            return {
                "response": "Sim, senhor. Sistemas online — pode repetir o pedido?",
                "tools_used": [],
            }
        if result.get("requires_confirmation"):
            return result
        resp = (result.get("response") or "").strip()
        if not resp:
            result["response"] = "Sim, senhor. Estou online e pronto para o próximo comando."
        return result
    except (asyncio.TimeoutError, asyncio.CancelledError):
        print("[agent] turno excedeu JARVIS_TURN_TIMEOUT / cancelled")
        try:
            await broadcast({"type": "state", "state": "idle"})
        except Exception:
            pass
        return {
            "response": (
                "Senhor, isso está demorando além do esperado. "
                "Sigo online — peça de novo em partes menores ou repita o comando."
            ),
            "tools_used": [],
            "soft_timeout": True,
        }
    except Exception as e:
        print(f"[agent] turno falhou: {type(e).__name__}: {e}")
        try:
            await broadcast({"type": "state", "state": "idle"})
        except Exception:
            pass
        return {
            "response": (
                "Senhor, tive um contratempo interno, mas não saí do ar. "
                "Pode repetir o pedido? Estou pronto."
            ),
            "tools_used": [],
            "soft_error": str(e)[:180],
        }


async def _run_agent_turn_impl(
    user_text: str,
    broadcast: Broadcast,
    *,
    browser_active: bool = False,
    prefer_panel: bool = False,
) -> Dict[str, Any]:
    """
    Um turno completo do agente: pensa → executa tools quantas vezes precisar → responde.
    Se encontrar tool de risco, salva o estado e retorna pedido de confirmação.
    Após tarefas executadas, dispara auto-reflexão (arquivado no Obsidian).
    """
    # Saudações PRIMEIRO (antes de humor/verbatim) — evita 8–12s de atraso em "oi"
    canned_early = await _try_canned_greeting(user_text)
    if canned_early:
        return canned_early

    # Conversa pura (saudação, agradecimento, despedida, concordância) — resposta imediata
    # sem passar por todos os fast paths pesados
    if _is_pure_chat(user_text) and not _needs_browser_action(user_text):
        fast = await _safe_await(
            "chat_fast", _try_fast_conversation(user_text), 10.0
        )
        if fast:
            greet_key = re.sub(r"[!?.]+$", "", (user_text or "").strip().lower()).strip()
            if _is_pure_greeting(greet_key):
                return {"response": fast, "tools_used": []}
            enriched = await _safe_await(
                "enrich", _enrich_response_with_hint(user_text, fast, []), 8.0
            )
            return {"response": enriched or fast, "tools_used": []}

    dt_early = await _safe_await(
        "datetime", _try_fast_datetime(user_text, broadcast), 4.0
    )
    if dt_early:
        return dt_early

    speak_verbatim = await _safe_await(
        "speak_verbatim", _try_fast_speak_verbatim(user_text, broadcast), 8.0
    )
    if speak_verbatim:
        return speak_verbatim

    humor_fast = await _safe_await(
        "humor", _try_fast_humor(user_text, broadcast), 12.0
    )
    if humor_fast:
        return humor_fast

    try:
        from jarvis_skills_registry import handle_skills_command

        skills_reply = handle_skills_command(user_text)
        if skills_reply:
            return {"response": skills_reply, "tools_used": []}
    except Exception:
        pass

    orch_cmd = _try_orchestrator_command(user_text)
    if orch_cmd:
        return orch_cmd

    capabilities_early = await _safe_await(
        "cap_early", _try_capabilities_fast(user_text), 8.0
    )
    if capabilities_early:
        return capabilities_early

    # Pesquisa / relatório / estudo — caminho dedicado (antes de cowatch e chat)
    research_report = await _safe_await(
        "research_report",
        _try_research_or_report(user_text, broadcast),
        75.0,
    )
    if research_report:
        return research_report

    cowatch_early = await _safe_await(
        "cowatch_early", _try_live_cowatch(user_text, broadcast), 70.0
    )
    if cowatch_early:
        return cowatch_early

    if _browse_allowed_for_turn(user_text) and re.search(
        r"\bgoogle\b", user_text, re.I
    ) and re.search(r"\b(?:youtube|vídeo|video)\b", user_text, re.I):
        compound_web = await _safe_await(
            "compound_web", _try_fast_site_open(user_text, broadcast), 40.0
        )
        if compound_web:
            if _COWATCH_RE.search(user_text) or re.search(
                r"\b(?:assista|veja|ver|resumo|resuma|comigo|relat[oó]rio)\b",
                user_text,
                re.I,
            ):
                await asyncio.sleep(0.35)
                cw = await _safe_await(
                    "cowatch_compound",
                    jarvis_live.cowatch_with_user(
                        user_text,
                        broadcast,
                        open_url_fn=None,
                        broadcast_preview_fn=_broadcast_web_preview,
                    ),
                    70.0,
                )
                if cw:
                    tools = (compound_web.get("tools_used") or []) + (cw.get("tools_used") or [])
                    resp = (
                        f"{compound_web.get('response', '').strip()} "
                        f"{cw.get('response', '').strip()}"
                    ).strip()
                    out = dict(cw)
                    out["response"] = resp[:420]
                    out["tools_used"] = tools
                    return out
            return compound_web

    try:
        await asyncio.wait_for(_prepare_turn_context(user_text, broadcast), timeout=8.0)
    except Exception as e:
        print(f"[agent] prepare context: {e}")

    voice_change = await _safe_await(
        "voice_change", _try_fast_voice_change(user_text, broadcast), 12.0
    )
    if voice_change:
        return voice_change

    dt_early = await _safe_await(
        "datetime", _try_fast_datetime(user_text, broadcast), 8.0
    )
    if dt_early:
        return dt_early

    try:
        from jarvis_fast_paths import (
            try_jarvis_status,
            try_pc_status,
            try_security_audit,
            try_vault_ops,
        )

        self_status = await _safe_await(
            "jarvis_status", try_jarvis_status(user_text), 10.0
        )
        if self_status:
            return self_status

        pc_status = await _safe_await(
            "pc_status", try_pc_status(user_text, broadcast, _broadcast_tool), 15.0
        )
        if pc_status:
            return pc_status

        from claude_brain import try_claude_task

        claude_task = await _safe_await(
            "claude_brain", try_claude_task(user_text, broadcast), 10.0
        )
        if claude_task:
            return claude_task

        security_fast = await _safe_await(
            "security", try_security_audit(user_text, broadcast, _broadcast_tool), 25.0
        )
        if security_fast:
            return security_fast

        vault_fast = await _safe_await(
            "vault", try_vault_ops(user_text, broadcast, _broadcast_tool), 25.0
        )
        if vault_fast:
            return vault_fast
    except Exception as e:
        print(f"[agent] fast_paths: {e}")

    if _orchestrator_enabled():
        try:
            from agent_orchestrator import get_orchestrator

            orch = get_orchestrator()
            primary, _, reasons = orch.select_agent(user_text)
            if primary:
                await broadcast(
                    {
                        "type": "agent_suggestion",
                        "id": primary.id,
                        "name": primary.name,
                        "reason": reasons[0] if reasons else primary.squad,
                    }
                )
            adv = await orch.advisory_reply_async(user_text)
            if adv and (
                orch.wants_comparison(user_text)
                or orch.wants_explicit_advisory(user_text)
            ):
                ranked = orch.rank_agents(user_text, top=1)
                st = orch.status_dict()
                st["suggested_agent"] = ranked[0][1].id if ranked else None
                st["advisory_mode"] = (
                    "comparison" if orch.wants_comparison(user_text) else "suggestion"
                )
                return {
                    "response": adv,
                    "tools_used": [],
                    "orchestrator": st,
                    "agent_suggestion": st.get("suggested_agent"),
                }
        except Exception as e:
            print(f"[orchestrator] comando: {e}")

    capabilities = await _safe_await(
        "capabilities", _try_capabilities_fast(user_text), 10.0
    )
    if capabilities:
        return capabilities

    screen_help = await _safe_await(
        "screen", _try_live_screen_assist(user_text, broadcast), 55.0
    )
    if screen_help:
        return screen_help

    orchestration = await _safe_await(
        "orch_report", _try_orchestration_report(user_text), 20.0
    )
    if orchestration:
        return orchestration

    try:
        compound_plan = resolve_fast_action(user_text)
    except Exception:
        compound_plan = None
    if compound_plan and len(compound_plan.get_actions()) > 1:
        compound_site = await _safe_await(
            "compound_site", _try_fast_site_open(user_text, broadcast), 40.0
        )
        if compound_site:
            return compound_site

    multi = await _safe_await(
        "multi",
        _try_multi_intent(user_text, broadcast, browser_active=browser_active),
        50.0,
    )
    if multi:
        return multi

    site_early = await _safe_await(
        "site", _try_fast_site_open(user_text, broadcast), 40.0
    )
    if site_early:
        return site_early

    youtube_smart = await _safe_await(
        "youtube", _try_youtube_smart(user_text, broadcast), 55.0
    )
    if youtube_smart:
        return youtube_smart

    close_panel = await _safe_await(
        "close_panel",
        _try_fast_close_panel(user_text, broadcast, browser_active=browser_active),
        12.0,
    )
    if close_panel:
        return close_panel

    open_app_fast = await _safe_await(
        "open_app", _try_fast_open_app(user_text, broadcast), 20.0
    )
    if open_app_fast:
        return open_app_fast

    pc_action = await _safe_await(
        "pc", _try_fast_pc_actions(user_text, broadcast), 25.0
    )
    if pc_action:
        return pc_action

    skills = await _safe_await(
        "skills", _try_fast_skills(user_text, broadcast), 30.0
    )
    if skills:
        return skills

    canned = await _safe_await("canned", _try_canned_greeting(user_text), 8.0)
    if canned:
        return canned

    # Opinião inteligente: Google + análise (antes de conversa rasa)
    opinion_smart = await _safe_await(
        "opinion", _try_smart_opinion_research(user_text, broadcast), 70.0
    )
    if opinion_smart:
        return opinion_smart

    web_fast = await _safe_await(
        "web_search",
        _try_fast_web_search(
            user_text,
            broadcast,
            browser_active=browser_active,
            prefer_panel=prefer_panel,
        ),
        50.0,
    )
    if web_fast:
        return web_fast

    auto_research = await _safe_await(
        "auto_research", _try_auto_research(user_text, broadcast), 50.0
    )
    if auto_research:
        return auto_research

    memory_hit = await _safe_await("memory", _try_memory_recall(user_text), 15.0)
    if memory_hit:
        return {"response": memory_hit, "tools_used": []}

    live_mem = await _safe_await("live_mem", _try_live_memory_first(user_text), 15.0)
    if live_mem:
        return live_mem

    study_live = await _safe_await(
        "study", _try_live_study(user_text, broadcast), 50.0
    )
    if study_live:
        return study_live

    calango_live = await _safe_await(
        "calango", _try_calango_studio_live(user_text, broadcast), 55.0
    )
    if calango_live:
        return calango_live

    cowatch = await _safe_await(
        "cowatch", _try_live_cowatch(user_text, broadcast), 70.0
    )
    if cowatch:
        return cowatch

    browse_deep = await _safe_await(
        "browse_deep", _try_browse_deep_navigate(user_text, broadcast), 50.0
    )
    if browse_deep:
        return browse_deep

    hybrid = await _safe_await(
        "hybrid",
        _try_hybrid_search(
            user_text,
            broadcast,
            browser_active=browser_active,
            prefer_panel=prefer_panel,
        ),
        50.0,
    )
    if hybrid:
        return hybrid

    browser_nav = await _safe_await(
        "browser_nav",
        _try_fast_browser_navigate(
            user_text, broadcast, browser_active=browser_active
        ),
        45.0,
    )
    if browser_nav:
        return browser_nav

    site = await _safe_await(
        "site2", _try_fast_site_open(user_text, broadcast), 40.0
    )
    if site:
        return site

    youtube_fast = await _safe_await(
        "yt_fast", _try_fast_youtube(user_text, broadcast), 50.0
    )
    if youtube_fast:
        return youtube_fast

    if not _needs_tools(user_text):
        fast = await _safe_await(
            "chat_fast2", _try_fast_conversation(user_text), 15.0
        )
        if fast:
            greet_key = re.sub(r"[!?.]+$", "", (user_text or "").strip().lower()).strip()
            if _is_pure_greeting(greet_key):
                return {"response": fast, "tools_used": []}
            enriched = await _safe_await(
                "enrich2", _enrich_response_with_hint(user_text, fast, []), 12.0
            )
            return {"response": enriched or fast, "tools_used": []}

    client = get_client()
    try:
        messages = _build_messages(user_text)
    except Exception as e:
        print(f"[agent] build_messages: {e}")
        messages = [
            {
                "role": "system",
                "content": "Você é J.A.R.V.I.S. Responda em pt-BR, breve e útil.",
            },
            {"role": "user", "content": (user_text or "")[:800]},
        ]
    agent_model = get_smart_model() if _is_exploration_task(user_text) else _pick_agent_model(user_text)
    result = await _agent_loop(client, messages, broadcast, tools_used=[], model=agent_model)
    tools = result.get("tools_used") or []

    researched = await _maybe_auto_research_after_response(user_text, result, broadcast)
    if researched:
        result = researched
        tools = result.get("tools_used") or []

    if result.get("response"):
        if tools:
            result["response"] = await _append_continuity_hint(
                user_text, result["response"], tools
            )
        else:
            result["response"] = await _enrich_response_with_hint(
                user_text, result["response"], tools
            )
    if result.get("response") and len(tools) >= 2:
        asyncio.create_task(_reflect(user_text, tools, result["response"]))

    tone = jarvis_memory.detect_tone(user_text)
    result["tone"] = tone
    result["mood"] = jarvis_memory.emotion_for_orb(tone)
    await broadcast({"type": "tone", "tone": tone, "mood": result["mood"]})

    return result


async def _reflect(user_text: str, tools_used: List[Dict], response: str) -> None:
    """Auto-reflexão pós-tarefa: o que fez, o que funcionou, o que melhorar → Obsidian."""
    try:
        client = get_client()
        resumo = "; ".join(f"{t['tool']}: {str(t.get('result', ''))[:80]}" for t in tools_used[:8])
        resp = await client.chat.completions.create(
            model=get_model(),
            messages=[
                {"role": "system", "content": "Você é o módulo de auto-reflexão do JARVIS. Escreva em pt-BR, markdown, no máximo 6 linhas, concreto e útil para execuções futuras."},
                {"role": "user", "content": f"Tarefa pedida: {user_text}\nFerramentas executadas: {resumo}\nResposta final: {response}\n\nReflita: o que foi feito, o que funcionou, o que fazer melhor na próxima."},
            ],
            max_tokens=260,
            temperature=0.4,
        )
        text = (resp.choices[0].message.content or "").strip()
        if text:
            await asyncio.to_thread(
                obsidian_notes.save_reflection,
                f"Reflexão - {user_text[:50]}",
                text,
            )
    except Exception as e:
        print(f"[reflect] falhou: {e}")


async def continue_after_confirmation(broadcast: Broadcast) -> Dict[str, Any]:
    """Retoma o loop pausado: executa a tool de risco confirmada e continua até a resposta final."""
    pending = load_pending()
    if not pending or pending.get("kind") != "agent_tool":
        return {"error": "Nenhuma ação pendente para confirmar."}

    clear_pending()
    client = get_client()
    messages = pending["messages"]
    tc = pending["tool_call"]
    tools_used = pending.get("tools_used", [])

    args = json.loads(tc["arguments"] or "{}")
    feedback = await _execute_tool(tc["name"], args)
    tools_used.append({"tool": tc["name"], "result": feedback[:200]})
    await broadcast({"type": "tool_call", "tool": tc["name"], "status": "done", "result": feedback[:200]})

    messages.append({"role": "tool", "tool_call_id": tc["id"], "content": feedback[:1500]})
    return await _agent_loop(
        client, messages, broadcast, tools_used=tools_used, model=get_smart_model()
    )


async def _agent_loop(
    client,
    messages: List[Dict[str, Any]],
    broadcast: Broadcast,
    tools_used: List[Dict],
    model: Optional[str] = None,
) -> Dict[str, Any]:
    active_model = model or get_fast_model()
    depth = _response_depth(_turn_user_text(messages))
    if fast_mode_enabled():
        max_tokens_map = {"brief": 90, "standard": 220, "detailed": 420}
    else:
        max_tokens_map = {"brief": 140, "standard": 380, "detailed": 720}
    max_tokens = max_tokens_map.get(depth, 380)
    for _ in range(_max_agent_rounds()):
        try:
            resp = await asyncio.wait_for(
                client.chat.completions.create(
                    model=active_model,
                    messages=messages,
                    tools=TOOLS,
                    tool_choice="auto",
                    max_tokens=max_tokens,
                    temperature=0.38,
                ),
                timeout=_llm_call_timeout(),
            )
        except asyncio.TimeoutError as e:
            print(f"[agent_loop] LLM timeout ({_llm_call_timeout():.0f}s) em {active_model}")
            return {
                "response": graceful_error_message(e),
                "tools_used": tools_used,
                "degraded": True,
                "error": f"llm_timeout:{_llm_call_timeout():.0f}s",
            }
        except Exception as e:
            if _is_api_denied(e):
                return {
                    "response": _llm_unavailable_message(e),
                    "tools_used": tools_used,
                    "degraded": True,
                    "error": f"llm_denied:{type(e).__name__}",
                }
            print(f"[agent_loop] LLM falhou: {type(e).__name__}: {e}")
            return {
                "response": graceful_error_message(e),
                "tools_used": tools_used,
                "degraded": True,
                "error": f"llm_error:{type(e).__name__}",
            }
        msg = resp.choices[0].message

        if not msg.tool_calls:
            final = (msg.content or "").strip() or "Sim, senhor."
            return {"response": final, "tools_used": tools_used}

        # Serializa a mensagem do assistant com tool_calls (necessário pro histórico da API)
        assistant_msg = {
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ],
        }
        messages.append(assistant_msg)

        if (
            msg.content
            and msg.content.strip()
            and os.getenv("JARVIS_AGENT_THOUGHT_UI", "0").strip().lower() in ("1", "true", "yes", "on")
        ):
            await broadcast({"type": "agent_thought", "text": msg.content.strip()[:300]})

        for i, tc in enumerate(msg.tool_calls):
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            if name in RISKY_TOOLS:
                # Pausa o loop: tools restantes deste round são descartadas (modelo replaneja após confirmar)
                from datetime import datetime
                save_pending({
                    "kind": "agent_tool",
                    "messages": messages,
                    "tool_call": {"id": tc.id, "name": name, "arguments": tc.function.arguments},
                    "tools_used": tools_used,
                    "timestamp": datetime.now().isoformat(),  # expira em 5 min (auto-clear)
                })
                desc = _tool_desc(name, args)
                prompt = f"Senhor, isso executa {desc}. Confirma?"
                await broadcast({
                    "type": "action_requires_confirmation",
                    "action": {"action": name, **args},
                    "speak": prompt,
                    "confirmation_prompt": prompt,
                })
                return {"requires_confirmation": True, "confirmation_prompt": prompt, "action": {"action": name, **args}, "tools_used": tools_used}

            turn_text = _turn_user_text(messages)
            _browser_session_open = False
            try:
                _browser_session_open = (
                    web_browser.has_session() or web_browser.has_playwright_page()
                )
            except Exception:
                _browser_session_open = False
            if name in _OPENS_BROWSER and not _browse_allowed_for_turn(turn_text) and not _browser_session_open:
                feedback = (
                    "Navegação não solicitada neste turno — o Gustavo só conversou. "
                    "Responda em texto, sem abrir o Google nem o navegador."
                )
                tools_used.append({"tool": name, "result": feedback[:200]})
                await broadcast({"type": "tool_call", "tool": name, "status": "done", "result": feedback[:200]})
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": feedback[:500]})
                continue

            if name == "open_app":
                app_raw = (args.get("app_name") or "").strip().lower()
                if app_raw in _BROWSER_APP_NAMES:
                    if not _browse_allowed_for_turn(turn_text):
                        feedback = (
                            "Abrir Chrome/Edge externo bloqueado — o Gustavo só conversou. "
                            "Responda em texto sem abrir navegador."
                        )
                        tools_used.append({"tool": name, "result": feedback[:200]})
                        await broadcast({"type": "tool_call", "tool": name, "status": "done", "result": feedback[:200]})
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": feedback[:500]})
                        continue
                    name = "browse_open"
                    args = {"url": _normalize_site_url("google" if "google" in turn_text.lower() else "")}

            await broadcast({"type": "tool_call", "tool": name, "status": "running", "desc": _tool_desc(name, args)})
            if name in _WEB_PREVIEW_TOOLS:
                early = web_browser.preview_from_feedback(name, args, "")
                if early.get("url") or early.get("query"):
                    await broadcast({"type": "browser_preview", **early})
            images: List[str] = []
            try:
                result = await _execute_tool(name, args)
                if isinstance(result, tuple):
                    feedback, images = result
                else:
                    feedback = result
            except Exception as e:
                feedback = f"Erro ao executar {name}: {e}"
            tools_used.append({"tool": name, "result": feedback[:200]})
            await broadcast({"type": "tool_call", "tool": name, "status": "done", "result": feedback[:200]})
            await _broadcast_web_preview(broadcast, name, args, str(feedback))
            note = (msg.content or "").strip() if i == 0 else ""
            await _broadcast_browse_narration(broadcast, name, str(feedback), note)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": feedback[:1500]})

            if images:
                ocr_note = ""
                try:
                    ocr_text = await asyncio.to_thread(
                        local_vision.ocr_from_b64_jpeg, images[0]
                    )
                    if ocr_text and len(ocr_text) > 12:
                        ocr_note = f"\n\nTexto OCR extraído da tela:\n{ocr_text[:2200]}"
                        messages.append({
                            "role": "user",
                            "content": (
                                f"Captura de {name} — use este texto se a imagem não carregar:{ocr_note}"
                            ),
                        })
                except Exception:
                    pass
                # Visão multimodal (quando API disponível)
                content: List[Dict[str, Any]] = [
                    {
                        "type": "text",
                        "text": (
                            f"Imagens capturadas por {name} (analise e prossiga):{ocr_note}"
                        ),
                    }
                ]
                for b64 in images:
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"},
                    })
                messages.append({"role": "user", "content": content})

    return {"response": "Executei o que consegui, senhor, mas o plano ficou longo demais. Pode reformular?", "tools_used": tools_used}
