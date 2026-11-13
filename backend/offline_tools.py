"""
Ferramentas offline — tradução e clima sem depender de créditos xAI.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Optional

import httpx

_LANG_MAP = {
    "inglês": "en", "ingles": "en", "english": "en", "en": "en",
    "espanhol": "es", "español": "es", "spanish": "es", "es": "es",
    "português": "pt", "portugues": "pt", "portuguese": "pt", "pt": "pt",
    "francês": "fr", "frances": "fr", "french": "fr", "fr": "fr",
    "alemão": "de", "alemao": "de", "german": "de", "de": "de",
    "italiano": "it", "italian": "it", "it": "it",
    "japonês": "ja", "japones": "ja", "japanese": "ja", "ja": "ja",
    "chinês": "zh-CN", "chines": "zh-CN", "chinese": "zh-CN", "zh": "zh-CN",
}


def _lang_code(target: str) -> str:
    key = (target or "inglês").strip().lower()
    return _LANG_MAP.get(key, "en")


def translate_offline(text: str, target_language: str = "inglês") -> str:
    """Tradução via Google Translate (endpoint público, sem API key)."""
    raw = (text or "").strip()
    if not raw:
        return "Nada para traduzir."
    tl = _lang_code(target_language)
    try:
        url = (
            "https://translate.googleapis.com/translate_a/single"
            f"?client=gtx&sl=auto&tl={urllib.parse.quote(tl)}&dt=t&q={urllib.parse.quote(raw[:500])}"
        )
        r = httpx.get(url, timeout=12, headers={"User-Agent": "JARVIS/1.0"})
        r.raise_for_status()
        data = r.json()
        parts = data[0] if data else []
        out = "".join(p[0] for p in parts if p and p[0]).strip()
        if out:
            label = (target_language or "inglês").strip()
            return f"Tradução ({label}): {out}"
    except Exception as e:
        return f"Tradução indisponível agora ({e}). Texto: {raw[:120]}"
    return f"Não consegui traduzir. Texto: {raw[:120]}"


def weather_search_url(city: str) -> str:
    q = (city or "Caçador SC").strip()
    return f"https://www.google.com/search?q={urllib.parse.quote_plus('quando vai chover em ' + q)}"


def open_google_in_browser(query: str) -> str:
    """Abre o Google de verdade no navegador do Windows (nao Playwright)."""
    import os
    q = (query or "").strip()
    if not q:
        return "Sem busca."
    url = f"https://www.google.com/search?q={urllib.parse.quote_plus(q)}"
    try:
        os.startfile(url)
        return url
    except Exception as e:
        return f"Nao abriu o Google: {e}"


def _wmo_rain(code: int) -> bool:
    return code in range(51, 68) or code in range(80, 83) or code in range(95, 100)


async def forecast_city(city: str = "Caçador") -> str:
    """Previsao real via Open-Meteo (sem captcha do Google)."""
    place = (city or "Caçador").strip() or "Caçador"
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            geo = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": place, "count": 3, "language": "pt", "country": "BR"},
            )
            hits = (geo.json() or {}).get("results") or []
            if hits:
                lat = hits[0]["latitude"]
                lon = hits[0]["longitude"]
                label = hits[0].get("name") or place
                admin = hits[0].get("admin1") or ""
                if admin:
                    label = f"{label}, {admin}"
            else:
                lat, lon, label = -26.775, -51.015, "Caçador, Santa Catarina"
            fc = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,precipitation,weather_code",
                    "daily": "precipitation_probability_max,precipitation_sum,temperature_2m_max,weather_code",
                    "timezone": "America/Sao_Paulo",
                    "forecast_days": 5,
                },
            )
            data = fc.json()
    except Exception as e:
        return f"Nao consegui a previsao agora ({e}). Abri o Google para o senhor conferir."

    cur = data.get("current") or {}
    daily = data.get("daily") or {}
    temp = cur.get("temperature_2m")
    days = daily.get("time") or []
    probs = daily.get("precipitation_probability_max") or []
    codes = daily.get("weather_code") or []
    rain_bits = []
    for i, day in enumerate(days[:4]):
        p = probs[i] if i < len(probs) else None
        code = int(codes[i]) if i < len(codes) and codes[i] is not None else 0
        if p is None:
            continue
        when = "hoje" if i == 0 else ("amanha" if i == 1 else day[8:])
        if p >= 40 or _wmo_rain(code):
            rain_bits.append(f"{when} chance de {int(p)}%")
    now = f"{int(round(temp))} graus" if isinstance(temp, (int, float)) else "temperatura indisponivel"
    if rain_bits:
        chuva = "; ".join(rain_bits)
        return f"Em {label} agora esta {now}. Chuva: {chuva}, senhor."
    return f"Em {label} agora esta {now}. Nos proximos dias a chance de chuva esta baixa, senhor."


def narrate_weather_from_text(city: str, visible: str) -> str:
    """Resume clima a partir do texto visível do Google."""
    vis = " ".join((visible or "").split())
    if not vis or len(vis) < 20:
        return f"Abri a previsão do tempo para {city}, senhor. Veja no painel."
    # Extrai trecho com graus ou palavras de clima
    m = re.search(r"(\d{1,2})\s*°", vis)
    temp = m.group(0) if m else ""
    snippet = vis[:280]
    if temp:
        return f"Em {city}, senhor, vejo cerca de {temp} na previsão. {snippet[:120]}."
    return f"Previsão para {city}, senhor: {snippet[:200]}."