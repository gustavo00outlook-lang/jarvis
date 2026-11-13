"""Pré-carrega hermes3 no Ollama para reduzir latência da 1ª pergunta."""

from __future__ import annotations

import os

import httpx

from xai_client import (
    _ollama_base,
    _ollama_model,
    _ollama_runtime_options,
    check_ollama_available,
)


def _warmup_enabled() -> bool:
    return (os.getenv("JARVIS_OLLAMA_WARMUP") or "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _keep_alive() -> str:
    return (os.getenv("JARVIS_OLLAMA_KEEP_ALIVE") or "60m").strip() or "60m"


async def warmup_ollama() -> None:
    if not _warmup_enabled():
        return
    if not await check_ollama_available(force=True):
        print("[ollama] warmup ignorado — servidor offline ou modelo ausente")
        return

    base = _ollama_base().replace("/v1", "")
    model = _ollama_model()
    try:
        timeout_s = float(os.getenv("JARVIS_OLLAMA_WARMUP_TIMEOUT") or "200")
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            opts = _ollama_runtime_options()
            r = await client.post(
                f"{base}/api/generate",
                json={
                    "model": model,
                    "prompt": "ok",
                    "stream": False,
                    "keep_alive": _keep_alive(),
                    "options": opts,
                },
            )
            if r.status_code == 200:
                print(f"[ollama] warmup OK — {model} pré-carregado (keep_alive {_keep_alive()})")
            else:
                print(f"[ollama] warmup HTTP {r.status_code}: {r.text[:120]}")
    except Exception as e:
        detail = str(e).strip() or type(e).__name__
        print(f"[ollama] warmup falhou (não crítico): {detail}")