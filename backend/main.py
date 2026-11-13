# -*- coding: utf-8 -*-
"""
JARVIS Pro Backend — FastAPI.

Endpoints principais:
  POST /api/jarvis/chat     - agente unificado: conversa + executa tools (function calling Grok)
  POST /api/jarvis/confirm  - confirma ação de risco pendente e retoma o agente
  POST /api/jarvis/cancel   - cancela ação pendente
  WS   /ws                  - eventos em tempo real (estado, transcript, tools, captions)

Legado (fases 1-5, ainda funcionais):
  POST /api/hermes/reason, /api/hermes/action, /api/confirm-action,
  /api/tools/search, /api/speak/xai, /api/speak/edge, /api/conversation/reset
"""
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from xai_client import (
    apply_probe_exhaustion,
    check_ollama_available,
    ensure_key as _ensure_xai_key,
    get_client,
    get_last_chat_model,
    get_last_used_provider,
    get_model,
    get_provider,
    google_key_looks_valid,
    is_provider_skipped,
    probe_llm_providers,
    provider_chain,
    readiness_label,
    resolve_model,
    warn_google_key_format,
)
from ollama_warmup import warmup_ollama
_ensure_xai_key()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Body, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from xai_reasoning import stream_deep_reasoning, ReasoningEffort
from xai_structured_action import get_structured_action
from intent_resolver import resolve_fast_action
from conversation_state import (
    clear_conversation, append_message, get_recent_context,
    extract_and_learn_prefs_from_text, get_user_prefs,
    record_successful_command, get_adaptive_context_for_actions,
    get_previous_successful_commands, get_ui_history,
    purge_degraded_history,
)
import jarvis_memory
from xai_tools import search_with_tools
from xai_tts import speak_with_xai, get_cloned_voice_id, ensure_jarvis_voice
from edge_tts_jarvis import speak_edge

try:
    from fish_tts import speak_fish
    _FISH_AVAILABLE = True
except ImportError:
    _FISH_AVAILABLE = False
from structured_to_legacy import execute_structured_action
from action_schema import ActionPlan
from pending_state import load_pending, save_pending, clear_pending
from jarvis_agent import (
    run_agent_turn,
    continue_after_confirmation,
    graceful_error_message,
    JARVIS_CAPABILITIES,
)

import actions
import web_browser

os.environ.setdefault("JARVIS_VOICE_PRIMARY", "local")
os.environ.setdefault("JARVIS_PLAY_SYSTEM", "1")
os.environ.setdefault("JARVIS_LOCAL_CLONE_PREFER", "xtts")
os.environ.setdefault("JARVIS_LLM_PROVIDER", "ollama")

