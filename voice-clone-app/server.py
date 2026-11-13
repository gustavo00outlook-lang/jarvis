"""
API local de clone de voz — porta 8787
Usado pelo JARVIS (/api/speak/local) e pelo app Gradio.

  POST /speak  { "text": "...", "voice_id": "thomas-0701", "prefer": "xtts" }
  GET  /status
  POST /register { "voice_id": "minha-voz", "path": "C:\\audio.wav" }
  POST /activate { "voice_id": "thomas-0701" }
"""
from __future__ import annotations

import sys
from pathlib import Path

# permite import engine a partir de qualquer cwd
sys.path.insert(0, str(Path(__file__).resolve().parent))

import os
import threading

from fastapi import Body, FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

import engine as vc

app = FastAPI(title="JARVIS Voice Clone", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
@app.get("/status")
def status():
    st = vc.engine_status()
    st["ok"] = bool(st.get("reference_ok"))
    return st


@app.get("/voices")
def voices():
    return {"voices": vc.list_voices(), "active": vc.get_active_voice()}


@app.post("/activate")
def activate(payload: dict = Body(...)):
    vid = str(payload.get("voice_id") or "").strip()
    info = vc.set_active_voice(vid)
    return {"ok": True, "active": vid, "info": info}


@app.post("/register")
def register(payload: dict = Body(...)):
    vid = str(payload.get("voice_id") or "custom").strip()
    path = payload.get("path") or payload.get("source")
    if not path:
        return {"ok": False, "error": "path obrigatório"}
    start = float(payload.get("start_s") or 1.0)
    dur = float(payload.get("duration_s") or 14.0)
    ref = vc.register_voice(vid, path, start_s=start, duration_s=dur)
    return {"ok": True, "voice_id": vid, "reference": str(ref)}


@app.post("/speak")
async def speak(payload: dict = Body(...)):
    text = str(payload.get("text") or "").strip()
    if not text:
        return Response(b"", media_type="audio/mpeg")
    voice_id = payload.get("voice_id") or "thomas-0701"
    prefer = str(payload.get("prefer") or os.getenv("JARVIS_LOCAL_CLONE_PREFER") or "xtts")
    as_mp3 = bool(payload.get("mp3", False))
    hq = bool(payload.get("hq", False))
    try:
        audio, eng = await vc.speak_async(
            text, voice_id=voice_id, prefer=prefer, as_mp3=as_mp3, hq=hq
        )
    except Exception as e:
        return Response(
            f"clone_error: {e}".encode("utf-8"),
            status_code=503,
            media_type="text/plain",
        )
    if not audio or len(audio) < 100:
        return Response(b"empty_audio", status_code=503, media_type="text/plain")
    media = "audio/mpeg" if as_mp3 and audio[:4] != b"RIFF" else "audio/wav"
    if audio[:4] == b"RIFF":
        media = "audio/wav"
    return Response(
        audio,
        media_type=media,
        headers={
            "X-TTS-Engine": f"local-clone-{eng}",
            "X-Jarvis-Voice-Id": str(voice_id or vc.get_active_voice()),
            "Cache-Control": "no-store",
        },
    )


@app.on_event("startup")
def _startup_warmup() -> None:
    """Carrega XTTS em thread — /status continua respondendo."""

    def _bg() -> None:
        try:
            print("[voice-clone] warmup XTTS master.wav…")
            vc._get_xtts()
            audio, eng = vc.speak_sync("Olá, senhor.", prefer="xtts", as_mp3=False)
            print(f"[voice-clone] warmup OK engine={eng} bytes={len(audio)}")
        except Exception as e:
            print(f"[voice-clone] warmup falhou (1º speak carregará): {e}")

    threading.Thread(target=_bg, daemon=True, name="xtts-warmup").start()


if __name__ == "__main__":
    import os
    import uvicorn

    os.environ.setdefault("COQUI_TOS_AGREED", "1")
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

    print("[voice-clone] http://127.0.0.1:8787  status=/status speak=POST /speak")
    print("[voice-clone] fonte: voices/thomas-0701/master.wav (XTTS)")
    uvicorn.run(app, host="127.0.0.1", port=8787, log_level="info", workers=1)
