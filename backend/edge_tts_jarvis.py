"""
Edge TTS — Voz JARVIS pt-BR
Usa Microsoft Antonio Neural (gratuito, altíssima qualidade, sem API key).
Tom: calmo, profundo, autoritário — exatamente como o JARVIS do Homem de Ferro.
"""
import asyncio
import os
import subprocess
import tempfile
from typing import Optional

import edge_tts

# Voz masculina pt-BR mais próxima do JARVIS
JARVIS_VOICE = "pt-BR-AntonioNeural"

# Rate e pitch — JARVIS brasileiro: calmo, grave, autoritário (Antonio Neural)
JARVIS_RATE  = "+2%"    # Levemente mais fluido em pt-BR
JARVIS_PITCH = "-4Hz"   # Grave sutil — português natural


async def speak_edge(
    text: str,
    *,
    voice: str = JARVIS_VOICE,
    rate: str = JARVIS_RATE,
    pitch: str = JARVIS_PITCH,
    play_system: bool = True,
) -> bytes:
    """Gera áudio MP3 com Edge TTS e opcionalmente toca nos speakers do sistema."""
    if not text or not text.strip():
        return b""

    cleaned = _clean_text(text)

    comm = edge_tts.Communicate(cleaned, voice, rate=rate, pitch=pitch)

    audio_chunks = []
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            audio_chunks.append(chunk["data"])

    audio = b"".join(audio_chunks)

    if play_system and audio:
        asyncio.create_task(_play_system(audio))

    return audio


def _clean_text(text: str) -> str:
    """Remove markdown e caracteres que atrapalham o TTS."""
    import re
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'`(.+?)`', r'\1', text)
    text = re.sub(r'#{1,6}\s', '', text)
    text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)
    return text.strip()


async def _play_system(audio: bytes) -> None:
    """Toca o áudio pelos speakers do Windows."""
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(audio)
        tmp = f.name
    try:
        proc = await asyncio.create_subprocess_exec(
            "powershell", "-NoProfile", "-NonInteractive", "-c",
            f"Add-Type -AssemblyName presentationCore; "
            f"$m = New-Object System.Windows.Media.MediaPlayer; "
            f"$m.Open([Uri]'{tmp}'); $m.Play(); "
            f"Start-Sleep -s 20; $m.Stop()",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        print(f"[JARVIS TTS] Antonio Neural: {len(audio)} bytes")
    except Exception as e:
        # Fallback: Windows Media Player
        try:
            subprocess.Popen(["cmd", "/c", "start", "/min", "", "wmplayer", tmp])
        except Exception as e2:
            print(f"[warn] play_system falhou: {e} | {e2}")
