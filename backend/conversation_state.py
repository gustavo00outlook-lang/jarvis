"""
Conversation State - Fase 3 + Intelligence Memory (Fase 6)

Very lightweight persistence of the last xAI response_id (for chain) + 
conversation memory (last N messages), learned user prefs (style, favorites),
and successful past PC commands for adaptive control + context-aware responses.

This makes JARVIS "cada vez mais inteligente conforme conversamos":
- Inject "Previous context: ... User said before: ..." into Hermes/xAI system/user prompts.
- Learn prefs on the fly (e.g. "remember my favorite search is xAI" -> use in actions).
- Adaptive PC: suggest/use previous successful commands for compounds/follow-ups.
- Track success for self-correction (if fail, reference and offer alts).
"""

import json
import os
import re
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

STATE_FILE = Path(r"C:\Users\Micro\.hermes\jarvis_conversation_state.json")
MAX_HISTORY = 32
MAX_SUCCESSFUL = 5

# Respostas de fallback quando LLM estava offline — não injetar no contexto (hermes3 repete o padrão).
_DEGRADED_MARKERS = (
    "não consigo acessar nenhum modelo de linguagem",
    "nao consigo acessar nenhum modelo de linguagem",
    "sem acesso a modelos de linguagem",
    "ainda sem acesso a modelos",
    "nenhum llm disponível",
    "nenhum llm configurado",
    "cota do gemini esgotou",
    "nuvem está sem cota",
    "falha interna momentânea",
    "demorou além do aceitável",
)


def _is_degraded_message(text: str) -> bool:
    low = (text or "").strip().lower()
    if not low:
        return False
    return any(m in low for m in _DEGRADED_MARKERS)


def _load_state() -> Dict[str, Any]:
    """Internal: load full state or defaults. Backward compat with old response_id only."""
    if not STATE_FILE.exists():
        return {
            "last_response_id": None,
            "history": [],
            "user_prefs": {},
            "successful_commands": [],
            "updated_at": None,
        }
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        # compat: ensure keys
        data.setdefault("history", [])
        data.setdefault("user_prefs", {})
        data.setdefault("successful_commands", [])
        if "last_response_id" not in data:
            data["last_response_id"] = data.get("last_response_id")
        return data
    except Exception:
        return {
            "last_response_id": None,
            "history": [],
            "user_prefs": {},
            "successful_commands": [],
            "updated_at": None,
        }


