"""STT JARVIS — transcrição de áudio (fallback quando Web Speech API não existe no Tauri)."""

from __future__ import annotations

import base64
from typing import Optional

from xai_client import get_client, get_fast_model


def _webm_to_wav_bytes(data: bytes) -> Optional[bytes]:
    """Converte webm/opus para wav PCM 16kHz mono via ffmpeg, se disponível."""
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        inp = Path(tmp) / "in.webm"
        out = Path(tmp) / "out.wav"
        inp.write_bytes(data)
        try:
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-i",
                    str(inp),
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    "-f",
                    "wav",
                    str(out),
                ],
                capture_output=True,
                timeout=25,
                check=True,
            )
            if out.exists() and out.stat().st_size > 44:
                return out.read_bytes()
        except Exception:
            return None
    return None


async def _grok_transcribe_wav(wav_bytes: bytes) -> Optional[str]:
    client = get_client()
    if not client:
        return None
    b64 = base64.b64encode(wav_bytes).decode("ascii")
    try:
        resp = await client.chat.completions.create(
            model=get_fast_model(),
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Transcreva o áudio em português do Brasil. "
                                "Retorne APENAS o texto falado, sem aspas nem comentários."
                            ),
                        },
                        {
                            "type": "input_audio",
                            "input_audio": {"data": b64, "format": "wav"},
                        },
                    ],
                }
            ],
            max_tokens=320,
            temperature=0.1,
        )
        text = (resp.choices[0].message.content or "").strip()
        if text and len(text) > 1:
            return text
    except Exception as e:
        print(f"[stt] grok audio: {e}")
    return None


async def transcribe_audio_blob(data: bytes, content_type: str = "") -> str:
    """Transcreve blob de áudio (webm/wav) para texto pt-BR."""
    if not data or len(data) < 200:
        return ""

    ct = (content_type or "").lower()
    wav = data if "wav" in ct else _webm_to_wav_bytes(data)
    if not wav:
        # Sem ffmpeg: tenta grok com webm direto
        b64 = base64.b64encode(data).decode("ascii")
        client = get_client()
        if client:
            try:
                resp = await client.chat.completions.create(
                    model=get_fast_model(),
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Transcreva em pt-BR. Só o texto falado.",
                                },
                                {
                                    "type": "input_audio",
                                    "input_audio": {"data": b64, "format": "webm"},
                                },
                            ],
                        }
                    ],
                    max_tokens=320,
                    temperature=0.1,
                )
                text = (resp.choices[0].message.content or "").strip()
                if text:
                    return text
            except Exception as e:
                print(f"[stt] grok webm: {e}")

    if wav:
        text = await _grok_transcribe_wav(wav)
        if text:
            return text
        text = await _google_sr_transcribe_wav(wav)
        if text:
            return text

    return ""


async def _google_sr_transcribe_wav(wav_bytes: bytes) -> Optional[str]:
    """Fallback STT via SpeechRecognition + Google (pt-BR), sem API key."""
    import asyncio
    import io

    try:
        import speech_recognition as sr
    except ImportError:
        return None

    def _run() -> Optional[str]:
        try:
            recognizer = sr.Recognizer()
            with sr.AudioFile(io.BytesIO(wav_bytes)) as source:
                audio = recognizer.record(source)
            return recognizer.recognize_google(audio, language="pt-BR").strip()
        except Exception:
            return None

    return await asyncio.to_thread(_run)