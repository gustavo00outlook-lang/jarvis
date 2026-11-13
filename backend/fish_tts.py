"""
Fish Audio TTS — Voz Thomas/JARVIS (briefing Malibu + trechos Thomas do voice_sample)
NUNCA usar trechos com voz humana do Gustavo.
"""
import asyncio
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import httpx

try:
    import ormsgpack
except ImportError:
    ormsgpack = None  # type: ignore

FISH_TTS_URL = "https://api.fish.audio/v1/tts"
_VOICE_STORE = str(Path.home() / '.hermes' / 'jarvis_voice.json')
_ASSETS = Path(__file__).resolve().parent / "assets"

# Thomas puro — briefing Malibu (whisper transcript exato)
_0701_VOCAL = _ASSETS / "jarvis-0701-vocal.mp3"
_OFFICIAL_SAMPLE = _ASSETS / "jarvis-verdadeiro-sample.mp3"
_OFFICIAL_TRANSCRIPT = (
    "Bom dia, são 7 da manhã e em Malibu 22 graus. "
    "O tempo está no lado, mas o mar apresenta boa expondições para o Sul. "
    "A Maria alta será 10.52."
)

# Thomas no voice_sample (26-42s + 65-101s) — SEM voz humana
_THOMAS_EXTRACT = _ASSETS / "thomas-from-voice_sample.mp3"
_THOMAS_TRANSCRIPT = (
    "Entendo, perfeitamente, senhor. "
    "A viabilidade depende principalmente do tipo de micro-camera utilizada e da integração como sistema. "
    "É um projeto fascinante chefe. "
    "A viabilidade reside principalmente no tipo de micro-camera e na integração. "
    "Podemos iniciar uma pesquisa de mercado juntos se desejar?"
)

_ENV_PATHS = [
    str(Path.home() / '.hermes' / '.env'),
    str(Path.home() / '.hermes' / 'fish.txt'),
    str(Path.home() / '.hermes' / 'fish_team.json'),
]

FISH_MODEL = os.getenv("FISH_TTS_MODEL", "s2-pro")

_fish_client: Optional[httpx.AsyncClient] = None
_tts_cache: dict[str, bytes] = {}
_TTS_CACHE_MAX = 32


def _get_fish_client() -> httpx.AsyncClient:
    global _fish_client
    if _fish_client is None or _fish_client.is_closed:
        _fish_client = httpx.AsyncClient(
            timeout=90,
            limits=httpx.Limits(max_keepalive_connections=4, max_connections=8),
        )
    return _fish_client


def _tts_cache_key(text: str, speed: float, rid: str) -> str:
    digest = hashlib.md5(f"{rid}:{speed}:{text}".encode("utf-8")).hexdigest()
    return digest


def get_jarvis_reference_id() -> Optional[str]:
    try:
        raw = Path(_VOICE_STORE).read_text(encoding="utf-8-sig")
        return json.loads(raw).get("fish_reference_id") or None
    except Exception:
        return None


