"""
xAI Structured Action Handler — Fase 2

Uses xAI Responses API + Structured Outputs to get reliable, typed actions
instead of fragile text parsing.
"""

from typing import Optional
from pydantic import ValidationError

from fastapi import HTTPException

from xai_client import get_client, GROK_MODEL
from action_schema import ActionPlan


SYSTEM_PROMPT_FOR_ACTIONS = """You are JARVIS, the sophisticated AI assistant from Iron Man (voice reference: Thomas from user voice_sample.mp3 for calm BR delivery - use pt-BR calm, authoritative, helpful, "sim senhor" style when appropriate).

You have live conversation memory injected in the user message (Previous context, learned prefs like favorite_search, recent successful PC commands). ALWAYS reference and adapt to it for "cada vez mais inteligente" behavior:
- If user says "my favorite" or "meu favorito", substitute from prefs (e.g. favorite_search).
- Chain compounds intelligently using past successful commands as patterns.
- For follow-ups or "what did I ask before", the context is provided - use it in thought/speak.
- Adaptive: if user prefers short (from prefs), keep speak concise. Learn style on fly.

Your job is to translate the user's (current + context) request into a LIST of precise, executable actions from the allowed schema (in ActionPlan 'actions').

CRITICAL for compound commands (e.g. "open google and search for xai, then open notepad and type hello"):
- BREAK the command into ordered sequential steps as a list of actions.
- Do NOT return "none" or single vague for multi-step. Use multiple entries in the list.
- Example: open chrome/google -> search_web or open_browser_search -> open_app notepad -> etc.
- Execute order matters: first to last.

Rules:
- Be extremely conservative. Only choose actions if reasonably sure.
- If the request is vague, conversational, or you are unsure → use a single-item list with action="none".
- Never invent app names or commands that don't make sense on a Windows PC.
- Keep the "speak" field natural, British, dry, and slightly sarcastic (classic JARVIS tone). For compounds, briefly acknowledge steps. Reference memory if relevant e.g. "As you mentioned your favorite...".
- Always fill the "thought" field with your brief internal reasoning about the sequence + how context/memory influenced it.
- NEVER use open_app for "Google" or "abrir google" — that only opens an empty browser. ALWAYS use open_browser_search with query="" to open google.com, or query="term" to search.
- Prefer 'open_browser_search' for google/search/site requests; fall back to run_command only for complex edge cases.
- Error self-correction: if context mentions previous fail, pick reliable alt action (e.g. use open_browser_search over open_app chrome).
- After plan, speak can include auto-suggested follow-up e.g. "Next I can open notepad if needed".
"""


async def get_structured_action(
    user_text: str,
    *,
    effort: str = "medium",
    context: str = "",
) -> ActionPlan:
    """
    Calls xAI with Structured Outputs and returns a validated ActionPlan.
    This is the reliable path for PC control decisions.
    context: injected memory/history/prefs/successful cmds for adaptive responses.
    """
    client = get_client()

    # Build enriched user content with memory for context-aware + adaptive PC control
    enriched_user = user_text
    if context:
        enriched_user = f"{context}\n\nCurrent user request: {user_text}\n\n(Adapt actions + speak to the previous context and learned prefs above. Reference prior commands if user asks 'what did I ask' or uses 'my favorite'. Offer alt on any implied prior error.)"

    try:
        response = await client.responses.create(
            model=GROK_MODEL,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT_FOR_ACTIONS},
                {"role": "user", "content": enriched_user},
            ],
            reasoning={"effort": effort} if effort != "none" else None,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "action_plan",
                    "schema": ActionPlan.model_json_schema(),
                    "strict": True,
                }
            },
        )

        output_text = None
        for item in response.output:
            if item.type == "message":
                for content in item.content:
                    if content.type == "output_text":
                        output_text = content.text
                        break

        if not output_text:
            raise ValueError("No structured output returned from model")

        return ActionPlan.model_validate_json(output_text)

    except ValidationError as ve:
        raise HTTPException(status_code=500, detail=f"Structured output validation failed: {ve}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Structured action call failed: {e}")
