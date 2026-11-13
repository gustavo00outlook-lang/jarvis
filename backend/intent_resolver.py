"""Deterministic fast-path intent resolution for common PC actions.

Bypasses LLM when the user intent is unambiguous (e.g. 'abrir o Google').
"""

from __future__ import annotations

import re
from typing import Optional

from action_schema import ActionPlan, OpenBrowserSearchAction


_COMPOUND_GOOGLE = re.compile(
    r"abr(?:a|e|ir)\s+(?:o\s+)?google\s+(?:e\s+)?"
    r"(?:veja|ver|pesquis(?:e|ar|a|ei)|busc(?:a|ar|e)|procure|procurar|mostr(?:e|a))\s+(.+)",
    re.IGNORECASE,
)

_OPEN_GOOGLE = re.compile(
    r"(?:"
    r"abr(?:a|e|ir)\s+(?:o\s+)?google"
    r"|acesse?\s+(?:o\s+)?google"
    r"|acessar\s+(?:o\s+)?google"
    r"|open\s+google"
    r"|abre\s+(?:o\s+)?google"
    r"|google\s+(?:pra\s+mim|por\s+favor)"
    r")",
    re.IGNORECASE,
)

_OPEN_YOUTUBE = re.compile(
    r"(?:"
    r"abr(?:a|e|ir)\s+(?:o\s+)?youtube"
    r"|acesse?\s+(?:o\s+)?youtube"
    r"|vá?\s+(?:para|ao?)\s+(?:o\s+)?youtube"
    r")",
    re.IGNORECASE,
)

_COMPOUND_GOOGLE_YOUTUBE = re.compile(
    r"(?:"
    r"(?:acesse?|abr(?:a|e|ir))\s+(?:o\s+)?google\s+(?:e|depois|,?)\s*(?:abr(?:a|e|ir)|acesse?)?\s*(?:o\s+)?youtube"
    r"|(?:acesse?|abr(?:a|e|ir))\s+(?:o\s+)?youtube\s+(?:e|depois)\s+(?:abr(?:a|e|ir)|acesse?)\s+(?:o\s+)?google"
    r"|(?:abr(?:a|e|ir)|acesse?)\s+(?:o\s+)?google\s+e\s+(?:o\s+)?youtube"
    r"|\bgoogle\b.{0,35}\byoutube\b"
    r"|\byoutube\b.{0,35}\bgoogle\b"
    r")",
    re.IGNORECASE,
)

_SEARCH_GOOGLE = re.compile(
    r"(?:"
    r"(?:pesquis(?:e|ar|a|ei)|busc(?:a|ar|e)|procure|procurar|search(?:\s+for)?)"
    r"\s+(?:no\s+)?google\s+(?:sobre\s+|por\s+|de\s+|for\s+)?(.+)"
    r"|(?:pesquis(?:e|ar|a|ei)|busc(?:a|ar|e)|procure|procurar)"
    r"\s+(?:na\s+web|na\s+internet|online)\s+(?:sobre\s+|por\s+|de\s+)?(.+)"
    r")",
    re.IGNORECASE,
)

# "pesquisa sobre IA" / "busca copa do mundo" — abre Google no painel (sem exigir "google")
_SEARCH_PLAIN = re.compile(
    r"^(?:pesquis(?:e|ar|a|ei)|busc(?:a|ar|e)|procure|procurar)"
    r"\s+(?:sobre\s+|por\s+|de\s+)?(.+)$",
    re.IGNORECASE,
)

_SEARCH_PLAIN_SKIP = re.compile(
    r"\b(?:obsidian|memória|memoria|vault|arquivo|salv(?:e|ar)|ensin)\b",
    re.IGNORECASE,
)

_OPEN_SITE = re.compile(
    r"(?:"
    r"abr(?:a|e|ir)\s+(?:o\s+|a\s+)?(?:site\s+)?"
    r"|acesse?\s+(?:o\s+|a\s+)?(?:site\s+)?"
    r"|vá?\s+(?:para|ao?)\s+"
    r")"
    r"(https?://\S+|[\w][\w.\-]+\.[a-z]{2,})",
    re.IGNORECASE,
)

_OPEN_CALANGO = re.compile(
    r"calango\s*\.?\s*studio",
    re.IGNORECASE,
)

_OPEN_CALANGO_STUDIO = re.compile(
    r"(?:"
    r"modo\s+(?:studio|estúdio)"
    r"|(?:abrir?|acesse?)\s+(?:o\s+)?(?:modo\s+)?(?:studio|estúdio)"
    r"|studio\s+(?:da\s+)?calango"
    r"|calango\s+(?:modo\s+)?(?:studio|estúdio)"
    r")",
    re.IGNORECASE,
)