def set_jarvis_reference_id(rid: str) -> dict:
    """Define o modelo Fish ativo (reference_id). Faz backup do anterior."""
    rid = (rid or "").strip()
    if not rid:
        raise RuntimeError("reference_id vazio")
    try:
        data = json.load(open(_VOICE_STORE, encoding="utf-8"))
    except Exception:
        data = {}
    old = data.get("fish_reference_id")
    if old and old != rid:
        data["fish_reference_id_backup"] = old
    data["fish_reference_id"] = rid
    os.makedirs(os.path.dirname(_VOICE_STORE), exist_ok=True)
    json.dump(data, open(_VOICE_STORE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return {"fish_reference_id": rid, "backup": old}


def fish_configured() -> bool:
    return bool(_get_key()) and bool(get_jarvis_reference_id())


def _get_team_id() -> Optional[str]:
    tid = os.getenv("FISH_TEAM_ID", "").strip()
    if tid:
        return tid
    for path in _ENV_PATHS:
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            m = re.search(r"FISH_TEAM_ID=['\"]?([^'\"\r\n]+)", content)
            if m:
                tid = m.group(1).strip()
                os.environ["FISH_TEAM_ID"] = tid
                return tid
            if path.endswith(".json"):
                data = json.load(open(path, encoding="utf-8"))
                tid = (data.get("team_id") or "").strip()
                if tid:
                    os.environ["FISH_TEAM_ID"] = tid
                    return tid
        except Exception:
            continue
    return None


async def _wallet_credit(scope: str = "auto") -> Optional[float]:
    key = _get_key()
    if not key:
        return None
    team_id = _get_team_id()

    async def _fetch(tid: Optional[str]) -> Optional[float]:
        params = {"team_id": tid} if tid else None
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    "https://api.fish.audio/wallet/self/api-credit",
                    headers={"Authorization": f"Bearer {key}"},
                    params=params,
                )
                if r.status_code != 200:
                    return None
                return float(r.json().get("credit", 0))
        except Exception:
            return None

    if scope == "personal":
        return await _fetch(None)
    if scope == "team":
        return await _fetch(team_id) if team_id else None

    personal = await _fetch(None)
    if team_id:
        team = await _fetch(team_id)
        if team is not None and team > 0:
            return team
    return personal


async def get_fish_api_credit() -> Optional[float]:
    return await _wallet_credit("auto")


async def get_fish_wallet_status() -> dict:
    team_id = _get_team_id()
    personal = await _wallet_credit("personal")
    team = await _wallet_credit("team") if team_id else None
    active = team if team_id and team is not None and team > 0 else personal
    return {
        "team_id": team_id,
        "personal_credit_usd": personal,
        "team_credit_usd": team,
        "active_credit_usd": active,
        "uses_team_wallet": bool(team_id and team is not None and team > 0),
    }


_credit_cache: dict = {"at": 0.0, "ok": True}


async def fish_has_api_credit(min_usd: float = 0.001) -> bool:
    import time
    now = time.time()
    if now - _credit_cache["at"] < 180:
        return bool(_credit_cache["ok"])
    status = await get_fish_wallet_status()
    bal = status.get("active_credit_usd")
    ok = bal is not None and bal >= min_usd
    _credit_cache["at"] = now
    _credit_cache["ok"] = ok
    return ok


def _get_key() -> str:
    key = os.getenv("FISH_API_KEY", "")
    if key:
        return key
    for path in _ENV_PATHS:
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            m = re.search(r"FISH_API_KEY=['\"]?([^'\"\r\n]+)", content)
            if m:
                key = m.group(1).strip()
                os.environ["FISH_API_KEY"] = key
                return key
        except Exception:
            continue
    return ""


def _reference_samples() -> list[tuple[Path, str]]:
    """Referência pt-dubbed no infer — ancora timbre ao 0701.WAV_pt_dubbed."""
    for name in (
        "jarvis-0701-pt-dubbed-from10s.mp3",
        "jarvis-0701-pt-dubbed-master.mp3",
        "jarvis-0701-capcut-master.mp3",
    ):
        master = _ASSETS / name
        if master.is_file() and master.stat().st_size > 50_000:
            return [
                (
                    master,
                    "Ola senhor. Sistemas operacionais e prontos para suas ordens.",
                )
            ]
    return []


def _fish_tuning() -> dict:
    """Parâmetros calibrados — presença próxima, sem abafamento."""
    try:
        from voice_prefs import get_voice_config
        cfg = get_voice_config()
        if cfg.get("engine") == "fish" or cfg.get("voice_id") == "thomas":
            return cfg
    except Exception:
        pass
    return {
        "speed": 1.0,
        "volume": 0,
        "temperature": 0.38,
        "top_p": 0.52,
        "mp3_bitrate": 192,
        "normalize": True,
        "latency": "balanced",
    }


def _build_payload(text: str, speed: float, *, use_references: bool, chunk_length: int = 300) -> dict:
    cleaned = _clean(text)
    tune = _fish_tuning()
    n = len(cleaned)
    if n < 60:
        chunk_length = min(chunk_length, 100)
    elif n < 140:
        chunk_length = min(chunk_length, 180)
    payload: dict = {
        "text": cleaned,
        "chunk_length": chunk_length,
        "format": "mp3",
        "mp3_bitrate": min(192, max(64, int(tune.get("mp3_bitrate") or 192))),
        "sample_rate": 44100,
        "normalize": bool(tune.get("normalize", True)),
        "latency": str(tune.get("latency") or "normal"),
        "prosody": {
            "speed": max(0.5, min(2.0, speed)),
            "volume": int(tune.get("volume") if tune.get("volume") is not None else 0),
        },
        "temperature": float(tune.get("temperature") or 0.38),
        "top_p": float(tune.get("top_p") or 0.52),
        "repetition_penalty": float(tune.get("repetition_penalty") or 1.06),
        "min_chunk_length": 16,
        "condition_on_previous_chunks": True,
        "early_stop_threshold": 0.92,
    }
    if use_references and ormsgpack is not None:
        refs = []
        for path, transcript in _reference_samples():
            refs.append({"audio": path.read_bytes(), "text": transcript})
        if refs:
            payload["references"] = refs
            return payload
    rid = get_jarvis_reference_id()
    if not rid:
        raise RuntimeError("Voz Thomas não clonada. Rode: python backend/clone_fish_voice.py")
    payload["reference_id"] = rid
    return payload


async def _request_fish(payload: dict, api_key: str) -> bytes:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "model": FISH_MODEL,
    }
    use_msgpack = "references" in payload and ormsgpack is not None
    if use_msgpack:
        headers["Content-Type"] = "application/msgpack"
        body = ormsgpack.packb(payload)
    else:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")

    client = _get_fish_client()
    r = await client.post(FISH_TTS_URL, headers=headers, content=body)
    if r.status_code == 402:
        raise RuntimeError(
            "Fish Audio: crédito API insuficiente. "
            "Recarregue em https://fish.audio/pt/app/developers"
        )
    if r.status_code != 200:
        raise RuntimeError(f"Fish Audio erro {r.status_code}: {r.text[:200]}")
    return r.content