app = FastAPI(title="JARVIS Pro Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def _blindagem_erros(request, exc):
    """Nao derruba o processo: devolve erro em pt-BR e segue."""
    from fastapi import HTTPException
    from fastapi.responses import JSONResponse
    if isinstance(exc, HTTPException):
        raise exc
    print(f"[blindagem] {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"ok": False, "error": "Falha interna. Tente de novo, senhor.", "path": str(request.url.path)},
    )


@app.get("/api/heal")
async def heal_status():
    """Status rapido para o watchdog — nao reinicia daqui (PowerShell faz o restart)."""
    clone = False
    try:
        import httpx
        async with httpx.AsyncClient(timeout=2.5) as client:
            r = await client.get("http://127.0.0.1:8787/status")
            clone = r.status_code == 200
    except Exception:
        clone = False
    return {
        "ok": True,
        "backend": True,
        "clone": clone,
        "voice": os.getenv("JARVIS_VOICE_PRIMARY", "local"),
        "play_system": os.getenv("JARVIS_PLAY_SYSTEM", "1"),
    }


@app.middleware("http")
async def _private_network_cors(request, call_next):
    """WebView2 (Tauri) exige este header ao chamar 127.0.0.1:8000 de localhost:3000."""
    response = await call_next(request)
    response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response

_clients: set[WebSocket] = set()


async def _ollama_keepalive_loop() -> None:
    """Mantém hermes3 carregado entre turnos longos."""
    from ollama_warmup import _warmup_enabled, warmup_ollama

    interval_min = int(os.getenv("JARVIS_OLLAMA_KEEPALIVE_MIN", "18") or "18")
    while True:
        await asyncio.sleep(max(5, interval_min) * 60)
        if _warmup_enabled():
            await warmup_ollama()


async def _boot_probe_llm():
    """Detecta cota esgotada no boot — evita retentar xAI a cada mensagem."""
    try:
        probe = await probe_llm_providers(force=True)
        apply_probe_exhaustion(probe)
        primary = get_provider()
        chain = provider_chain()
        print(f"[llm] boot probe — primário={primary} chain={chain}")
    except Exception as e:
        print(f"[llm] boot probe skip: {e}")


async def _load_orchestrator_background() -> None:
    """Carrega 166 agentes em thread — não bloqueia o event loop no boot."""
    try:
        from agent_orchestrator import get_orchestrator

        await asyncio.to_thread(get_orchestrator().ensure_loaded)
        n = len(get_orchestrator()._agents)
        print(f"[orchestrator] {n} agentes AIOS+Xquads carregados (lazy)")
    except Exception as e:
        print(f"[orchestrator] lazy load skip: {e}")


async def _boot_verify_capabilities() -> None:
    """Garante que pesquisa web gratuita responde — JARVIS nunca fica 'cego'."""
    await asyncio.sleep(2.5)
    try:
        from free_web_search import free_web_search

        r = await asyncio.wait_for(free_web_search("JARVIS teste busca web"), timeout=25.0)
        n = len(r.get("hits") or [])
        print(f"[boot] pesquisa web OK sources={r.get('tools_used')} hits={n}")
    except Exception as e:
        print(f"[boot] pesquisa web aviso: {e} — painel Google ainda disponível")
    try:
        from eleven_tts import eleven_configured, eleven_voice_id

        if eleven_configured():
            print(f"[boot] voz ElevenLabs OK id={eleven_voice_id()[:10]}…")
        else:
            print("[boot] AVISO: ElevenLabs não configurado — Edge fallback")
    except Exception as e:
        print(f"[boot] voz check: {e}")


@app.on_event("startup")
async def _boot_tasks():
    """Resolve LLM (Gemini/Grok/Ollama), voz e warmup (idempotentes)."""
    removed = purge_degraded_history()
    if removed:
        print(f"[memory] histórico: {removed} turno(s) degradado(s) removido(s)")
    warn_google_key_format()
    if get_provider() != "ollama":
        asyncio.create_task(_boot_probe_llm())
    else:
        print("[llm] modo Ollama-only — boot probe nuvem desligado")
    asyncio.create_task(resolve_model())
    asyncio.create_task(warmup_ollama())
    asyncio.create_task(_ollama_keepalive_loop())
    orch_on = os.getenv("JARVIS_AGENT_ORCHESTRATOR", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    if orch_on:
        lazy = os.getenv("JARVIS_ORCHESTRATOR_LAZY", "1").strip().lower() not in (
            "0",
            "false",
            "no",
            "off",
        )
        if lazy:
            print("[orchestrator] lazy-load em background — boot rapido")
            asyncio.create_task(_load_orchestrator_background())
        else:
            try:
                from agent_orchestrator import get_orchestrator

                get_orchestrator().ensure_loaded()
                n = len(get_orchestrator()._agents)
                print(f"[orchestrator] {n} agentes AIOS+Xquads carregados (sync)")
            except Exception as e:
                print(f"[orchestrator] boot skip: {e}")
    else:
        print("[orchestrator] desligado (JARVIS_AGENT_ORCHESTRATOR=0)")
    # Voz principal = ElevenLabs Thomas; clone xAI só se ainda útil (sem cota = skip)
    try:
        from xai_client import is_provider_skipped

        if not is_provider_skipped("xai"):
            sample = Path(__file__).parent / "assets" / "jarvis-verdadeiro-sample.mp3"
            asyncio.create_task(ensure_jarvis_voice(str(sample)))
        else:
            print("[voice] xAI skip (cota) — ElevenLabs Thomas ativo")
    except Exception:
        sample = Path(__file__).parent / "assets" / "jarvis-verdadeiro-sample.mp3"
        asyncio.create_task(ensure_jarvis_voice(str(sample)))
    asyncio.create_task(web_browser.warm_up())
    asyncio.create_task(_boot_verify_capabilities())


@app.get("/")
async def root():
    return {
        "name": "JARVIS Pro Backend",
        "status": "online",
        "provider": get_provider(),
        "last_provider": get_last_used_provider(),
        "model": get_model(),
        "provider_chain": provider_chain(),
    }


JARVIS_BUILD = "2026-07-04-voz-0701-cowatch"


@app.get("/health/live")
async def health_live():
    """Ping instantâneo — polling UI sem bloquear em Ollama/probe."""
    return {
        "ok": True,
        "status": "online",
        "build": JARVIS_BUILD,
        "provider": get_provider(),
    }


@app.get("/health")
async def health(probe: bool = False):
    try:
        ollama_ok = await asyncio.wait_for(check_ollama_available(force=True), timeout=6.0)
    except asyncio.TimeoutError:
        ollama_ok = False
    last_p = get_last_used_provider() or get_provider()
    probe_data = None
    if probe:
        try:
            timeout = 8.0 if get_provider() == "ollama" else 35.0
            probe_data = await asyncio.wait_for(probe_llm_providers(), timeout=timeout)
        except asyncio.TimeoutError:
            probe_data = {"error": "probe_timeout", "hint": "backend ocupado ou API lenta"}
    if get_provider() == "ollama":
        ready = "OLLAMA_OK" if ollama_ok else "OLLAMA_OFFLINE"
    else:
        ready = readiness_label(probe_data)

    brain_note = None
    if ready == "FULL_GEMINI":
        brain_note = "Gemini ativo — co-assistir, tools e visão multimodal no máximo."
    elif ready == "FULL_XAI":
        brain_note = "xAI Grok ativo — tools e chat completos."
    elif ready == "PARTIAL_OLLAMA" or get_provider() == "ollama":
        brain_note = "Ollama hermes3 — modo local rapido (fast-paths, PC, painel, voz)."
    elif ready == "CONFIGURE_GOOGLE_KEY":
        brain_note = "Substitua GOOGLE_API_KEY por chave AIzaSy... em .env.local e reinicie."
    elif ready == "WAITING_API_CREDIT":
        brain_note = "Chave no formato certo mas API recusou — recarregue crédito/cota e rode probe."
    elif last_p == "ollama":
        brain_note = "Cérebro em Ollama local — Gemini/xAI indisponíveis ou sem cota."

    rec_status = ready
    if ready == "KEY_OK_PROBE_PENDING":
        rec_status = "RUN_PROBE"
    elif ready in ("FULL_GEMINI", "FULL_XAI"):
        rec_status = "OK"

    return {
        "ok": True,
        "status": "online",
        "ready": ready,
        "provider": get_provider(),
        "last_provider": get_last_used_provider(),
        "model": get_model(),
        "last_chat_model": get_last_chat_model(),
        "provider_chain": provider_chain(),
        "ollama_available": ollama_ok,
        "google_key_valid_format": google_key_looks_valid(),
        "xai_skipped": is_provider_skipped("xai"),
        "brain_note": brain_note,
        "api_probe": probe_data,
        "recommended_api": {
            "brain_primary": "google",
            "brain_key": "GOOGLE_API_KEY=AIzaSy... (aistudio.google.com/apikey)",
            "brain_mode": "JARVIS_LLM_PROVIDER=auto",
            "brain_fallback": "ollama hermes3",
            "brain_why": (
                "Gemini faz function-calling de todas as ~30 tools, pesquisa Google "
                "grounding, visão no co-assistir e Calango — melhor para 'fazer tudo'."
            ),
            "voice_primary": "eleven-thomas",
            "voice_fallback": "eleven-then-edge",
            "status": rec_status,
            "after_credit_steps": [
                "1. Cole GOOGLE_API_KEY=AIzaSy... em jarvis-pro/.env.local",
                "2. Reinicie backend (START_JARVIS.bat ou uvicorn)",
                "3. Rode: .\\scripts\\pronto-apos-credito.ps1",
            ],
        },
        "companion_features": {
            "cowatch": True,
            "watch_report": True,
            "calango_login": True,
            "capcut_assist": True,
            "humor_pegadinha": True,
        },
        "build": JARVIS_BUILD,
    }


# ============================================================
# WEBSOCKET
# ============================================================
@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    _clients.add(websocket)
    try:
        await websocket.send_json({"type": "state", "state": "idle"})
        while True:
            msg = await websocket.receive_text()
            try:
                data = json.loads(msg)
                if data.get("type") == "chat" and data.get("text"):
                    asyncio.create_task(jarvis_chat({"text": data["text"]}))
            except Exception:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(websocket)


async def broadcast(payload: dict):
    dead = []
    # Snapshot evita RuntimeError quando WS conecta/desconecta durante o loop.
    for c in list(_clients):
        try:
            await c.send_json(payload)
        except Exception:
            dead.append(c)
    for d in dead:
        _clients.discard(d)


@app.post("/api/broadcast")
async def http_broadcast(payload: dict = Body(...)):
    await broadcast(payload)
    return {"status": "ok"}


@app.get("/api/browse/preview")
async def browse_preview():
    """Frame atual do navegador headless — refresh ao vivo no painel."""
    import web_browser
    try:
        preview = await web_browser.get_preview()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    if not preview.get("url"):
        # Sem página real (about:blank/sessão morta) — painel deve fechar, não mostrar branco
        return {"ok": True, "empty": True}
    await broadcast({"type": "browser_preview", **preview})
    return {"ok": True, **preview}


@app.post("/api/browse/interact")
async def browse_interact(payload: dict = Body(...)):
    """Clique/rolagem direto no painel — opera o navegador headless e devolve o novo frame."""
    import web_browser
    action = (payload.get("action") or "click").lower()
    try:
        if action == "click":
            await web_browser.click_at(float(payload.get("x", 0.5)), float(payload.get("y", 0.5)))
        elif action == "scroll":
            await web_browser.scroll_by(int(payload.get("dy", 600)))
        elif action == "back":
            await web_browser.go_back()
        preview = await web_browser.get_preview()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    if preview.get("url"):
        await broadcast({"type": "browser_preview", **preview})
    return {"ok": True, "url": preview.get("url"), "title": preview.get("title")}


async def delayed_idle(seconds: float = 8.0):
    try:
        await asyncio.sleep(seconds)
        await broadcast({"type": "state", "state": "idle"})
    except Exception as e:
        print(f"[broadcast] delayed_idle: {e}")


# ============================================================
# AGENTE UNIFICADO — conversa + execução (function calling)
# ============================================================
@app.get("/api/jarvis/capabilities")
async def jarvis_capabilities():
    """O que o JARVIS pode fazer — UI e integrações."""
    from claude_brain import claude_brain_status
    from jarvis_agent import _refresh_capabilities_meta

    _refresh_capabilities_meta()
    return {
        "ok": True,
        "build": JARVIS_BUILD,
        "claude_brain": claude_brain_status(),
        **JARVIS_CAPABILITIES,
    }


@app.get("/api/jarvis/orchestration")
async def jarvis_orchestration():
    """Auditoria: pedidos do usuário, bloqueios, saúde live."""
    from jarvis_orchestration_report import build_report_async, save_to_obsidian

    report = await build_report_async()
    vault_path = ""
    try:
        vault_path = save_to_obsidian(report)
    except Exception:
        pass
    return {"ok": True, "vault_path": vault_path, **report}


@app.get("/api/jarvis/skills")
async def jarvis_skills():
    """Skills Grok/Cursor disponíveis ao orquestrador."""
    from jarvis_skills_registry import skills_status

    return {"ok": True, **skills_status()}


@app.get("/api/jarvis/ruflo")
async def jarvis_ruflo_status():
    """Status do bridge Ruflo (auto-ativação dev/swarm)."""
    from jarvis_ruflo_bridge import status_dict, wants_ruflo

    return {"ok": True, **status_dict(), "sample_triggers": wants_ruflo("melhore o codigo do jarvis")}


@app.get("/api/jarvis/agents")
async def jarvis_agents():
    """Orquestrador AIOS + Xquads — status e lista resumida."""
    from agent_orchestrator import get_orchestrator

    orch = get_orchestrator()
    st = orch.status_dict()
    agents = [
        {
            "id": a.id,
            "name": a.name,
            "squad": a.squad,
            "source": a.source,
            "title": a.title,
            "tier": a.tier,
        }
        for a in orch.list_agents(60)
    ]
    return {"ok": True, **st, "agents": agents}


@app.post("/api/jarvis/agents/suggest")
async def jarvis_agents_suggest(payload: dict = Body(...)):
    """Sugere ou compara agentes para um texto/pedido."""
    from agent_orchestrator import get_orchestrator

    text = (payload.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "text vazio"}
    orch = get_orchestrator()
    if orch.wants_comparison(text):
        mentioned = orch._find_mentioned_agents(text)
        reply = orch.format_comparison(text, mentioned)
        mode = "comparison"
    else:
        reply = orch.advisory_reply(text) or ""
        mode = "suggestion"
    ranked = orch.rank_agents(text, top=3)
    top = []
    for score, ag, reasons in ranked:
        top.append(
            {
                "id": ag.id,
                "name": ag.name,
                "squad": ag.squad,
                "score": score,
                "reasons": reasons,
            }
        )
    return {
        "ok": True,
        "mode": mode,
        "response": reply,
        "ranking": top,
    }


@app.get("/api/jarvis/history")
async def jarvis_history(limit: int = 10):
    """Últimas mensagens persistidas — restaura contexto ao reabrir o app."""
    hist = get_ui_history(limit)
    last_jarvis = next(
        (h.get("text", "") for h in reversed(hist) if h.get("role") == "jarvis"),
        "",
    )
    return {"history": hist, "last_jarvis": last_jarvis, "count": len(hist)}


@app.post("/api/jarvis/session/close")
async def jarvis_session_close():
    """Persiste sessão ao fechar o app — histórico não se perde."""
    import obsidian_notes
    hist = get_ui_history(16)
    if not hist:
        return {"ok": True, "saved": False}
    lines = []
    for h in hist:
        role = "Gustavo" if h.get("role") == "user" else "JARVIS"
        lines.append(f"- **{role}:** {h.get('text', '')[:400]}")
    body = (
        f"# Sessão JARVIS — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        + "\n".join(lines)
        + "\n\n#jarvis #sessao"
    )
    try:
        await asyncio.to_thread(
            obsidian_notes.save_or_update_note,
            f"Sessão JARVIS {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            body,
            "sessao",
            "jarvis, sessao",
        )
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "saved": True, "turns": len(hist)}


@app.post("/api/jarvis/stt")
async def jarvis_stt(audio: UploadFile = File(...)):
    """Transcrição de voz — fallback para app Tauri (Web Speech indisponível)."""
    import speech_stt

    data = await audio.read()
    ct = audio.content_type or ""
    text = await speech_stt.transcribe_audio_blob(data, ct)
    return {"ok": bool(text), "text": text or ""}


@app.post("/api/jarvis/chat")
async def jarvis_chat(payload: dict = Body(...)):
    """Endpoint principal. O Grok decide sozinho: responder, pesquisar na web,
    ou executar ações no PC (encadeando quantas tools precisar)."""
    text = (payload.get("text") or "").strip()
    if not text:
        return {"error": "no text"}

    browser_active = bool(payload.get("browser_active"))
    prefer_panel = bool(payload.get("prefer_panel"))
    try:
        web_browser.mark_panel_active(browser_active or prefer_panel)
    except Exception:
        pass

    extract_and_learn_prefs_from_text(text)
    tone = jarvis_memory.detect_tone(text)
    append_message("user", text)
    await broadcast({"type": "transcript", "role": "user", "text": text})
    await broadcast({
        "type": "tone",
        "tone": tone,
        "mood": jarvis_memory.emotion_for_orb(tone),
    })
    await broadcast({"type": "state", "state": "thinking"})
    orch_on = os.getenv("JARVIS_AGENT_ORCHESTRATOR", "1").strip().lower() not in (
        "0", "false", "no", "off",
    )
    if orch_on and get_provider() != "ollama":
        try:
            from agent_orchestrator import get_orchestrator

            orch = get_orchestrator()
            primary, _, reasons = orch.select_agent(text)
            if primary:
                await broadcast(
                    {
                        "type": "agent_suggestion",
                        "id": primary.id,
                        "name": primary.name,
                        "reason": reasons[0] if reasons else primary.squad,
                    }
                )
        except Exception:
            pass

    try:
        # Timeout global do chat — evita UI travada para sempre
        chat_to = float(os.getenv("JARVIS_CHAT_TIMEOUT") or "95")
        result = await asyncio.wait_for(
            run_agent_turn(
                text,
                broadcast,
                browser_active=browser_active,
                prefer_panel=prefer_panel,
            ),
            timeout=chat_to,
        )
        from jarvis_agent import merge_turn_meta

        try:
            result = merge_turn_meta(result, text)
        except Exception as me:
            print(f"[chat] merge_turn_meta: {me}")
    except asyncio.TimeoutError:
        await broadcast({"type": "state", "state": "idle"})
        err = (
            "Senhor, o pedido excedeu o tempo máximo. "
            "Sigo online — tente de novo em partes menores."
        )
        append_message("jarvis", err)
        await broadcast({"type": "transcript", "role": "jarvis", "text": err})
        await broadcast({"type": "state", "state": "speaking"})
        return {"response": err, "tools_used": [], "soft_timeout": True}
    except Exception as e:
        print(f"[chat] turno falhou: {type(e).__name__}: {e}")
        err = graceful_error_message(e)
        append_message("jarvis", err)
        await broadcast({"type": "transcript", "role": "jarvis", "text": err})
        await broadcast({"type": "state", "state": "speaking"})
        asyncio.create_task(delayed_idle(4.0))
        return {"error": str(e)[:200], "response": err, "tools_used": []}

    if result.get("requires_confirmation"):
        append_message("jarvis", result["confirmation_prompt"])
        await broadcast({"type": "state", "state": "speaking"})
        return result

    response = result.get("response", "")
    resp_tone = result.get("tone") or tone
    if not result.get("verbatim"):
        response = jarvis_memory.apply_emotion_to_speech(response, resp_tone)
    append_message("jarvis", response)
    tool_names = [t["tool"] for t in result.get("tools_used") or []]
    asyncio.create_task(jarvis_memory.persist_conversation_turn(text, response, tool_names))
    asyncio.create_task(jarvis_memory.learn_from_turn(text, response, resp_tone))
    if result.get("tools_used"):
        record_successful_command(
            f"agent: {text[:60]}",
            {"tools": [t["tool"] for t in result["tools_used"]]},
        )

    await broadcast({
        "type": "tone",
        "tone": resp_tone,
        "mood": result.get("mood") or jarvis_memory.emotion_for_orb(resp_tone),
    })
    await broadcast({"type": "transcript", "role": "jarvis", "text": response, "tone": resp_tone})
    if result.get("agent_suggestion"):
        await broadcast(
            {
                "type": "agent_suggestion",
                "id": result.get("agent_suggestion"),
                "name": result.get("agent_name") or result.get("agent_suggestion"),
                "reason": (result.get("orchestrator") or {}).get("suggestion_reason"),
            }
        )
    await broadcast({"type": "state", "state": "speaking"})
    asyncio.create_task(delayed_idle(4.0))
    return result


@app.post("/api/jarvis/confirm")
async def jarvis_confirm():
    """Executa a tool de risco confirmada e deixa o agente concluir o turno."""
    pending = load_pending()
    if not pending:
        return {"error": "Nenhuma ação pendente."}

    if pending.get("kind") != "agent_tool":
        return await confirm_pending_action()  # compat com fluxo legado

    await broadcast({"type": "state", "state": "thinking"})
    try:
        result = await continue_after_confirmation(broadcast)
    except Exception as e:
        await broadcast({"type": "state", "state": "idle"})
        return {"error": str(e)}

    if result.get("requires_confirmation"):
        append_message("jarvis", result["confirmation_prompt"])
        await broadcast({"type": "state", "state": "speaking"})
        return result

    response = result.get("response", "Executado, senhor.")
    append_message("jarvis", response)
    tool_names = [t["tool"] for t in result.get("tools_used") or []]
    asyncio.create_task(jarvis_memory.persist_conversation_turn("(confirm)", response, tool_names))
    await broadcast({"type": "transcript", "role": "jarvis", "text": response})
    await broadcast({"type": "state", "state": "speaking"})
    asyncio.create_task(delayed_idle(4.0))
    return {"executed": True, **result}


@app.post("/api/jarvis/cancel")
async def jarvis_cancel():
    if load_pending():
        clear_pending()
        await broadcast({"type": "transcript", "role": "jarvis", "text": "Ação cancelada, senhor."})
    await broadcast({"type": "state", "state": "idle"})
    return {"cancelled": True}


# Compat: rota antiga /api/chat agora aponta pro agente
@app.post("/api/chat")
async def chat_compat(payload: dict = Body(...)):
    return await jarvis_chat(payload)


# ============================================================
# FASE 1: DEEP REASONING (mantida)
# ============================================================
@app.post("/api/hermes/reason")
async def hermes_deep_reason(payload: dict = Body(...)):
    text = (payload.get("text") or "").strip()
    if not text:
        return {"error": "no text"}

    effort: ReasoningEffort = payload.get("effort", "high")
    system_prompt = payload.get("system")

    append_message("user", text)
    learned = extract_and_learn_prefs_from_text(text)
    ctx = get_recent_context(4)
    adaptive = get_adaptive_context_for_actions()
    mem_system = system_prompt or ""
    if ctx or learned:
        mem_system = (mem_system + "\n\n" + ctx + "\n" + adaptive).strip()

    await broadcast({"type": "transcript", "role": "user", "text": text})
    await broadcast({"type": "state", "state": "thinking"})
    await broadcast({"type": "reasoning_start", "effort": effort})

    full_answer = ""
    reasoning_trace = ""

    try:
        async for event in stream_deep_reasoning(text, effort=effort, system_prompt=mem_system or None, store=True):
            if event["type"] == "reasoning":
                reasoning_trace += event["delta"]
                await broadcast({"type": "reasoning_chunk", "delta": event["delta"], "accumulated": reasoning_trace[-800:]})
            elif event["type"] == "answer_delta":
                full_answer += event["delta"]
                await broadcast({"type": "answer_chunk", "delta": event["delta"]})
            elif event["type"] == "done":
                full_answer = event["full_answer"]
                reasoning_trace = event["reasoning_trace"]
                await broadcast({
                    "type": "reasoning_complete",
                    "reasoning_trace": reasoning_trace,
                    "reasoning_tokens": event.get("reasoning_tokens", 0),
                    "response_id": event.get("response_id"),
                })
                await broadcast({"type": "transcript", "role": "jarvis", "text": full_answer})
                await broadcast({"type": "state", "state": "speaking"})
                append_message("jarvis", full_answer)
                asyncio.create_task(delayed_idle())
                return {
                    "response": full_answer,
                    "reasoning_trace": reasoning_trace,
                    "reasoning_tokens": event.get("reasoning_tokens", 0),
                    "effort": effort,
                    "response_id": event.get("response_id"),
                }
            elif event["type"] == "error":
                await broadcast({"type": "state", "state": "idle"})
                return {"error": event["message"]}
    except Exception as e:
        await broadcast({"type": "state", "state": "idle"})
        return {"error": str(e)}
    await broadcast({"type": "state", "state": "idle"})
    return {
        "response": full_answer,
        "reasoning_trace": reasoning_trace,
        "effort": effort,
        "incomplete": True,
    }


# ============================================================
# FASE 2: STRUCTURED ACTIONS (legado, mantido funcional)
# ============================================================
@app.post("/api/hermes/action")
async def hermes_structured_action(payload: dict = Body(...)):
    """Legado — redireciona ao agente unificado (evita Chrome externo via actions legado)."""
    return await jarvis_chat(payload)


@app.post("/api/confirm-action")
async def confirm_pending_action():
    pending = load_pending()
    if not pending:
        return {"error": "Nenhuma ação pendente para confirmar."}

    if pending.get("kind") == "agent_tool":
        return await jarvis_confirm()

    plan = ActionPlan(**pending["plan"])
    execution_feedback = execute_structured_action(plan, actions)
    actions_list = plan.get_actions()
    first_dump = actions_list[0].model_dump() if actions_list else {}
    first_name = first_dump.get("action", "sequence")

    had_error = "erro" in (execution_feedback or "").lower()
    if not had_error:
        record_successful_command(f"confirmed: {first_name}", {"feedback": str(execution_feedback)[:120]})

    await broadcast({
        "type": "structured_action",
        "action": first_dump,
        "actions": [a.model_dump() for a in actions_list],
        "speak": f"Executando: {first_name}",
        "execution": execution_feedback,
    })
    await broadcast({"type": "state", "state": "speaking"})
    asyncio.create_task(delayed_idle())
    clear_pending()
    return {"executed": True, "execution_feedback": execution_feedback, "had_error": had_error}


@app.post("/api/cancel-action")
async def cancel_pending_action():
    return await jarvis_cancel()


@app.get("/api/pending-action")
async def get_pending_action():
    """Sincroniza confirmação pendente após reload (suporta agente novo e plano legado)."""
    pending = load_pending()
    if not pending:
        return {"pending": None}

    if pending.get("kind") == "agent_tool":
        tc = pending["tool_call"]
        try:
            args = json.loads(tc.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        return {
            "pending": {
                "action": {"action": tc["name"], **args},
                "confirmation_prompt": f"Confirmar execução de {tc['name']}?",
            }
        }

    plan_data = pending.get("plan", {})
    actions_in_plan = plan_data.get("actions") or []
    return {
        "pending": {
            "action": actions_in_plan[0] if actions_in_plan else None,
            "actions": actions_in_plan,
            "speak": plan_data.get("speak", ""),
            "confirmation_prompt": "Confirmar execução desta ação?",
            "timestamp": pending.get("timestamp"),
        }
    }


@app.post("/api/conversation/reset")
async def reset_conversation():
    clear_conversation()
    await broadcast({"type": "conversation_reset"})
    return {"status": "ok", "message": "Nova conversa iniciada"}


# ============================================================
# FASE 4: Native xAI Tools (web_search + x_search)
# ============================================================
@app.post("/api/tools/search")
async def tools_search(payload: dict = Body(...)):
    query = (payload.get("query") or "").strip()
    if not query:
        return {"error": "no query"}

    result = await search_with_tools(
        query,
        use_web=payload.get("web", True),
        use_x=payload.get("x", False),
        x_handles=payload.get("x_handles"),
    )
    await broadcast({"type": "tool_result", "tool": "search", "query": query, "answer": result["answer"][:600]})
    return result


# ============================================================
# FASE 5: TTS (xAI + Edge) — áudio é tocado pelo frontend
# ============================================================
@app.post("/api/speak/xai")
async def speak_xai(payload: dict = Body(...)):
    """xAI TTS. Usa voice_id do payload, XAI_VOICE_ID, jarvis_voice.json ou voice_prefs."""
    from xai_tts import get_xai_voice_id
    from voice_prefs import get_voice_config

    text = payload.get("text", "")
    if not text:
        return Response(b"", media_type="audio/mpeg")
    vcfg = get_voice_config()
    voice = payload.get("voice_id") or get_xai_voice_id()
    if not voice:
        return Response(b"xai_voice_id ausente", status_code=503, media_type="text/plain")
    lang = payload.get("language") or vcfg.get("language") or "pt-BR"
    speed = float(payload.get("speed") or vcfg.get("speed") or 1.0)
    try:
        audio = await speak_with_xai(
            text,
            voice_id=voice,
            language=lang,
            speed=speed,
        )
        return Response(
            audio,
            media_type="audio/mpeg",
            headers={"X-TTS-Engine": "xai-custom", "X-Jarvis-Voice-Id": voice},
        )
    except Exception as e:
        print(f"[xai] TTS erro: {e}")
        return Response(str(e)[:400].encode("utf-8"), status_code=503, media_type="text/plain")


@app.post("/api/speak/edge")
async def speak_edge_endpoint(payload: dict = Body(...)):
    """Voz JARVIS via Microsoft Antonio Neural (pt-BR, gratuito, alta qualidade)."""
    text = payload.get("text", "")
    if not text:
        return Response(b"", media_type="audio/mpeg")
    from voice_prefs import VOICES
    antonio = VOICES["antonio"]
    audio = await speak_edge(
        text,
        play_system=payload.get("play_system", False),
        rate=antonio.get("rate", "+2%"),
        pitch=antonio.get("pitch", "-4Hz"),
    )
    return Response(
        audio,
        media_type="audio/mpeg",
        headers={"X-TTS-Engine": "edge-antonio-neural"},
    )


@app.post("/api/speak/local")
async def speak_local_endpoint(payload: dict = Body(...)):
    """Clone de voz local (voice-clone-app) — Thomas 0701 sem Eleven/Fish."""
    text = payload.get("text", "")
    if not text:
        return Response(b"", media_type="audio/mpeg")
    try:
        from local_clone_tts import speak_local_clone

        prefer = str(payload.get("prefer") or os.getenv("JARVIS_LOCAL_CLONE_PREFER") or "xtts")
        play_sys = (
            True
            if payload.get("play_system") is True
            else False
            if payload.get("play_system") is False
            else (os.getenv("JARVIS_PLAY_SYSTEM") or "1").strip().lower()
            not in ("0", "false", "no", "off")
        )
        last_err = None
        audio, eng = b"", ""
        for _try in range(2):
            try:
                audio, eng = await asyncio.wait_for(
                    speak_local_clone(
                        text,
                        voice_id=payload.get("voice_id"),
                        prefer=prefer,
                        hq=False,
                        play_system=play_sys,
                    ),
                    timeout=180.0,
                )
                last_err = None
                break
            except Exception as e:
                last_err = e
                await asyncio.sleep(0.4)
        if last_err:
            raise last_err
        if not audio or len(audio) < 100:
            raise RuntimeError("local_empty_audio")
        media = "audio/wav" if audio[:4] == b"RIFF" else "audio/mpeg"
        return Response(
            audio,
            media_type=media,
            headers={
                "X-TTS-Engine": eng,
                "X-Jarvis-Voice-Id": "local-clone",
                "Cache-Control": "no-store",
            },
        )
    except Exception as e:
        print(f"[local-clone] erro (sem Antonio): {e}")
        return Response(b"tts_unavailable", status_code=503, media_type="text/plain")


@app.post("/api/speak/eleven")
async def speak_eleven_endpoint(payload: dict = Body(...)):
    """Voz JARVIS Thomas 0701 via ElevenLabs.

    NÃO cai no Edge Antonio em 429/quota — isso soava como 'voz errada'.
    Edge só se Eleven estiver sem chave/config.
    """
    text = payload.get("text", "")
    if not text:
        return Response(b"", media_type="audio/mpeg")
    try:
        from eleven_tts import speak_eleven, eleven_configured
        if not eleven_configured():
            raise RuntimeError("eleven_not_configured")
        from voice_prefs import get_voice_config
        vcfg = get_voice_config()
        audio = await asyncio.wait_for(speak_eleven(text), timeout=50.0)
        if not audio or len(audio) < 100:
            raise RuntimeError("eleven_empty_audio")
        model = vcfg.get("model") or "eleven_multilingual_v2"
        return Response(
            audio,
            media_type="audio/mpeg",
            headers={
                "X-TTS-Engine": f"elevenlabs-{model}",
                "X-Jarvis-Voice-Id": __import__("eleven_tts", fromlist=["eleven_voice_id"]).eleven_voice_id() or "",
            },
        )
    except Exception as e:
        print(f"[eleven] erro (sem fallback Antonio): {e}")
        return Response(b"tts_unavailable", status_code=503, media_type="text/plain")


@app.post("/api/speak/fish")
async def speak_fish_endpoint(payload: dict = Body(...)):
    """Voz JARVIS Verdadeiro via Fish Audio (reference_id do sample baixado)."""
    if not _FISH_AVAILABLE:
        return Response(b"", status_code=503, media_type="audio/mpeg")
    text = payload.get("text", "")
    if not text:
        return Response(b"", media_type="audio/mpeg")
    from fish_tts import fish_has_api_credit, get_jarvis_reference_id, _get_key
    if not _get_key():
        return Response(b"FISH_API_KEY ausente", status_code=503, media_type="text/plain")
    if not get_jarvis_reference_id():
        return Response(b"Voz nao clonada. Rode clone_fish_voice.py", status_code=503, media_type="text/plain")
    try:
        from voice_prefs import get_voice_config
        vcfg = get_voice_config()
        speed = float(payload.get("speed") or vcfg.get("speed") or 1.0)
        speak_text = text
        resp_tone = (payload.get("tone") or "").strip()
        if resp_tone and not payload.get("verbatim"):
            speak_text = jarvis_memory.apply_emotion_to_speech(speak_text, resp_tone)
        audio = await speak_fish(
            speak_text,
            play_system=payload.get("play_system", False),
            speed=speed,
        )
        from fish_tts import FISH_MODEL, get_jarvis_reference_id
        return Response(
            audio,
            media_type="audio/mpeg",
            headers={
                "X-TTS-Engine": f"fish-{FISH_MODEL}",
                "X-Jarvis-Voice-Id": get_jarvis_reference_id() or "",
            },
        )
    except Exception as e:
        return Response(str(e).encode(), status_code=503, media_type="text/plain")


@app.post("/api/speak/set_model")
async def set_speak_model(payload: dict = Body(...)):
    """Define o modelo Fish (reference_id) ativo e aplica o estilo Thomas (engine fish)."""
    rid = (payload.get("model_id") or payload.get("reference_id") or "").strip()
    if not rid:
        return {"ok": False, "error": "model_id ausente"}
    try:
        from fish_tts import set_jarvis_reference_id
        import voice_prefs
        res = set_jarvis_reference_id(rid)
        voice_prefs.set_voice_id("thomas")
        return {"ok": True, "voice_engine": "thomas", **res}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/speak/status")
async def speak_status():
    """Retorna quais provedores TTS estão configurados."""
    from fish_tts import FISH_MODEL, fish_configured, get_jarvis_reference_id, get_fish_wallet_status
    wallet = await get_fish_wallet_status()
    api_credit = wallet.get("active_credit_usd")
    from voice_prefs import get_voice_config, list_voices
    vcfg = get_voice_config()
    local_st = {}
    local_ok = False
    try:
        from local_clone_tts import local_clone_status

        local_st = await local_clone_status()
        local_ok = bool(local_st.get("ok") or local_st.get("reference_ok"))
    except Exception as e:
        local_st = {"ok": False, "error": str(e)}
    # Canônico: clone local master.wav (Thomas 0701). Eleven só se o usuário pediu eleven.
    engine_id = vcfg.get("voice_id") or "local"
    eleven_ok = __import__("eleven_tts", fromlist=["eleven_configured"]).eleven_configured()
    if engine_id == "local" and not local_ok:
        engine_id = "local"
    return {
        "voice_engine": engine_id if engine_id != "local" else "local",
        "voice_label": vcfg.get("label") if local_ok or vcfg.get("voice_id") != "local" else "JARVIS Clone Local (servidor off)",
        "voices": list_voices(),
        "fish": fish_configured(),
        "fish_api_credit_usd": api_credit,
        "fish_personal_credit_usd": wallet.get("personal_credit_usd"),
        "fish_team_credit_usd": wallet.get("team_credit_usd"),
        "fish_team_id": wallet.get("team_id"),
        "fish_uses_team_wallet": wallet.get("uses_team_wallet"),
        "fish_api_ready": api_credit is not None and api_credit > 0,
        "active_tts_fallback": "local",
        "fish_note": (
            "Fish sem crédito API — usando clone local 0701 / ElevenLabs até recarregar."
            if api_credit is not None and api_credit <= 0
            else None
        ),
        "fish_developers_url": "https://fish.audio/pt/app/developers",
        "fish_voice_connected": bool(get_jarvis_reference_id()),
        "edge": True,
        "local": local_ok,
        "local_clone": local_ok,
        "local_status": local_st,
        "eleven": __import__("eleven_tts", fromlist=["eleven_configured"]).eleven_configured(),
        "eleven_voice_id": __import__("eleven_tts", fromlist=["eleven_voice_id"]).eleven_voice_id(),
        "eleven_model": vcfg.get("model") if vcfg.get("engine") == "eleven" else None,
        "eleven_tuning": (
            {
                k: vcfg.get(k)
                for k in (
                    "stability",
                    "similarity_boost",
                    "style",
                    "speed",
                    "model",
                    "use_speaker_boost",
                    "seed",
                )
                if vcfg.get(k) is not None
            }
            if vcfg.get("engine") == "eleven"
            else None
        ),
        "xai": bool(os.getenv("XAI_API_KEY")),
        "xai_voice_id": (
            __import__("xai_tts", fromlist=["get_xai_voice_id"]).get_xai_voice_id()
        ),
        "fish_model": FISH_MODEL,
        "jarvis_voice_id": get_jarvis_reference_id() or "a5f754f073a14ce3bf544b30efebc2f5",
        "thomas_extract": "backend/assets/thomas-from-voice_sample.mp3",
        "sample_mp3": True,
        "sample_file": "[Voz do Jarvis Verdadeiro]Bom d......0_52. (1).mp3",
    }


@app.get("/api/speak/sample")
async def speak_sample():
    """Retorna o sample MP3 'Voz do Jarvis Verdadeiro' para boot/greeting."""
    sample = Path(__file__).parent / "assets" / "jarvis-verdadeiro-sample.mp3"
    if not sample.exists():
        sample = Path(__file__).resolve().parents[1] / "public" / "voices" / "jarvis-verdadeiro-sample.mp3"
    if not sample.exists():
        return Response(b"", status_code=404)
    return Response(sample.read_bytes(), media_type="audio/mpeg")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