_OPEN_CALANGO_IMAGE = re.compile(
    r"(?:"
    r"(?:calango|studio).*(?:ger[ae]|cri[ae]|faz|monta).*(?:imagem|foto|arte|visual|banner)"
    r"|(?:ger[ae]|cri[ae]|faz).*(?:imagem|foto|arte).*(?:calango|studio)"
    r"|(?:abre|abra|acesse).*(?:calango|studio).*(?:imagem|gerar|gera)"
    r")",
    re.IGNORECASE,
)


def resolve_fast_action(text: str) -> Optional[ActionPlan]:
    """Return an ActionPlan for unambiguous intents, or None to defer to Grok."""
    raw = (text or "").strip()
    if not raw:
        return None

    normalized = re.sub(r"\s+", " ", raw)
    normalized = re.sub(
        r"^(?:jarvis|ok\s+jarvis|ei\s+jarvis)[,\s:]+",
        "",
        normalized,
        flags=re.IGNORECASE,
    ).strip()

    if _COMPOUND_GOOGLE_YOUTUBE.search(normalized):
        return ActionPlan(
            thought="Fast-path: Google depois YouTube em sequência.",
            actions=[
                OpenBrowserSearchAction(action="open_browser_search", query=""),
                OpenBrowserSearchAction(action="open_browser_search", query="https://www.youtube.com"),
            ],
            speak="Sim senhor. Abrindo o Google e em seguida o YouTube.",
            confidence=0.98,
        )

    if _OPEN_YOUTUBE.search(normalized) and not _SEARCH_GOOGLE.search(normalized):
        return ActionPlan(
            thought="Fast-path: abrir YouTube no painel.",
            actions=[OpenBrowserSearchAction(action="open_browser_search", query="https://www.youtube.com")],
            speak="YouTube aberto no painel, senhor.",
            confidence=0.97,
        )

    if _OPEN_CALANGO_IMAGE.search(normalized):
        return ActionPlan(
            thought="Fast-path: calango.studio modo Studio para gerar imagem no painel.",
            actions=[OpenBrowserSearchAction(action="open_browser_search", query="calango.studio/#/studio")],
            speak="Sim senhor. Abrindo o Studio da Calango no painel — diga o prompt da imagem.",
            confidence=0.97,
        )

    if _OPEN_CALANGO_STUDIO.search(normalized) and re.search(
        r"abr(?:a|e|ir)|acesse?|vá?\s+(?:para|ao?)|open\s+|mexa|naveg|ger[ae]",
        normalized,
        re.I,
    ):
        return ActionPlan(
            thought="Fast-path: abrir modo Studio Calango.",
            actions=[OpenBrowserSearchAction(action="open_browser_search", query="calango.studio/#/studio")],
            speak="Sim senhor. Abrindo o modo Studio da Calango agora.",
            confidence=0.98,
        )

    if _OPEN_CALANGO.search(normalized) and re.search(
        r"abr(?:a|e|ir)|acesse?|vá?\s+(?:para|ao?)|open\s+", normalized, re.I
    ):
        return ActionPlan(
            thought="Fast-path: abrir calango.studio.",
            actions=[OpenBrowserSearchAction(action="open_browser_search", query="calango.studio")],
            speak="Sim senhor. Abrindo a Calango Studio agora.",
            confidence=0.97,
        )

    m_compound = _COMPOUND_GOOGLE.search(normalized)
    if m_compound:
        q = m_compound.group(1).strip().rstrip(".,!?")
        if q:
            return ActionPlan(
                thought=f"Fast-path: abrir Google e pesquisar {q}.",
                actions=[OpenBrowserSearchAction(action="open_browser_search", query=q)],
                speak=f"Sim senhor. Abrindo o Google e pesquisando {q}.",
                confidence=0.97,
            )

    m_sg = _SEARCH_GOOGLE.search(normalized)
    if m_sg:
        q = (m_sg.group(1) or "").strip().rstrip(".,!?")
        if q:
            return ActionPlan(
                thought=f"Fast-path: pesquisar no Google painel: {q}.",
                actions=[OpenBrowserSearchAction(action="open_browser_search", query=q)],
                speak=f"Pesquisando {q} no Google, senhor.",
                confidence=0.95,
            )

    if _OPEN_GOOGLE.search(normalized) and not _SEARCH_GOOGLE.search(normalized):
        return ActionPlan(
            thought="Fast-path: abrir google.com no painel JARVIS (não Chrome externo).",
            actions=[OpenBrowserSearchAction(action="open_browser_search", query="")],
            speak="Google aberto no painel, senhor.",
            confidence=0.98,
        )

    m = _OPEN_SITE.search(normalized)
    if m:
        target = m.group(1).strip().rstrip(".,!?")
        if target.lower() not in ("google", "google.com", "www.google.com"):
            return ActionPlan(
                thought=f"Fast-path: abrir site {target}.",
                actions=[OpenBrowserSearchAction(action="open_browser_search", query=target)],
                speak=f"Sim senhor. Abrindo {target}.",
                confidence=0.92,
            )

    return None