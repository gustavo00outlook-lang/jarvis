"""
xAI Reasoning Adapter for JARVIS Pro — Fase 1

Streaming deep reasoning via the xAI Responses API:
- reasoning_effort (low/medium/high)
- Live reasoning_content deltas (visible "thinking" trace)
- Final answer + usage metadata (reasoning tokens)
"""

import json
import os
from typing import AsyncGenerator, Optional, Dict, Any, Literal

from fastapi import HTTPException

from xai_client import get_client, GROK_MODEL
from conversation_state import load_last_response_id, save_last_response_id

ReasoningEffort = Literal["none", "low", "medium", "high"]


async def stream_deep_reasoning(
    prompt: str,
    *,
    effort: ReasoningEffort = "high",
    system_prompt: Optional[str] = None,
    previous_response_id: Optional[str] = None,
    store: bool = True,
    auto_continue: bool = True,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Streams reasoning deltas and the final answer (Fase 1 + Fase 3).

    When auto_continue=True the last saved response_id is used automatically
    so conversations chain without resending the full history.
    """
    client = get_client()

    effective_previous_id = previous_response_id
    if auto_continue and not previous_response_id:
        effective_previous_id = load_last_response_id()

    messages = []
    if system_prompt and not effective_previous_id:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    # Avoid burning high-effort tokens on trivial prompts
    if effort == "high" and len(prompt) < 40:
        effort = "medium"

    reasoning_config = {"effort": effort} if effort != "none" else None

    try:
        stream = await client.responses.create(
            model=GROK_MODEL,
            input=messages,
            reasoning=reasoning_config,
            previous_response_id=effective_previous_id,
            store=store,
            stream=True,
        )

        full_answer_parts = []
        reasoning_parts = []
        final_response_id = None
        reasoning_tokens = 0

        async for event in stream:
            if getattr(event, "type", None) == "response.reasoning_summary_text.delta":
                delta = event.delta or ""
                if delta:
                    reasoning_parts.append(delta)
                    yield {"type": "reasoning", "delta": delta}

            elif getattr(event, "type", None) == "response.output_text.delta":
                delta = event.delta or ""
                if delta:
                    full_answer_parts.append(delta)
                    yield {"type": "answer_delta", "delta": delta}

            elif getattr(event, "type", None) == "response.completed":
                resp = event.response
                final_response_id = getattr(resp, "id", None)

                usage = getattr(resp, "usage", None)
                if usage:
                    reasoning_tokens = getattr(usage, "reasoning_tokens", 0) or 0

                full_answer = "".join(full_answer_parts).strip()
                reasoning_trace = "".join(reasoning_parts).strip()

                if final_response_id and store:
                    save_last_response_id(final_response_id, {
                        "effort": effort,
                        "prompt_preview": prompt[:120],
                    })

                yield {
                    "type": "done",
                    "full_answer": full_answer,
                    "reasoning_trace": reasoning_trace,
                    "reasoning_tokens": reasoning_tokens,
                    "response_id": final_response_id,
                    "effort": effort,
                    "continued_from": effective_previous_id,
                }

    except Exception as e:
        yield {"type": "error", "message": str(e)}


async def deep_reason_once(
    prompt: str,
    *,
    effort: ReasoningEffort = "high",
    system_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """One-shot deep reasoning — collects all deltas and returns the final event."""
    async for event in stream_deep_reasoning(prompt, effort=effort, system_prompt=system_prompt):
        if event["type"] in ("done", "error"):
            return event
    return {"type": "done", "full_answer": "", "reasoning_trace": "", "reasoning_tokens": 0, "response_id": None, "effort": effort}
