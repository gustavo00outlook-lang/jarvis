"""Preferência de voz JARVIS — persiste até o usuário pedir outra."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

_STORE = (Path.home() / '.hermes' / 'jarvis_voice_pref.json')

VOICES: Dict[str, Dict[str, Any]] = {
    "thomas": {
        "id": "thomas",
        "label": "JARVIS pt-dubbed — Fish Audio (natural)",
        "engine": "fish",
        "speed": 1.0,
        "volume": 0,
        "temperature": 0.54,
        "top_p": 0.65,
        "mp3_bitrate": 256,
        "normalize": False,
        "latency": "normal",
        "repetition_penalty": 1.04,
        "chunk_length": 240,
        "description": "Clone Fish do 0701.WAV projeto (54s completo) — fluido, detalhado, tom do Gustavo",
    },
    "antonio": {
        "id": "antonio",
        "label": "Antonio — Neural pt-BR (Edge)",
        "engine": "edge",
        "rate": "-3%",
        "pitch": "-7Hz",
        "description": "Microsoft Antonio Neural, pt-BR nativo — tom grave/calmo estilo JARVIS",
    },
    "eleven": {
        "id": "eleven",
        "label": "JARVIS Thomas",
        "engine": "eleven",
        "model": "eleven_multilingual_v2",
        "stability": 0.62,
        "similarity_boost": 1.0,
        "style": 0.0,
        "speed": 0.95,
        "use_speaker_boost": True,
        "seed": 7001,
        "description": (
            "Clone JARVIS Thomas na conta ElevenLabs de quem roda — "
            "calmo, speed 0.95, stab 0.62, sem drift de tom. "
            "Defina ELEVENLABS_VOICE_ID no .env.local."
        ),
    },
    "xai": {
        "id": "xai",
        "label": "Jarvis — xAI TTS (custom)",
        "engine": "xai",
        "xai_voice_id": "",
        "language": "pt-BR",
        "speed": 1.0,
        "description": "Voz custom xAI — clone Jarvis via API TTS",
    },
    "voicebox": {
        "id": "voicebox",
        "label": "Voicebox — TTS local (open source)",
        "engine": "voicebox",
        "mcp_url": "http://127.0.0.1:8787",
        "description": "Estúdio local voicebox.sh — clone voz, 23 idiomas, sem mensalidade (fallback futuro)",
    },
    "local": {
        "id": "local",
        "label": "JARVIS Thomas (master.wav 0701)",
        "engine": "local",
        "prefer": "xtts",
        "description": "Clone local XTTS do master.wav Thomas 0701 — voz canônica",
    },
}

DEFAULT_VOICE = "local"


def _load() -> Dict[str, Any]:
    try:
        if _STORE.exists():
            return json.loads(_STORE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"voice_id": DEFAULT_VOICE}


def _save(data: Dict[str, Any]) -> None:
    _STORE.parent.mkdir(parents=True, exist_ok=True)
    _STORE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _normalize_voice_id(vid: str) -> str:
    v = (vid or "").strip().lower()
    aliases = {
        "elevenlabs": "eleven",
        "thomas": "local",
        "0701": "local",
        "edge": "local",
        "antonio": "local",
        "clone": "local",
        "xtts": "local",
    }
    return aliases.get(v, v)


def get_voice_id() -> str:
    env = _normalize_voice_id(os.getenv("JARVIS_VOICE_PRIMARY") or "")
    stored = _normalize_voice_id(str(_load().get("voice_id") or ""))
    vid = env or stored or DEFAULT_VOICE
    return vid if vid in VOICES else DEFAULT_VOICE


def get_voice_config() -> Dict[str, Any]:
    vid = get_voice_id()
    cfg = {**VOICES[vid], "voice_id": vid}
    overrides = _load().get("tuning_overrides") or {}
    if isinstance(overrides, dict):
        for k, v in overrides.items():
            if k in cfg or k in (
                "stability",
                "similarity_boost",
                "style",
                "speed",
                "model",
                "use_speaker_boost",
                "seed",
            ):
                cfg[k] = v
    return cfg


def set_voice_id(voice_id: str) -> Dict[str, Any]:
    key = (voice_id or "").strip().lower()
    aliases = {
        "fish": "thomas",
        "jarvis": "local",
        "verdadeiro": "local",
        "thomas": "local",
        "edge": "local",
        "antonio": "local",
        "antônio": "local",
        "microsoft": "local",
        "neural": "local",
        "eleven": "eleven",
        "elevenlabs": "eleven",
        "11labs": "eleven",
        "xai": "xai",
        "grok": "xai",
        "voicebox": "voicebox",
        "local": "local",
        "clone": "local",
        "0701": "local",
        "thomas-0701": "local",
    }
    key = aliases.get(key, key)
    if key not in VOICES:
        raise ValueError(f"Voz desconhecida: {voice_id}")
    data = _load()
    data["voice_id"] = key
    _save(data)
    return get_voice_config()


def list_voices() -> Dict[str, Dict[str, Any]]:
    return VOICES


def parse_voice_change(text: str) -> Optional[str]:
    """Detecta pedido explícito de troca de voz. Retorna voice_id ou None."""
    raw = (text or "").strip()
    if not raw:
        return None
    low = raw.lower()

    if re.search(r"eleven\s?labs?|11\s?labs|voz\s+natural\s+brasileir|thomas\s+brasileir", low):
        return "local"

    if re.search(r"\bvoz\s+(?:para|do|de)\s+(?:antonio|antônio|thomas|fish|edge|jarvis|eleven|xai|grok)\b", low):
        return "local"

    # Preferências qualitativas — mantém o clone 0701 exato (ElevenLabs)
    if re.search(
        r"\b(?:mais\s+fluida?|mais\s+natural|fluidez|mais\s+detalhad|pron[uú]ncia\s+natural|"
        r"corrig(?:e|ir)\s+(?:a\s+)?voz)\b",
        low,
    ):
        return "local"
    if re.search(r"\b(?:mais\s+grave|mais\s+jarvis|cinematogr[aá]fic|tom\s+de\s+filme)\b", low):
        return "local"

    if not re.search(r"\b(?:voz|voice|tom)\b", low) and not re.search(
        r"\b(?:antonio|antônio|thomas|fish|edge|jarvis|xai|grok)\b", low
    ):
        return None

    action = re.search(
        r"\b(?:mud[ae]|troc[ae]|coloc[ae]|usa|use|quero|prefiro|ponha|bote|deixe|alter[ae]|"
        r"mudar|trocar|colocar|usar|passa|passe)\b",
        low,
    )
    if not action and not re.search(r"\bvoz\s+(?:do|de|para)\b", low):
        return None

    if re.search(
        r"\b(?:antonio|antônio|edge|microsoft|neural|xai|grok|fish|thomas|jarvis|verdadeiro)\b",
        low,
    ):
        return "local"

    return None