"""
Constantes e padrões regex do JARVIS Agent.
Extraído de jarvis_agent.py para reduzir complexidade.
"""

import re
from typing import FrozenSet

# Configurações do agente
MAX_ROUNDS = 6
RISKY_TOOLS = {"run_command", "close_app"}

# Triggers para detectar necessidade de tools
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
)

_BROWSER_TOOLS: FrozenSet[str] = frozenset({
    "browse_open", "browse_read", "browse_click", "browse_type", "browse_scroll",
    "browse_press_key", "browse_carousel_slide", "browse_back", "browse_site_search",
    "open_url", "open_browser_search", "web_search",
})

# Tools que ABREM um navegador visível na tela — gate rígido: só com pedido web explícito.
# web_search NÃO entra aqui (é busca de fato via API, não abre o Google).
# browse_read/click/scroll também não — apenas continuam uma página já aberta.
_OPENS_BROWSER: FrozenSet[str] = frozenset({"open_url", "open_browser_search", "browse_open"})

_BROWSER_APP_NAMES: FrozenSet[str] = frozenset({
    "chrome", "google chrome", "navegador", "edge", "msedge", "microsoft edge",
})

# Regex patterns
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
    r"^(?:oi|olá|ola|hey|bom dia|boa tarde|boa noite|e aí|e ai|fala|salve)\b"
    r"|^(?:tudo bem|tudo joia|beleza|e aí|e ai|fala aí)\b"
    r"|^como\s+(?:vai|está|esta|anda)\b"
    r"|^como\s+vai\s+(?:você|voce|vc)\b"
    r"|^tudo\s+(?:bem|joia|certo)\b"
    r"|\b(?:kk+|haha|rsrs|piada|brincando|zoeira|pegadinha|hehe)\b"
    r"|\b(?:obrigad|valeu|tchau|até logo|ate logo|falou|flw|brigad)\b"
    r"|^(?:sim|não|nao|ok|certo|entendi|legal|show|haha|blz|beleza|exato)\b"
    r"|^(?:e\s+aí|e\s+ai|fala|fala\s+aí|suave|firme)\b"
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

# Co-assistir / cowatch
_COWATCH_RE = re.compile(
    r"\b(?:co[- ]?assistir|cowatch|assiste\s+comigo|assistir\s+comigo)\b", re.I
)

_YOUTUBE_COWATCH = re.compile(
    r"\b(?:assista|assistir|veja|ver)\s+comigo\b.*\b(?:youtube|yt|vídeo|video|shorts)\b", re.I
)

_YOUTUBE_OPEN_RE = re.compile(r"\b(?:abre|abra|abrir)\s+(?:o\s+)?youtube\b", re.I)
_YOUTUBE_SEARCH_RE = re.compile(r"\b(?:pesquisa|pesquise|busca|busque)\s+(?:no\s+)?youtube\b", re.I)
_YOUTUBE_WATCH_RE = re.compile(r"\b(?:assista|veja|ver)\s+(?:o\s+)?(?:vídeo|video)\b", re.I)
_YOUTUBE_URL_RE = re.compile(r"https?://(?:www\.)?(?:youtube\.com|youtu\.be)/\S+", re.I)

# YouTube compound actions
_YOUTUBE_OPEN = re.compile(r"\b(?:abre|abra)\s+(?:o\s+)?youtube\b", re.I)
_YOUTUBE_SEARCH = re.compile(r"\b(?:pesquisa|pesquise|busca|busque)\s+(?:no\s+)?youtube\s+(.+)", re.I)
_YOUTUBE_PLAY = re.compile(r"\b(?:assista|veja|ver|play|toca)\s+(?:no\s+)?youtube\s+(.+)", re.I)

# Painel/browser
_BROWSER_NAV_QUERY = re.compile(
    r"\b(?:abre|abra|abrir|acesse|acessa|vá|va)\s+(?:o\s+)?(?:site|página|pagina|url|link)\b", re.I
)
_CLOSE_PANEL_RE = re.compile(r"\b(?:fecha|feche|fechar)\s+(?:o\s+)?(?:painel|navegador|chrome|google)\b", re.I)
_FULLSCREEN_RE = re.compile(r"\b(?:tela\s+cheia|fullscreen|maximiz[ae])\b", re.I)
_SKIP_AD_RE = re.compile(r"\b(?:pula|pule|pular)\s+(?:o\s+)?(?:anúncio|anuncio|ad|ads)\b", re.I)
_COPA_CASETV_RE = re.compile(r"\b(?:copa|casetv|casé)\b", re.I)
_RESEARCH_DOC_RE = re.compile(
    r"\b(?:pesquisa|estuda|analisa|faz\s+(?:um\s+)?relat[oó]rio)\s+(?:sobre|de)\b", re.I
)
_SEARCH_FAST = re.compile(r"^(?:pesquisa|pesquise|busca|busque|procure|procurar)\s+", re.I)

