"""
Pending Action State - for Fase 2 confirmation flow.

Simple file-based persistence so that pending confirmation survives backend restarts and page reloads.
"""

import json
import os
from pathlib import Path
from typing import Optional, Dict, Any

STATE_FILE = (Path.home() / '.hermes' / 'jarvis_pending_action.json')


def load_pending() -> Optional[Dict[str, Any]]:
    """Load the current pending action if any. Auto-clears if older than 5 minutes."""
    if not STATE_FILE.exists():
        return None
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        ts = data.get("timestamp")
        if ts:
            from datetime import datetime, timedelta
            try:
                dt = datetime.fromisoformat(ts)
                if datetime.now() - dt > timedelta(minutes=5):
                    clear_pending()
                    return None
            except:
                pass
        return data
    except Exception:
        return None


def save_pending(data: Dict[str, Any]) -> None:
    """Save the pending action."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def clear_pending() -> None:
    """Clear the pending action."""
    if STATE_FILE.exists():
        try:
            STATE_FILE.unlink()
        except Exception:
            pass
