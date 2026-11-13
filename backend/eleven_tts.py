"""ElevenLabs TTS — voz JARVIS natural (timbre Thomas em pt-BR).

Lê ELEVENLABS_API_KEY e ELEVENLABS_VOICE_ID do ambiente; se não houver,
faz fallback lendo o .env.local do projeto ou C:\\Users\\Micro\\.hermes\\.env.
Nunca hardcode de chave.

Pós-processo: loudnorm + limiter (anti-estouro, presença controlada).

Fila global: evita 429 concurrent_limit_exceeded (plano free ~5 paralelos)
que fazia o endpoint cair no Edge Antonio (voz errada).
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

# Uma síntese por vez no processo backend (watchdog + UI + prefetch)
_ELEVEN_LOCK: Optional[asyncio.Lock] = None


def _get_eleven_lock() -> asyncio.Lock:
    global _ELEVEN_LOCK
    if _ELEVEN_LOCK is None:
        _ELEVEN_LOCK = asyncio.Lock()
    return _ELEVEN_LOCK

_ENV_PATHS = [
    Path(__file__).resolve().parent.parent / ".env.local",
    (Path.home() / '.hermes' / '.env'),
]

# multilingual_v2: melhor fidelidade de tom/calma em pt-BR (vs turbo mais rápido)
_DEFAULT_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2")


def _read_env(name: str) -> str:
    val = (os.getenv(name) or "").strip()
    if val:
        return val
    for p in _ENV_PATHS:
        try:
            content = p.read_text(encoding="utf-8")
        except Exception:
            continue
        m = re.search(rf"{name}\s*=\s*['\"]?([^'\"\r\n]+)", content)
        if m:
            val = m.group(1).strip()
            os.environ[name] = val
            return val
    return ""


def eleven_api_key() -> str:
    return _read_env("ELEVENLABS_API_KEY")


def eleven_voice_id() -> str:
    return _read_env("ELEVENLABS_VOICE_ID")


def eleven_configured() -> bool:
    return bool(eleven_api_key()) and bool(eleven_voice_id())


def _eleven_tuning() -> Dict[str, Any]:
    try:
        from voice_prefs import get_voice_config

        cfg = get_voice_config()
        if cfg.get("engine") == "eleven" or cfg.get("voice_id") == "eleven":
            return cfg
    except Exception:
        pass
    # JARVIS Thomas canônico: calmo, sem drift, speed 0.95
    return {
        "model": _DEFAULT_MODEL,
        "stability": 0.62,
        "similarity_boost": 1.0,
        "style": 0.0,
        "speed": 0.95,
        "use_speaker_boost": True,
        "seed": 7001,
    }


def _normalize_mp3(audio: bytes) -> bytes:
    """Volume confortavel sem remodelar o tom no meio da fala.

    loudnorm agressivo + LRA baixo "puxava" o timbre ao longo do audio.
    Aqui: ganho fixo + limiter suave (sem loudnorm dinamico).
    """
    if not audio or len(audio) < 500:
        return audio
    ff = shutil.which("ffmpeg")
    if not ff:
        return audio
    try:
        with tempfile.TemporaryDirectory(prefix="jarvis-tts-") as td:
            src = Path(td) / "in.mp3"
            dst = Path(td) / "out.mp3"
            src.write_bytes(audio)
            cmd = [
                ff, "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(src),
                "-af",
                # Presenca do sample 50s+ — menos "apagado/cansado" que 0.86
                "volume=0.96,"
                "alimiter=limit=0.92:attack=5:release=50",
                "-c:a", "libmp3lame", "-b:a", "192k",
                str(dst),
            ]
            proc = subprocess.run(cmd, capture_output=True, timeout=30)
            if proc.returncode == 0 and dst.is_file() and dst.stat().st_size > 500:
                return dst.read_bytes()
    except Exception:
        pass
    return audio


def _prep_text(text: str) -> str:
    """Limpa texto sem forcar mudancas de prosodia no meio da frase.

    Importante: NAO injetar pontos artificiais (ex: "e" -> ". E") — isso faz o
    modelo Eleven rearmar o tom e o usuario ouve "comeca igual, depois muda".
    """
    t = (text or "").strip()
    if not t:
        return t
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    t = re.sub(r"\*(.+?)\*", r"\1", t)
    t = re.sub(r"`(.+?)`", r"\1", t)
    t = re.sub(r"#{1,6}\s+", "", t)
    # Remove bullets/listas que soam roboticas no TTS
    t = re.sub(r"(?m)^\s*[-•*]\s+", "", t)
    t = re.sub(r"(?m)^\s*\d+[.)]\s+", "", t)
    t = re.sub(r"\s+", " ", t)
    # Tracos longos viram virgula (pausa leve) — nao ponto (rearm de tom)
    t = re.sub(r"\s*[—–]\s*", ", ", t)
    t = re.sub(r"!\s*", ". ", t)  # evita exaltacao
    t = re.sub(r";\s*", ", ", t)
    # Normaliza espacos apos pontuacao existente (sem inventar frases)
    t = re.sub(r"\s*([,.!?])\s*", r"\1 ", t)
    t = re.sub(r"\.\s*\.", ".", t)
    t = re.sub(r",\s*,", ",", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


async def speak_eleven(
    text: str,
    *,
    stability: Optional[float] = None,
    similarity: Optional[float] = None,
    style: Optional[float] = None,
    speed: Optional[float] = None,
) -> bytes:
    """Sintetiza `text` na voz ElevenLabs configurada. Retorna mp3 (bytes)."""
    key = eleven_api_key()
    voice = eleven_voice_id()
    if not key or not voice:
        raise RuntimeError(
            "ELEVENLABS_API_KEY/ELEVENLABS_VOICE_ID ausentes (.env.local ou .hermes/.env)"
        )

    tune = _eleven_tuning()
    prepared = _prep_text(text)
    model = str(tune.get("model") or _DEFAULT_MODEL)
    # Thomas canônico: calmo (stab 0.62, speed 0.95) — fallback se o store falhar
    stab = float(stability if stability is not None else (tune.get("stability") if tune.get("stability") is not None else 0.62))
    sim = float(similarity if similarity is not None else (tune.get("similarity_boost") if tune.get("similarity_boost") is not None else 1.0))
    sty = float(style if style is not None else (tune.get("style") if tune.get("style") is not None else 0.0))
    spd = float(speed if speed is not None else (tune.get("speed") if tune.get("speed") is not None else 0.95))

    fallback_voice = _read_env("ELEVENLABS_FALLBACK_VOICE_ID") or "xNGAXaCH8MaasNuo7Hr7"
    voice_settings: Dict[str, Any] = {
        "stability": max(0.0, min(1.0, stab)),
        "similarity_boost": max(0.0, min(1.0, sim)),
        "style": max(0.0, min(1.0, sty)),
        "use_speaker_boost": bool(tune["use_speaker_boost"]) if "use_speaker_boost" in tune else True,
    }
    # Sempre envia speed (1.0+ tira o arrasto cansado do preset 0.95)
    voice_settings["speed"] = max(0.7, min(1.2, spd if spd else 1.0))

    payload: Dict[str, Any] = {
        "text": prepared,
        "model_id": model,
        "voice_settings": voice_settings,
    }
    # Seed fixo = geracao mais repetivel (mesmo timbre entre frases)
    seed = tune.get("seed")
    if seed is not None:
        try:
            payload["seed"] = int(seed) & 0xFFFFFFFF
        except (TypeError, ValueError):
            pass
    else:
        payload["seed"] = 7001  # ancora 0701 — consistencia entre falas

    headers = {
        "xi-api-key": key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }

    async def _synthesize(vid: str) -> bytes:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{vid}"
        last_err: Optional[Exception] = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=45.0) as client:
                    resp = await client.post(url, json=payload, headers=headers)
                    if resp.status_code == 429:
                        detail = ""
                        try:
                            detail = resp.text[:200]
                        except Exception:
                            pass
                        wait_s = 0.8 * (attempt + 1)
                        print(f"[eleven] 429 concurrent — retry {attempt + 1}/3 em {wait_s:.1f}s")
                        await asyncio.sleep(wait_s)
                        last_err = RuntimeError(f"ElevenLabs 429: {detail}")
                        continue
                    if resp.status_code != 200:
                        detail = ""
                        try:
                            detail = resp.text[:300]
                        except Exception:
                            pass
                        raise RuntimeError(f"ElevenLabs {resp.status_code}: {detail}")
                    return _normalize_mp3(resp.content)
            except RuntimeError:
                raise
            except Exception as e:
                last_err = e
                await asyncio.sleep(0.4 * (attempt + 1))
        if last_err:
            raise last_err
        raise RuntimeError("ElevenLabs falhou sem detalhe")

    lock = _get_eleven_lock()
    async with lock:
        try:
            return await _synthesize(voice)
        except RuntimeError as e:
            msg = str(e)
            if fallback_voice and fallback_voice != voice and (
                "ivc_not_permitted" in msg or "subscription_required" in msg
            ):
                print(
                    "[eleven] clone Thomas bloqueado no plano (Instant Voice Cloning). "
                    "Usando voz ElevenLabs PT-BR — nao cai no Antonio."
                )
                return await _synthesize(fallback_voice)
            raise