# Apps
_DOC_APPS = [
    (re.compile(r"\b(?:bloco\s+de\s+notas|notepad|editor\s+de\s+texto)\b", re.I), "notepad", "Bloco de Notas"),
    (re.compile(r"\b(?:calculadora|calc)\b", re.I), "calc", "Calculadora"),
    (re.compile(r"\b(?:explorador\s+de\s+arquivos|explorer|arquivos)\b", re.I), "explorer", "Explorador de Arquivos"),
    (re.compile(r"\b(?:word|microsoft\s+word)\b", re.I), "winword", "Word"),
    (re.compile(r"\b(?:excel|microsoft\s+excel)\b", re.I), "excel", "Excel"),
    (re.compile(r"\b(?:powerpoint|ppt)\b", re.I), "powerpnt", "PowerPoint"),
    (re.compile(r"\b(?:vscode|visual\s+studio\s+code|code)\b", re.I), "code", "VS Code"),
    (re.compile(r"\b(?:terminal|powershell|cmd|prompt\s+de\s+comando)\b", re.I), "terminal", "Terminal"),
    (re.compile(r"\b(?:paint|mspaint)\b", re.I), "mspaint", "Paint"),
    (re.compile(r"\b(?:spotify)\b", re.I), "spotify", "Spotify"),
    (re.compile(r"\b(?:discord)\b", re.I), "discord", "Discord"),
    (re.compile(r"\b(?:obsidian)\b", re.I), "obsidian", "Obsidian"),
    (re.compile(r"\b(?:notion)\b", re.I), "notion", "Notion"),
]

# Calango Studio
_CALANGO_LIVE_RE = re.compile(r"\b(?:calango|calango\.studio|modo\s+studio)\b", re.I)

# Screen assist
_SCREEN_ASSIST_RE = re.compile(
    r"\b(?:veja|olhe|olha)\s+(?:a\s+)?(?:minha\s+)?tela\b.*\b(?:agora|ao\s+vivo|tempo\s+real)\b", re.I
)

# Multi-part commands
_MULTI_AND_RE = re.compile(r"\s+(?:e|,)\s+(?:e\s+)?", re.I)

# WhatsApp patterns
_WHATSAPP_OPEN_RE = re.compile(r"\b(?:abre|abra|abrir)\s+(?:o\s+)?whatsapp\b.*\b(?:veja|ver|mensagem)\b", re.I)
_WHATSAPP_MSG_RE = re.compile(r"\bwhatsapp\b.*\b(?:mensagem|quem\s+mandou)\b", re.I)

def _turn_user_text(messages: list) -> str:
    """Extrai o texto do usuário da última mensagem."""
    for m in reversed(messages):
        if m.get("role") == "user":
            return str(m.get("content") or "")
    return ""

def _browse_allowed_for_turn(user_text: str) -> bool:
    """Verifica se o usuário pediu explicitamente para abrir/navegar no painel."""
    return _needs_browser_action(user_text) or _is_web_exploration(user_text)

def _needs_browser_action(user_text: str) -> bool:
    """Detecta pedido explícito de ABRIR/VER/NAVEGAR no painel."""
    for rx in _BROWSER_ACTION_RE:
        if rx.search(user_text):
            return True
    return False

def _is_web_exploration(user_text: str) -> bool:
    """Detecta pedido de exploração/web research explícito."""
    for trigger in _EXPLORATION_TRIGGERS:
        if trigger in user_text.lower():
            return True
    return False

def _is_conversational(user_text: str) -> bool:
    """Detecta conversa puramente social/saudação."""
    for rx in _CONVERSATIONAL_RE:
        if rx.search(user_text):
            return True
    return False

def _is_pure_chat(user_text: str) -> bool:
    """Detecta conversa pura (humor/social) — NÃO pesquisa Google."""
    return bool(_PURE_CHAT_RE.search(user_text))

def _is_info_tool_request(user_text: str) -> bool:
    """Detecta perguntas de info/sistema que precisam de tool."""
    return bool(_INFO_TOOL_RE.search(user_text))

def _is_capabilities_request(user_text: str) -> bool:
    """Detecta pedido de capacidades."""
    return bool(_CAPABILITIES_RE.search(user_text))

def _is_cowatch_request(user_text: str) -> bool:
    """Detecta pedido de co-assistir."""
    return bool(_COWATCH_RE.search(user_text))

def _is_youtube_cowatch(user_text: str) -> bool:
    """Detecta co-assistir YouTube específico."""
    return bool(_YOUTUBE_COWATCH.search(user_text))

def _is_browser_nav_query(user_text: str) -> bool:
    """Detecta navegação explícita."""
    return bool(_BROWSER_NAV_QUERY.search(user_text))

def _is_close_panel(user_text: str) -> bool:
    """Detecta fechar painel."""
    return bool(_CLOSE_PANEL_RE.search(user_text))

def _is_fullscreen(user_text: str) -> bool:
    """Detecta tela cheia."""
    return bool(_FULLSCREEN_RE.search(user_text))

def _is_skip_ad(user_text: str) -> bool:
    """Detecta pular anúncio."""
    return bool(_SKIP_AD_RE.search(user_text))

def _is_research_doc(user_text: str) -> bool:
    """Detecta pesquisa/documento."""
    return bool(_RESEARCH_DOC_RE.search(user_text))

def _is_search_fast(user_text: str) -> bool:
    """Detecta pesquisa rápida."""
    return bool(_SEARCH_FAST.match(user_text))

def _is_calango_live(user_text: str) -> bool:
    """Detecta Calango Studio."""
    return bool(_CALANGO_LIVE_RE.search(user_text))

def _is_screen_assist(user_text: str) -> bool:
    """Detecta assistência de tela."""
    return bool(_SCREEN_ASSIST_RE.search(user_text))

def _is_whatsapp_open(user_text: str) -> bool:
    """Detecta abrir WhatsApp e ver mensagens."""
    return bool(_WHATSAPP_OPEN_RE.search(user_text))

def _is_whatsapp_msg(user_text: str) -> bool:
    """Detecta WhatsApp mensagens."""
    return bool(_WHATSAPP_MSG_RE.search(user_text))