def _save_state(data: Dict[str, Any]) -> None:
    """Escrita atômica — crash no meio do write não corrompe o histórico inteiro."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = datetime.now().isoformat()
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def load_last_response_id() -> Optional[str]:
    """Returns the last response_id we got from xAI, if any."""
    data = _load_state()
    return data.get("last_response_id")


def save_last_response_id(response_id: str, metadata: Optional[Dict[str, Any]] = None) -> None:
    """Saves the latest response_id so future calls can continue the chain."""
    data = _load_state()
    data["last_response_id"] = response_id
    if metadata:
        data.setdefault("metadata", {}).update(metadata)
    _save_state(data)


def clear_conversation() -> None:
    """Starts a fresh conversation chain (keeps file but resets memory/history for new session)."""
    if STATE_FILE.exists():
        try:
            STATE_FILE.unlink()
        except Exception:
            pass


def purge_degraded_history() -> int:
    """Remove turnos de fallback LLM do histórico persistido (evita hermes3 repetir 'sem modelo')."""
    data = _load_state()
    hist = data.get("history", [])
    cleaned = [
        h for h in hist
        if not (h.get("role") == "jarvis" and _is_degraded_message(h.get("text", "")))
    ]
    removed = len(hist) - len(cleaned)
    if removed:
        data["history"] = cleaned
        _save_state(data)
    return removed


# ============================================================
# NEW: Simple persistent conversation memory + adaptive learning
# ============================================================

def append_message(role: str, text: str) -> None:
    """Append user or jarvis message to rolling history (last MAX_HISTORY)."""
    if not text or not role:
        return
    if role == "jarvis" and _is_degraded_message(text):
        return
    data = _load_state()
    entry = {
        "role": role,
        "text": text.strip()[:500],  # cap length
        "ts": datetime.now().isoformat()
    }
    hist = data.get("history", [])
    hist.append(entry)
    # keep last N
    data["history"] = hist[-MAX_HISTORY:]
    _save_state(data)


def get_recent_context(n: int = 5) -> str:
    """Formatted previous context string for injecting into Hermes / xAI prompts.
    Example: 'Previous context:\n- User: remember my favorite search is xAI\n- Jarvis: Entendido senhor.\nUser said before: ...'
    """
    data = _load_state()
    hist = [h for h in data.get("history", [])[-n:] if not _is_degraded_message(h.get("text", ""))]
    if not hist:
        return ""
    lines = []
    for h in hist:
        prefix = "User" if h["role"] == "user" else "JARVIS"
        lines.append(f"- {prefix}: {h['text']}")
    ctx = "Previous context (last turns):\n" + "\n".join(lines)
    prefs = get_user_prefs()
    if prefs:
        ctx += "\n\nLearned user preferences: " + ", ".join(f"{k}={v}" for k,v in list(prefs.items())[:4])
    succ = get_previous_successful_commands(2)
    if succ:
        ctx += "\n\nRecent successful PC commands: " + "; ".join(succ)
    return ctx


def get_ui_history(n: int = 10) -> List[Dict[str, Any]]:
    """Histórico para restaurar contexto na UI ao reabrir o app."""
    data = _load_state()
    return list(data.get("history", [])[-max(1, min(n, MAX_HISTORY)):])


def get_api_messages(n: int = 12) -> List[Dict[str, str]]:
    """Histórico no formato da API (role user/assistant) para o loop do agente."""
    data = _load_state()
    hist = data.get("history", [])[-n:]
    out: List[Dict[str, str]] = []
    for h in hist:
        role = "user" if h.get("role") == "user" else "assistant"
        text = (h.get("text") or "").strip()
        if text and not (role == "assistant" and _is_degraded_message(text)):
            out.append({"role": role, "content": text})
    return out


def get_user_prefs() -> Dict[str, Any]:
    data = _load_state()
    return data.get("user_prefs", {}) or {}


def forget_user_pref(key: str) -> None:
    if not key:
        return
    data = _load_state()
    prefs = data.setdefault("user_prefs", {})
    prefs.pop(key, None)
    _save_state(data)


def update_user_pref(key: str, value: Any) -> None:
    """Learn/store a pref e.g. 'favorite_search': 'xAI', 'prefers_short': True."""
    if not key:
        return
    data = _load_state()
    prefs = data.setdefault("user_prefs", {})
    prefs[key] = value
    _save_state(data)


def extract_and_learn_prefs_from_text(text: str) -> Dict[str, Any]:
    """Simple heuristic extraction for 'cada vez mais inteligente': detect remember/favorite prefs from chat.
    Call this on user messages in chat/action paths.
    """
    learned = {}
    t = (text or "").lower().strip()
    if not t:
        return learned
    # favorites
    if "favorite" in t or "favorito" in t or "meu favorito" in t:
        if "search" in t or "busca" in t or "google" in t:
            # crude extract after "is" or "="
            for marker in ["is ", "é ", ":", "="]:
                if marker in t:
                    val = t.split(marker, 1)[-1].strip().split()[0:3]
                    if val:
                        learned["favorite_search"] = " ".join(val).strip(".,!?")
                        break
        if "app" in t or "aplicativo" in t or "notepad" in t or "chrome" in t:
            learned["favorite_app"] = t.split()[-1].strip(".,!?")  # rough
    # remember my ...
    if "remember my" in t or "lembre" in t or "lembrar" in t or "guarde" in t:
        if "search" in t or "busca" in t:
            learned["favorite_search"] = "xAI" if "xai" in t else (t.split("is ",1)[-1] if "is " in t else "xAI")
    # style prefs — só quando é preferência declarada ("responda curto"),
    # não palavra solta ("shorts", "nome completo", "resumo do vídeo").
    if re.search(
        r"\b(?:respond[ae]|seja|fal[ae])\s+(?:de\s+forma\s+|mais\s+|bem\s+)?"
        r"(?:curt[oa]|breve|direto|resumid[oa])\b"
        r"|\b(?:prefiro\s+)?respostas?\s+(?:mais\s+|bem\s+)?curtas?\b"
        r"|\bshort\b",
        t,
    ):
        learned["response_style"] = "short"
    if re.search(
        r"\b(?:respond[ae]|seja|fal[ae])\s+(?:de\s+forma\s+|mais\s+|bem\s+)?"
        r"(?:detalhad[oa]|complet[oa]|long[oa])\b"
        r"|\b(?:prefiro\s+)?respostas?\s+(?:mais\s+|bem\s+)?(?:detalhadas?|completas?|longas?)\b",
        t,
    ):
        learned["response_style"] = "detailed"
    try:
        import voice_prefs
        vid = voice_prefs.parse_voice_change(text)
        if vid:
            voice_prefs.set_voice_id(vid)
            learned["voice_engine"] = vid
    except Exception:
        pass
    for k, v in learned.items():
        update_user_pref(k, v)
    return learned


def record_successful_command(desc: str, details: Optional[Dict[str, Any]] = None) -> None:
    """Track successful PC control for adaptive reuse in future compounds / suggestions."""
    if not desc:
        return
    data = _load_state()
    cmds = data.setdefault("successful_commands", [])
    entry = {"desc": desc[:200], "ts": datetime.now().isoformat(), "details": details or {}}
    cmds.append(entry)
    data["successful_commands"] = cmds[-MAX_SUCCESSFUL:]
    _save_state(data)


def get_previous_successful_commands(n: int = 3) -> List[str]:
    data = _load_state()
    cmds = data.get("successful_commands", [])[-n:]
    return [c.get("desc", "") for c in cmds if c.get("desc")]


def get_adaptive_context_for_actions() -> str:
    """Extra context snippet specifically for action planning / chaining."""
    ctx = get_recent_context(4)
    succ = get_previous_successful_commands(3)
    if succ:
        ctx += "\nUse previous successful patterns for chaining if relevant (e.g. follow up open with search)."
    prefs = get_user_prefs()
    if prefs.get("favorite_search"):
        ctx += f"\nUser's favorite search topic: {prefs['favorite_search']} (use in search/open_browser_search if 'my favorite' referenced)."
    return ctx
