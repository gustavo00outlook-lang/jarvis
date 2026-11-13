"""Extrai termos de busca inteligentes — entende intenção, não texto literal."""

from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, Literal, Optional

_WAKE = re.compile(
    r"^(?:jarvis|ok\s+jarvis|ei\s+jarvis)[,\s:]+",
    re.IGNORECASE,
)

_STRIP_PREFIXES = (
    r"^(?:quero\s+que\s+(?:você|voce|vc)\s+)",
    r"^(?:pode\s+)?(?:me\s+)?(?:ajud[ae]|mostr[ae]|fal[ae]|cont[ae]|diz)\s+(?:com\s+|a\s+)?",
    r"^(?:eu\s+)?(?:quero|preciso|gostaria)\s+(?:de\s+)?(?:ver|assistir|ouvir|saber\s+sobre)\s+",
    r"^(?:pesquis(?:e|ar|a|ei)|busc(?:a|ar|e)|procure|procurar|procurando)\s+"
    r"(?:no\s+)?(?:google|youtube|yt|painel|web|internet|online)?\s*(?:sobre\s+|por\s+|de\s+)?",
    r"^(?:not[ií]cias?\s+(?:sobre|de)\s+)",
    r"^(?:pesquisa\s+)?(?:o\s+que\s+(?:você|voce|vc)\s+(?:acha|pensa|sabe|viu|achou)\s+(?:do|da|de|sobre)\s+)",
    r"^(?:me\s+(?:fala|conta|diz|explica)\s+(?:sobre|do|da|de)\s+)",
    r"^(?:qual\s+(?:foi|é|e)\s+(?:o\s+)?)",
    r"^(?:faz\s+(?:um\s+)?(?:relat[oó]rio|resumo)\s+(?:sobre|do|da|de)\s+)",
    r"^(?:assista|assiste|veja|ver|abre|coloca|põe|poe|reproduz|toca)\s+(?:comigo\s+)?(?:um\s+)?(?:vídeo|video|filme|documentário|documentario|clipe|música|musica)?\s*(?:de|sobre|do|da|no)?\s*",
    r"^(?:no\s+)?youtube\s*[,:]?\s*",
    r"^(?:no\s+)?google\s*[,:]?\s*",
)

_TRAILING_NOISE = re.compile(
    r"\s+(?:por\s+favor|pfv|please|agora|já|ja|aí|ai|né|ne|ok|obrigad\w*)\s*[.!?]*$",
    re.IGNORECASE,
)

_CONVERSATIONAL = re.compile(
    r"\b(?:você|voce|vc|acha|pensa|sabe|como\s+está|tudo\s+bem|me\s+explica|me\s+diz)\b",
    re.IGNORECASE,
)

_YOUTUBE_OPEN = re.compile(
    r"\b(?:abre|abra|abrir|acesse|acessa|vá|va)\s+(?:o\s+)?youtube\b",
    re.IGNORECASE,
)

_YOUTUBE_COWATCH = re.compile(
    r"\b(?:assista|assiste|veja|ver|abre)\s+(?:comigo|junto|juntos)"
    r"|\b(?:coment[ae]|narre|reag[ie]|argument[ae]|discut[ae])\s+(?:enquanto|durante|ao|comigo)"
    r"|\b(?:vídeo|video)\b.*\b(?:coment|argument|discut|opini)\b"
    r"|\b(?:argument[ae]|discut[ae])\b.*\b(?:vídeo|video|youtube)\b",
    re.IGNORECASE,
)

_YOUTUBE_PLAY = re.compile(
    r"\b(?:assista|assiste|veja|ver|abre|coloca|põe|poe|reproduz|toca|dá\s+play|da\s+play|play)\s+"
    r"(?:comigo\s+)?(?:um\s+)?(?:vídeo|video|filme|documentário|documentario|clipe|short|shorts)?\s*"
    r"(?:de|sobre|do|da|no|com)?\s*(.+)$",
    re.IGNORECASE,
)

_YOUTUBE_SEARCH = re.compile(
    r"\b(?:pesquis(?:e|ar|a|ei)|busc(?:a|ar|e)|procure|procurar|encontr[ae]|ach[ae])\s+(.+?)\s+(?:no\s+)?youtube\b"
    r"|\b(?:no\s+)?youtube\s+(?:pesquis(?:e|ar|a|ei)?|busc(?:a|ar|e)?|procure|procurar)\s+(.+)"
    r"|\b(?:coloca|põe|poe)\s+(?:um\s+)?(?:vídeo|video)\s+(?:de|sobre)\s+(.+)",
    re.IGNORECASE,
)

_PLATFORM_NOISE = re.compile(
    r"\b(?:no\s+)?(?:google|youtube|yt|painel|site|web|internet|online)\b",
    re.IGNORECASE,
)


def strip_wake(text: str) -> str:
    return _WAKE.sub("", (text or "").strip()).strip()


