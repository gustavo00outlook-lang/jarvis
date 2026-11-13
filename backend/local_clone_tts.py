"""TTS via app local de clone de voz (voice-clone-app :8787).

Sem dependência de Eleven/Fish/xAI — usa sample 0701 local.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Optional, Tuple

import httpx

DEFAULT_URL = "http://127.0.0.1:8787"


def clone_base_url() -> str:
    return (os.getenv("JARVIS_LOCAL_CLONE_URL") or DEFAULT_URL).rstrip("/")


def local_voice_id() -> str:
    return (os.getenv("JARVIS_LOCAL_VOICE_ID") or "thomas-0701").strip()


def local_clone_configured() -> bool:
    """True se o servidor de clone responder /status com reference_ok."""
    try:
        r = httpx.get(f"{clone_base_url()}/status", timeout=2.5)
        if r.status_code != 200:
            return False
        data = r.json()
        return bool(data.get("ok") or data.get("reference_ok"))
    except Exception:
        return False


async def local_clone_status() -> dict:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{clone_base_url()}/status")
            if r.status_code == 200:
                return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": False}


def play_on_pc(audio: bytes) -> None:
    """Toca a voz Thomas nos alto-falantes do Windows (não depende do Edge)."""
    raw = (os.getenv("JARVIS_PLAY_SYSTEM") or "1").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return
    if not audio or len(audio) < 100:
        return

    def _run() -> None:
        try:
            tmp = Path(tempfile.gettempdir())
            is_wav = audio[:4] == b"RIFF"
            src = tmp / ("jarvis-thomas.wav" if is_wav else "jarvis-thomas.mp3")
            src.write_bytes(audio)
            ffplay = shutil.which("ffplay") or next(
                (
                    p
                    for p in (
                        str(Path.home() / 'AppData' / 'Local' / 'Microsoft' / 'WinGet' / 'Packages' / 'Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe' / 'ffmpeg-8.1.1-full_build' / 'bin' / 'ffplay.exe'),
                        r"C:\ffmpeg\bin\ffplay.exe",
                    )
                    if Path(p).is_file()
                ),
                None,
            )
            if ffplay:
                subprocess.Popen(
                    [ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet", "-af", "volume=1.0", str(src)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return
            wav = tmp / "jarvis-thomas-play.wav"
            if is_wav:
                wav.write_bytes(audio)
            else:
                ff = shutil.which("ffmpeg") or next(
                    (
                        p
                        for p in (
                            str(Path.home() / 'AppData' / 'Local' / 'Microsoft' / 'WinGet' / 'Packages' / 'Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe' / 'ffmpeg-8.1.1-full_build' / 'bin' / 'ffmpeg.exe'),
                            r"C:\ffmpeg\bin\ffmpeg.exe",
                        )
                        if Path(p).is_file()
                    ),
                    None,
                )
                if not ff:
                    os.startfile(str(src))  # type: ignore[attr-defined]
                    return
                subprocess.run(
                    [ff, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), str(wav)],
                    check=False,
                    timeout=20,
                )
            if wav.exists() and wav.stat().st_size > 200:
                import winsound

                winsound.PlaySound(str(wav), winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception as e:
            print(f"[local-clone] play_on_pc: {e}")

    threading.Thread(target=_run, daemon=True, name="jarvis-thomas-play").start()


async def speak_local_clone(
    text: str,
    *,
    voice_id: Optional[str] = None,
    prefer: str = "xtts",
    hq: bool = False,
    play_system: bool = False,
) -> Tuple[bytes, str]:
    """Sintetiza via voice-clone-app. Retorna (audio_mp3_or_wav, engine_header)."""
    payload = {
        "text": text,
        "voice_id": voice_id or local_voice_id(),
        "prefer": prefer or os.getenv("JARVIS_LOCAL_CLONE_PREFER") or "xtts",
        "mp3": False,
        "hq": hq,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(f"{clone_base_url()}/speak", json=payload)
        if r.status_code != 200:
            detail = ""
            try:
                detail = r.text[:240]
            except Exception:
                pass
            raise RuntimeError(f"local_clone {r.status_code}: {detail}")
        eng = r.headers.get("x-tts-engine") or "local-clone"
        # O navegador controla a reprodução; pré-buscas não devem falar no PC.
        if play_system:
            play_on_pc(r.content)
        return r.content, eng
