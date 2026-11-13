"""
xAI TTS + Custom Voices — Fase 5 (JARVIS PRO)

Tuned for the iconic JARVIS voice: calm, sophisticated, authoritative deep male.
Automatically wraps text with <slow>...</slow> [pause] for cinematic delivery.

Speech tags supported by xAI:
  Inline:   [pause], [long-pause], [laugh], [chuckle], [sigh], [breath]
  Wrapping: <whisper>, <soft>, <slow>, <emphasis>
"""

import json
import os
from pathlib import Path
from typing import Optional

import httpx
from fastapi import HTTPException

from xai_client import ensure_key

XAI_TTS_URL = "https://api.x.ai/v1/tts"
VOICE_STORE = str(Path.home() / '.hermes' / 'jarvis_voice.json')


def _load_voice_store() -> dict:
    try:
        with open(VOICE_STORE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def get_cloned_voice_id() -> Optional[str]:
    """voice_id da voz do Jarvis clonada na xAI (None se ainda não clonada)."""
    return _load_voice_store().get("voice_id") or None


def get_xai_voice_id() -> Optional[str]:
    """voice_id xAI configurado — env XAI_VOICE_ID, store, ou voice_prefs ativo."""
    env_id = (os.getenv("XAI_VOICE_ID") or "").strip()
    if env_id:
        return env_id
    store = _load_voice_store()
    if store.get("xai_voice_id"):
        return store["xai_voice_id"]
    if store.get("voice_id"):
        return store["voice_id"]
    try:
        import voice_prefs
        cfg = voice_prefs.get_voice_config()
        if cfg.get("engine") == "xai" and cfg.get("xai_voice_id"):
            return cfg["xai_voice_id"]
    except Exception:
        pass
    return None


def _xai_clone_blocked() -> bool:
    return bool(_load_voice_store().get("xai_clone_blocked"))


def _mark_xai_clone_blocked(reason: str) -> None:
    data = _load_voice_store()
    data["xai_clone_blocked"] = True
    data["xai_clone_reason"] = (reason or "")[:240]
    try:
        os.makedirs(os.path.dirname(VOICE_STORE), exist_ok=True)
        with open(VOICE_STORE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[voice] não consegui marcar clone bloqueado: {e}")


def _save_cloned_voice_id(voice_id: str, meta: dict) -> None:
    try:
        os.makedirs(os.path.dirname(VOICE_STORE), exist_ok=True)
        with open(VOICE_STORE, "w", encoding="utf-8") as f:
            json.dump({"voice_id": voice_id, **meta}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[voice] não consegui salvar voice_id: {e}")


async def ensure_jarvis_voice(sample_path: str) -> Optional[str]:
    """Clona a voz do sample na xAI uma única vez (idempotente). Roda no startup."""
    existing = get_cloned_voice_id()
    if existing:
        return existing
    if _xai_clone_blocked():
        return None
    # Não gastar boot se xAI está sem crédito / skip
    try:
        from xai_client import is_provider_skipped

        if is_provider_skipped("xai"):
            return None
    except Exception:
        pass
    if (os.getenv("JARVIS_SKIP_XAI") or "").strip().lower() in ("1", "true", "yes", "on"):
        return None
    if not os.path.exists(sample_path):
        return None
    ensure_key()
    if not os.getenv("XAI_API_KEY"):
        return None
    try:
        result = await create_custom_voice(
            "Jarvis Verdadeiro",
            sample_path,
            description="Voz oficial do JARVIS do Gustavo (sample Fish Audio)",
            gender="male",
            language="pt-BR",
        )
        voice_id = result.get("voice_id") or result.get("id")
        if voice_id:
            _save_cloned_voice_id(voice_id, {"name": "Jarvis Verdadeiro", "source": os.path.basename(sample_path)})
            print(f"[voice] Voz do Jarvis clonada na xAI: {voice_id}")
            return voice_id
        err = str(result)[:200]
        low = err.lower()
        if any(
            t in low
            for t in (
                "custom voices",
                "not enabled",
                "exhausted",
                "credits",
                "spending limit",
                "permission-denied",
            )
        ):
            _mark_xai_clone_blocked(err)
        else:
            print(f"[voice] clone xAI sem voice_id na resposta: {err}")
    except Exception as e:
        msg = str(e)
        low = msg.lower()
        if any(
            t in low
            for t in (
                "custom voices",
                "not enabled",
                "exhausted",
                "credits",
                "spending limit",
                "permission-denied",
            )
        ):
            _mark_xai_clone_blocked(msg)
        else:
            print(f"[voice] clone xAI indisponível (seguimos com Eleven/Edge): {e}")
    return None


def enhance_for_jarvis(text: str) -> str:
    """Wrap text for calm, deep, deliberate JARVIS delivery.
    If the caller already provided speech tags, leave them as-is.
    """
    t = (text or "").strip()
    if not t:
        return t
    if any(tag in t for tag in ("<slow>", "<soft>", "<whisper>", "<emphasis>", "[pause]", "[long-pause]")):
        return t
    return t


async def speak_with_xai(
    text: str,
    *,
    voice_id: str = "leo",
    language: str = "pt-BR",
    speed: float = 1.05,
    output_format: Optional[dict] = None,
) -> bytes:
    """
    Calls xAI TTS and returns raw audio bytes (mp3).
    Auto-enhances text with JARVIS calm tags unless pre-tagged.
    - language="pt-BR" + male clone → Jarvis Brasileiro
    - language="en", speed=0.88 → classic authoritative English JARVIS
    """
    ensure_key()
    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        raise HTTPException(500, "XAI_API_KEY required for xAI TTS")

    payload = {
        "text": enhance_for_jarvis(text),
        "voice_id": voice_id,
        "language": language,
        "speed": speed,
    }
    if output_format:
        payload["output_format"] = output_format

    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            XAI_TTS_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
        if r.status_code != 200:
            raise HTTPException(r.status_code, f"xAI TTS error: {r.text}")
        return r.content


async def create_custom_voice(
    name: str,
    audio_file_path: str,
    *,
    description: str = "",
    gender: Optional[str] = None,
    accent: Optional[str] = None,
    language: str = "pt-BR",
) -> dict:
    """Clone a voice once; save the returned voice_id and use it forever.

    For the perfect JARVIS voice: record 60-120s of calm, clear, sophisticated
    male speech (pt-BR for Brasileiro or EN for classic). Then call:
        python backend/clone_jarvis_voice.py "gravacao.wav" "Jarvis"
    """
    ensure_key()
    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        raise RuntimeError("XAI_API_KEY needed")

    mime = "audio/mpeg" if audio_file_path.lower().endswith(".mp3") else "audio/wav"
    with open(audio_file_path, "rb") as f:
        files = {"file": (os.path.basename(audio_file_path), f, mime)}
        data = {"name": name, "description": description, "language": language}
        if gender:
            data["gender"] = gender
        if accent:
            data["accent"] = accent

        async with httpx.AsyncClient(timeout=300) as client:
            r = await client.post(
                "https://api.x.ai/v1/custom-voices",
                headers={"Authorization": f"Bearer {api_key}"},
                files=files,
                data=data,
            )
            return r.json()
