"""Auditoria de segurança — playbook Central Felipe Tâmbara (segurança IA)."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Tuple

_ROOT = Path(__file__).resolve().parent.parent
_SCAN_DIRS = ("backend", "src", "scripts")
_SKIP_PARTS = {".next", "node_modules", "__pycache__", ".git", "assets"}
_SECRET_PATTERNS = [
    (r"sk-[a-zA-Z0-9]{20,}", "OpenAI-style key"),
    (r"AIzaSy[a-zA-Z0-9_-]{20,}", "Google API key"),
    (r"xai-[a-zA-Z0-9]{20,}", "xAI API key"),
    (r"sk_[a-zA-Z0-9]{20,}", "Stripe-style key"),
]
_ENV_NAMES = (
    "API_KEY", "SECRET", "PASSWORD", "TOKEN", "PRIVATE_KEY",
)


def audit_project_secrets() -> str:
    """Varre código por segredos em texto puro (não .env.local)."""
    hits: List[str] = []
    for sub in _SCAN_DIRS:
        base = _ROOT / sub
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".py", ".ts", ".tsx", ".js", ".mjs", ".json"}:
                continue
            if any(p in _SKIP_PARTS for p in path.parts):
                continue
            if path.name in {".env.local", "jarvis_secrets.json"}:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            rel = path.relative_to(_ROOT).as_posix()
            for pat, label in _SECRET_PATTERNS:
                if re.search(pat, text):
                    if label == "xAI API key" and (
                        "xai_voice_id" in text or "voice_id" in text.lower()
                    ):
                        continue
                    hits.append(f"⚠ {rel}: possível {label} hardcoded")
            for line_no, line in enumerate(text.splitlines(), 1):
                if ".env" in line or "getenv" in line or "_read_env" in line:
                    continue
                if re.search(r'["\'][A-Za-z0-9_]{24,}["\']', line) and any(
                    n in line.upper() for n in _ENV_NAMES
                ):
                    hits.append(f"⚠ {rel}:{line_no} valor sensível em string literal")

    env_local = _ROOT / ".env.local"
    gitignore = _ROOT / ".gitignore"
    lines = ["=== Auditoria segurança JARVIS ==="]
    if env_local.is_file():
        lines.append("✓ .env.local existe (segredos fora do código)")
    else:
        lines.append("⚠ .env.local ausente — use variáveis de ambiente")
    if gitignore.is_file() and ".env.local" in gitignore.read_text(encoding="utf-8", errors="replace"):
        lines.append("✓ .env.local no .gitignore")
    else:
        lines.append("⚠ .env.local NÃO está no .gitignore — risco de commit")

    if hits:
        lines.append(f"\n{len(hits)} alerta(s) no código:")
        lines.extend(hits[:12])
        if len(hits) > 12:
            lines.append(f"... +{len(hits) - 12} mais")
    else:
        lines.append("\n✓ Nenhum padrão de chave hardcoded detectado nos diretórios escaneados.")

    lines.append(
        "\nRegra: segredos só em .env.local ou C:\\Users\\Micro\\.hermes\\.env. "
        "Rotacione chaves se já commitadas no git."
    )
    return "\n".join(lines)