async def speak_fish(
    text: str,
    *,
    voice_id: Optional[str] = None,
    play_system: bool = True,
    chunk_length: int = 240,
    speed: float = 1.0,
) -> bytes:
    if not text or not text.strip():
        return b""

    api_key = _get_key()
    if not api_key:
        raise RuntimeError("FISH_API_KEY não configurada")

    rid = voice_id or get_jarvis_reference_id()
    if not rid:
        raise RuntimeError("Voz Thomas não clonada. Rode: python backend/clone_fish_voice.py")

    cleaned = _clean(text)
    cache_key = _tts_cache_key(cleaned, speed, rid)
    cached = _tts_cache.get(cache_key)
    if cached:
        if play_system and cached:
            asyncio.create_task(_play(cached))
        return cached

    tune = _fish_tuning()
    chunk_length = int(tune.get("chunk_length") or chunk_length)
    n = len(cleaned)
    if n < 80:
        chunk_length = min(chunk_length, 140)
    elif n < 200:
        chunk_length = min(chunk_length, 200)
    elif n < 400:
        chunk_length = min(chunk_length, 260)

    # Clone único (reference_id) — sem zero-shot multi-ref (evita mistura + reverb distante)
    payload = _build_payload(text, speed, use_references=False, chunk_length=chunk_length)
    payload["reference_id"] = rid
    audio = await _request_fish(payload, api_key)

    if audio and len(cleaned) <= 420:
        if len(_tts_cache) >= _TTS_CACHE_MAX:
            _tts_cache.pop(next(iter(_tts_cache)))
        _tts_cache[cache_key] = audio

    if play_system and audio:
        asyncio.create_task(_play(audio))

    return audio


def _clean(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"#{1,6}\s", "", text)
    return text.strip()


async def _play(audio: bytes) -> None:
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(audio)
        tmp = f.name
    # Duração dinâmica — evita cortar frases longas ou esperar 20s à toa
    est_sec = max(2, min(90, int(len(audio) / 9000) + 2))
    ps = (
        "Add-Type -AssemblyName presentationCore; "
        f"$m = New-Object System.Windows.Media.MediaPlayer; "
        f"$m.Open([Uri]'{tmp}'); $m.Play(); "
        "$deadline = (Get-Date).AddSeconds(45); "
        "do { Start-Sleep -Milliseconds 80; "
        "if ($m.NaturalDuration.HasTimeSpan) { break } "
        "} while ((Get-Date) -lt $deadline); "
        "if ($m.NaturalDuration.HasTimeSpan) { "
        "$s = [math]::Max(1.5, $m.NaturalDuration.TimeSpan.TotalSeconds + 0.35); "
        "Start-Sleep -Seconds $s } "
        f"else {{ Start-Sleep -Seconds {est_sec} }}; $m.Stop()"
    )
    try:
        await asyncio.create_subprocess_exec(
            "powershell", "-NoProfile", "-NonInteractive", "-c",
            ps,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        print(f"[JARVIS TTS] Fish {FISH_MODEL} Thomas: {len(audio)} bytes")
    except Exception as e:
        try:
            subprocess.Popen(["cmd", "/c", "start", "/min", "", "wmplayer", tmp])
        except Exception as e2:
            print(f"[warn] play falhou: {e} | {e2}")