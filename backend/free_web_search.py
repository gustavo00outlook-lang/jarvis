"""
Pesquisa web GRATUITA (sem Gemini/xAI).

Fontes:
  1) DuckDuckGo HTML (t├¡tulos + trechos)
  2) DuckDuckGo Instant Answer API
  3) Wikipedia (pt/en) quando o tema for enciclop├®dico

Usado quando Google Grounding / xAI est├úo sem cota.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, unquote

import httpx

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 "
    "JARVIS-Pro/1.0"
)
_HEADERS = {
    "User-Agent": _UA,
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
}


def _clean(s: str, n: int = 280) -> str:
    t = re.sub(r"\s+", " ", (s or "").strip())
    return t[:n]


async def _ddg_html(query: str, *, max_results: int = 8) -> List[Dict[str, str]]:
    q = (query or "").strip()
    if not q:
        return []
    url = "https://html.duckduckgo.com/html/"
    try:
        async with httpx.AsyncClient(timeout=22.0, follow_redirects=True, headers=_HEADERS) as client:
            r = await client.post(url, data={"q": q, "b": ""})
            if r.status_code != 200 or len(r.text) < 200:
                r = await client.get(url, params={"q": q})
            if r.status_code != 200:
                return []
            html = r.text
    except Exception:
        return []

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict[str, str]] = []
    # Layout cl├íssico DDG HTML
    for block in soup.select(".result")[: max_results + 2]:
        a = block.select_one("a.result__a") or block.select_one("a")
        if not a:
            continue
        title = _clean(a.get_text(" ", strip=True), 160)
        href = (a.get("href") or "").strip()
        # ddg redirect: //duckduckgo.com/l/?uddg=...
        m = re.search(r"uddg=([^&]+)", href)
        if m:
            try:
                href = unquote(m.group(1))
            except Exception:
                pass
        snip_el = block.select_one(".result__snippet") or block.select_one(".result__body")
        snip = _clean(snip_el.get_text(" ", strip=True) if snip_el else "", 320)
        if not title or len(title) < 3:
            continue
        if any(x in title.lower() for x in ("duckduckgo", "javascript", "enable")):
            continue
        out.append({"title": title, "snippet": snip, "url": href[:240]})
        if len(out) >= max_results:
            break

    # Fallback gen├®rico de links
    if not out:
        for a in soup.select("a[href]")[:40]:
            title = _clean(a.get_text(" ", strip=True), 140)
            href = (a.get("href") or "").strip()
            if not title or len(title) < 12:
                continue
            if href.startswith("/") or "duckduckgo.com" in href:
                continue
            if not href.startswith("http"):
                continue
            out.append({"title": title, "snippet": "", "url": href[:240]})
            if len(out) >= max_results:
                break
    return out


async def _ddg_instant(query: str) -> Dict[str, str]:
    q = (query or "").strip()
    if not q:
        return {}
    try:
        async with httpx.AsyncClient(timeout=15.0, headers=_HEADERS) as client:
            r = await client.get(
                "https://api.duckduckgo.com/",
                params={
                    "q": q,
                    "format": "json",
                    "no_html": "1",
                    "skip_disambig": "1",
                },
            )
            if r.status_code != 200:
                return {}
            data = r.json()
    except Exception:
        return {}
    abstract = _clean(data.get("AbstractText") or data.get("Abstract") or "", 600)
    heading = _clean(data.get("Heading") or "", 120)
    source = _clean(data.get("AbstractURL") or data.get("AbstractSource") or "", 200)
    related: List[str] = []
    for item in (data.get("RelatedTopics") or [])[:6]:
        if isinstance(item, dict):
            t = item.get("Text") or ""
            if t:
                related.append(_clean(t, 200))
        elif isinstance(item, list):
            continue
    return {
        "heading": heading,
        "abstract": abstract,
        "source": source,
        "related": " | ".join(related[:4]),
    }


async def _wikipedia(query: str) -> Dict[str, str]:
    q = (query or "").strip()
    if not q or len(q) < 2:
        return {}
    title = re.sub(r"\s+", " ", q)
    # tenta t├¡tulo direto e depois search
    for lang in ("pt", "en"):
        base = f"https://{lang}.wikipedia.org"
        try:
            async with httpx.AsyncClient(timeout=15.0, headers=_HEADERS) as client:
                # search
                sr = await client.get(
                    f"{base}/w/api.php",
                    params={
                        "action": "opensearch",
                        "search": title,
                        "limit": 1,
                        "namespace": 0,
                        "format": "json",
                    },
                )
                if sr.status_code != 200:
                    continue
                data = sr.json()
                names = data[1] if isinstance(data, list) and len(data) > 1 else []
                if not names:
                    continue
                page = names[0]
                sumr = await client.get(
                    f"{base}/api/rest_v1/page/summary/{quote_plus(page)}",
                )
                if sumr.status_code != 200:
                    continue
                j = sumr.json()
                extract = _clean(j.get("extract") or "", 700)
                if not extract:
                    continue
                return {
                    "title": _clean(j.get("title") or page, 120),
                    "extract": extract,
                    "url": _clean((j.get("content_urls") or {}).get("desktop", {}).get("page") or "", 200),
                    "lang": lang,
                }
        except Exception:
            continue
    return {}


def _compose_answer(query: str, hits: List[Dict[str, str]], instant: Dict[str, str], wiki: Dict[str, str]) -> str:
    parts: List[str] = []
    if instant.get("abstract"):
        h = instant.get("heading") or query
        parts.append(f"{h}: {instant['abstract']}")
    if wiki.get("extract"):
        parts.append(f"Wikipedia ({wiki.get('lang', 'pt')} ÔÇö {wiki.get('title')}): {wiki['extract']}")
    if hits:
        parts.append("Resultados web recentes:")
        for i, h in enumerate(hits[:6], 1):
            line = f"{i}. {h.get('title', '')}"
            if h.get("snippet"):
                line += f" ÔÇö {h['snippet']}"
            if h.get("url"):
                line += f" ({h['url']})"
            parts.append(line)
    if not parts:
        return ""
    body = "\n".join(parts)
    # Resposta fal├ível curta no topo
    spoken_bits = []
    if instant.get("abstract"):
        spoken_bits.append(instant["abstract"][:220])
    elif wiki.get("extract"):
        spoken_bits.append(wiki["extract"][:220])
    elif hits:
        spoken_bits.append(
            "Principais fontes: " + "; ".join(h["title"] for h in hits[:3])
        )
    spoken = " ".join(spoken_bits).strip()
    if spoken:
        return (
            f"Sobre {query}: {spoken}\n\n"
            f"---\nMaterial completo para relat├│rio:\n{body}"
        )
    return body


async def free_web_search(query: str, *, max_results: int = 8) -> Dict[str, Any]:
    """Pesquisa multi-fonte gratuita. Levanta RuntimeError se tudo falhar."""
    q = (query or "").strip()
    if len(q) < 2:
        raise RuntimeError("query vazia")

    hits = await _ddg_html(q, max_results=max_results)
    instant = await _ddg_instant(q)
    wiki = await _wikipedia(q)

    answer = _compose_answer(q, hits, instant, wiki)
    if not answer or len(answer) < 40:
        raise RuntimeError("free search sem resultados suficientes")

    tools = ["duckduckgo_html"] if hits else []
    if instant.get("abstract"):
        tools.append("duckduckgo_instant")
    if wiki.get("extract"):
        tools.append("wikipedia")

    return {
        "answer": answer,
        "query": q,
        "tools_used": tools or ["free_web_search"],
        "fallback": "free",
        "hits": hits[:max_results],
        "sources": {
            "duckduckgo": bool(hits or instant.get("abstract")),
            "wikipedia": bool(wiki.get("extract")),
        },
    }
