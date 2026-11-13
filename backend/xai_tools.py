"""
Busca web — Gemini Grounding → painel Google (offline) → xAI web_search.
"""

import asyncio
import re
import time
from typing import Optional, List, Dict, Any, Tuple

from fastapi import HTTPException

from xai_client import (
    get_client,
    get_fast_model,
    is_google,
    is_fallbackable_error,
    is_provider_skipped,
)
from google_tools import search_with_grounding

_SEARCH_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_SEARCH_CACHE_TTL = 300.0  # 5 min


def _cache_key(query: str) -> str:
    return re.sub(r"\s+", " ", (query or "").strip().lower())


async def search_via_panel(query: str) -> Dict[str, Any]:
    """Abre Google no painel Playwright e extrai títulos/trechos dos resultados."""
    import local_vision
    import web_browser

    q = (query or "").strip()
    if not q:
        raise RuntimeError("query vazia")
    url = web_browser.build_nav_url(q)
    try:
        feedback = await asyncio.wait_for(web_browser.open_url(url), timeout=50.0)
    except asyncio.TimeoutError:
        feedback = f"Pesquisa aberta: {url}\nTexto visível: carregando resultados no painel Google."

    # Extrai resultados orgânicos do Google (melhor que body.innerText genérico)
    serps: list = []
    try:
        preview = await asyncio.wait_for(web_browser.get_preview(), timeout=12.0)
        # tenta evaluate via open already done — use page text from feedback
    except Exception:
        preview = {}

    try:
        # re-read page for structured results
        read_fb = await asyncio.wait_for(web_browser.read_page(), timeout=15.0)
        if read_fb and len(str(read_fb)) > len(str(feedback)):
            feedback = str(read_fb)
    except Exception:
        pass

    visible = str(feedback)
    if "Texto visível:" in visible:
        visible = visible.split("Texto visível:", 1)[-1].strip()
    # limpa chrome chrome chrome
    visible = re.sub(
        r"(?i)(ir para o conte[uú]do|fazer login|modo ia|google\.com).*",
        " ",
        visible,
    )
    visible = re.sub(r"\s+", " ", visible).strip()

    answer = ""
    if visible and len(visible) >= 40 and local_vision.ocr_quality_ok(visible[:400]):
        answer = local_vision.narrate_from_visible_text(q, visible[:1200], mode="search")
    if not answer or len(answer) < 20:
        # anexa free search se painel fraco
        try:
            from free_web_search import free_web_search

            free = await free_web_search(q)
            answer = free.get("answer") or answer
            tools = ["browse_open", "panel_text"] + list(free.get("tools_used") or [])
            return {
                "answer": answer,
                "query": q,
                "tools_used": tools,
                "fallback": "panel+free",
            }
        except Exception:
            pass
    if not answer or len(answer) < 12:
        answer = (
            f"Abri a pesquisa sobre {q} no painel Google, senhor. "
            "Veja os resultados na tela."
        )
    return {
        "answer": answer,
        "query": q,
        "tools_used": ["browse_open", "panel_text"],
        "fallback": "panel",
    }


async def _search_free_then_panel(query: str, key: str, errors: List[str]) -> Dict[str, Any]:
    """DuckDuckGo + Wikipedia, depois painel Google se precisar."""
    # 1) Fontes gratuitas (funcionam sem Gemini/xAI)
    try:
        from free_web_search import free_web_search

        result = await free_web_search(query)
        if result.get("answer") and len(str(result["answer"])) >= 40:
            if key:
                _SEARCH_CACHE[key] = (time.time(), result)
            print(f"[search] free OK sources={result.get('tools_used')}")
            return result
    except Exception as fe:
        errors.append(f"free:{fe}")
        print(f"[search] free falhou ({str(fe)[:100]}) — painel Google…")

    # 2) Painel Google (Playwright) — o usuário vê a pesquisa
    try:
        result = await search_via_panel(query)
        if key and result.get("answer"):
            _SEARCH_CACHE[key] = (time.time(), result)
        return result
    except Exception as pe:
        errors.append(f"panel:{pe}")
        raise HTTPException(
            500,
            "Search failed: " + " | ".join(errors[-4:]) if errors else str(pe),
        )


async def search_with_tools(
    query: str,
    *,
    use_web: bool = True,
    use_x: bool = False,
    x_handles: Optional[List[str]] = None,
    max_results: int = 8,
) -> Dict[str, Any]:
    """
    Pesquisa web:
      Gemini Grounding → free (DDG+Wiki) → painel Google → xAI web_search.
    """
    key = _cache_key(query)
    if key and use_web and not use_x:
        cached = _SEARCH_CACHE.get(key)
        if cached and (time.time() - cached[0]) < _SEARCH_CACHE_TTL:
            return {**cached[1], "cached": True}

    errors: List[str] = []

    # Gemini Grounding (melhor quando há cota)
    if is_google() and use_web and not use_x and not is_provider_skipped("google"):
        try:
            result = await search_with_grounding(query)
            if key and result.get("answer"):
                _SEARCH_CACHE[key] = (time.time(), result)
            return result
        except Exception as e:
            errors.append(f"google:{e}")
            if is_fallbackable_error(e):
                print(f"[search] Gemini falhou ({str(e)[:100]}) — free/web…")
                return await _search_free_then_panel(query, key, errors)
            raise HTTPException(500, f"Google search failed: {e}")

    # Sem Gemini (ollama-only / cota) ou xAI skip → free + painel Google
    if use_web and not use_x and (
        is_provider_skipped("xai")
        or is_provider_skipped("google")
        or not is_google()
    ):
        print("[search] usando DuckDuckGo/Wikipedia + painel Google…")
        return await _search_free_then_panel(query, key, errors)

    client = get_client()

    tools: List[Dict] = []
    if use_web:
        tools.append({"type": "web_search"})
    if use_x:
        tool: Dict = {"type": "x_search"}
        if x_handles:
            tool["allowed_x_handles"] = x_handles
        tools.append(tool)
    if not tools:
        tools = [{"type": "web_search"}]

    try:
        resp = await client.responses.create(
            model=get_fast_model(),
            input=[{"role": "user", "content": query}],
            tools=tools,
            tool_choice="auto",
        )

        text = ""
        for item in resp.output:
            if item.type == "message":
                for c in item.content:
                    if c.type == "output_text":
                        text = c.text

        result = {
            "answer": text,
            "query": query,
            "tools_used": [t["type"] for t in tools],
        }
        if key and use_web and not use_x and text:
            _SEARCH_CACHE[key] = (time.time(), result)
        return result

    except Exception as e:
        errors.append(f"xai:{e}")
        try:
            result = await search_with_grounding(query)
            if key and result.get("answer"):
                _SEARCH_CACHE[key] = (time.time(), result)
            return result
        except Exception as ge:
            errors.append(f"google_retry:{ge}")
            if is_fallbackable_error(ge) or is_fallbackable_error(e):
                try:
                    result = await search_via_panel(query)
                    if key and result.get("answer"):
                        _SEARCH_CACHE[key] = (time.time(), result)
                    return result
                except Exception as pe:
                    errors.append(f"panel:{pe}")
            raise HTTPException(500, f"Tool search failed: {' | '.join(errors[-3:])}")