"""Credenciais locais do JARVIS — NUNCA salvar no vault Obsidian."""

import json
from pathlib import Path
from typing import Any, Dict, Optional

SECRETS_FILE = (Path.home() / '.hermes' / 'jarvis_secrets.json')


def _load() -> Dict[str, Any]:
    if not SECRETS_FILE.exists():
        return {}
    try:
        return json.loads(SECRETS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: Dict[str, Any]) -> None:
    SECRETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SECRETS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def set_service_credentials(service: str, fields: Dict[str, str]) -> None:
    data = _load()
    data[service] = {**(data.get(service) or {}), **fields}
    _save(data)


def get_service_credentials(service: str) -> Dict[str, str]:
    return dict(_load().get(service) or {})


def get_calango_login() -> Optional[Dict[str, str]]:
    c = get_service_credentials("calango_studio")
    if c.get("email") and c.get("password"):
        return c
    return None


def credentials_context_for_agent() -> str:
    """Contexto injetado no system prompt — uso interno do agente."""
    lines = []
    cal = get_calango_login()
    if cal:
        lines.append(
            f"Calango Studio (login automático): email={cal['email']}, "
            f"senha={cal['password']}. Use browse_open #/login → campo email (4) → senha (5) → Enter. "
            "Não leia a senha em voz alta ao Gustavo."
        )
    return "\n".join(lines)