def normalize_search_query(text: str, *, platform: str = "web") -> str:
    """Limpeza rápida (regex) — tira wake, filler e ruído de plataforma."""
    raw = strip_wake(text)
    if not raw:
        return ""

    for pat in _STRIP_PREFIXES:
        nxt = re.sub(pat, "", raw, flags=re.IGNORECASE).strip()
        if nxt and nxt != raw:
            raw = nxt

    raw = _PLATFORM_NOISE.sub(" ", raw)
    raw = re.sub(r"\s+e\s+(?:argument[ae]|discut[ae]|coment[ae]|debate).*$", "", raw, flags=re.I)
    raw = _TRAILING_NOISE.sub("", raw)
    raw = re.sub(r"\b(?:um|uma|uns|umas)\s+", " ", raw, flags=re.I)
    raw = re.sub(
        r"\b(?:vídeo|video|filme|documentário|documentario|clipe|short|shorts)\s*(?:de|sobre|do|da|no|na)?\s*",
        " ",
        raw,
        flags=re.I,
    )
    raw = re.sub(r"\b(?:sobre|de|do|da|no|na|com)\s+", " ", raw, flags=re.I)
    raw = re.sub(r"\s+", " ", raw).strip().rstrip(".,!?;:")

    # Remove artigo/filler final ("nova IA do" → "nova IA")
    raw = re.sub(r"\s+(?:do|da|de|no|na|em|ao|aos|à|a|o)\s*$", "", raw, flags=re.I).strip()

    if len(raw) < 2:
        return strip_wake(text)[:120]
    return raw[:120]


def _looks_conversational(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if _CONVERSATIONAL.search(t):
        return True
    return len(t.split()) > 8


async def resolve_search_query(
    text: str,
    *,
    platform: Literal["web", "google", "youtube"] = "web",
) -> str:
    """Termos otimizados para busca — usa LLM quando a frase é conversacional."""
    fast = normalize_search_query(text, platform=platform)
    if not fast:
        return ""
    words = fast.split()
    if 2 <= len(words) <= 6 and len(fast) >= 4:
        return fast
    if not _looks_conversational(text) and len(words) <= 8:
        return fast

    _GARBAGE = frozenset({"ok", "ping", "sim", "não", "nao", "yes", "no", "n/a", "none"})

    def _valid_llm_query(candidate: str) -> bool:
        c = (candidate or "").strip().strip("\"'")
        c = re.sub(r"\s+", " ", c)
        if not c or len(c) < 3 or len(c) > 80:
            return False
        if "\n" in candidate or ":" in c[:20]:
            return False
        if c.lower() in _GARBAGE:
            return False
        if re.search(r"termos?\s+de\s+busca", c, re.I):
            return False
        if len(c.split()) < 2 or len(c.split()) > 8:
            return False
        return True

    try:
        from xai_client import chat_completions_create, get_fast_model

        plat_label = {"web": "Google", "google": "Google", "youtube": "YouTube"}[platform]
        sys = (
            f"Você extrai termos de busca para {plat_label} a partir de pedidos em português. "
            "Retorne APENAS os termos de busca (2-6 palavras), sem frase completa, "
            "sem aspas, sem explicação. Ex: 'quero saber sobre a nova IA do Google' → nova IA Google"
        )
        resp = await asyncio.wait_for(
            chat_completions_create(
                model=get_fast_model(),
                messages=[
                    {"role": "system", "content": sys},
                    {"role": "user", "content": strip_wake(text)},
                ],
                max_tokens=40,
                temperature=0.2,
            ),
            timeout=12.0,
        )
        out = (resp.choices[0].message.content or "").strip().strip("\"'")
        out = re.sub(r"^(?:busca|pesquisa|termos)\s*:\s*", "", out, flags=re.I).strip()
        if _valid_llm_query(out):
            return out[:120]
    except Exception as e:
        print(f"[query_intelligence] LLM falhou: {e}")

    return fast


def parse_youtube_intent(text: str) -> Optional[Dict[str, Any]]:
    """Detecta intenção YouTube: open | search | play | cowatch."""
    raw = strip_wake(text)
    if not raw:
        return None

    # "abre o google" / "acesse google" — nunca rotear para YouTube
    if re.search(r"\b(?:abre|abra|abrir|acesse|acessa)\s+(?:o\s+)?google\b", raw, re.I):
        if not re.search(r"\byoutube\b", raw, re.I):
            return None

    has_yt_context = bool(
        re.search(
            r"\b(?:youtube|yt|vídeo|video|assistir|assista|shorts|documentário|documentario)\b",
            raw,
            re.I,
        )
    )
    if not has_yt_context:
        return None

    debate = bool(
        re.search(r"\b(?:argument[ae]|discut[ae]|opini[ãa]o|debate|contra|prós|pros)\b", raw, re.I)
    )

    if _YOUTUBE_COWATCH.search(raw):
        q = normalize_search_query(raw, platform="youtube")
        return {"action": "cowatch", "query": q, "debate": debate}

    if _YOUTUBE_OPEN.search(raw) and not _YOUTUBE_SEARCH.search(raw):
        return {"action": "open", "query": "", "debate": debate}

    m = _YOUTUBE_SEARCH.search(raw)
    if m:
        q = (m.group(1) or m.group(2) or "").strip().rstrip(".,!?")
        q = normalize_search_query(q, platform="youtube") or q
        if len(q) >= 2:
            return {"action": "search", "query": q, "debate": debate}

    m2 = _YOUTUBE_PLAY.search(raw)
    if m2:
        q = (m2.group(1) or "").strip().rstrip(".,!?")
        q = normalize_search_query(q, platform="youtube") or q
        if len(q) >= 2 and q.lower() not in ("youtube", "yt", "o youtube", "no youtube"):
            return {"action": "play", "query": q, "debate": debate}

    if re.search(r"\byoutube\b", raw, re.I):
        q = normalize_search_query(raw, platform="youtube")
        if q and len(q) >= 2:
            play = bool(re.search(r"\b(?:assistir|assista|veja|ver|play|toca)\b", text, re.I))
            return {"action": "play" if play else "search", "query": q, "debate": debate}

    return None