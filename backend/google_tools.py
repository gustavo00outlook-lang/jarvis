"""
Pesquisa web via Gemini + Google Search Grounding (sem xAI web_search).
"""

from __future__ import annotations

import os
from typing import Any, Dict

import httpx

from xai_client import gemini_fast_model, _google_key, ensure_key, google_key_looks_valid, warn_google_key_format


async def search_with_grounding(query: str) -> Dict[str, Any]:
    ensure_key()
    warn_google_key_format()
    key = _google_key()
    if not key:
        raise RuntimeError("GOOGLE_API_KEY ausente")
    model = gemini_fast_model()
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={key}"
    )
    body = {
        "contents": [
            {
                "parts": [
                    {
                        "text": (
                            "Você é J.A.R.V.I.S. Responda em português brasileiro, "
                            "3 a 6 frases naturais, com fatos atuais da pesquisa. "
                            f"Pergunta/pesquisa: {query}"
                        )
                    }
                ]
            }
        ],
        "tools": [{"google_search": {}}],
    }

    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(url, json=body)
        if r.status_code == 429:
            raise RuntimeError(
                "Gemini cota esgotada (429). Recarregue em aistudio.google.com ou use Ollama."
            )
        if r.status_code in (401, 403):
            hint = (
                "Chave invalida — gere AIzaSy... em https://aistudio.google.com/apikey"
                if not google_key_looks_valid()
                else "Chave rejeitada pela API Google."
            )
            raise RuntimeError(f"Google search failed ({r.status_code}): {hint}")
        r.raise_for_status()
        data = r.json()

    text = ""
    for cand in data.get("candidates") or []:
        content = cand.get("content") or {}
        for part in content.get("parts") or []:
            if part.get("text"):
                text += part["text"]

    text = (text or "").strip()
    if not text:
        raise RuntimeError("Gemini grounding sem texto na resposta")

    return {
        "answer": text,
        "query": query,
        "tools_used": ["google_search_grounding"],
    }