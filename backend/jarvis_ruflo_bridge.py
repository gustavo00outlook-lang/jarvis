"""Bridge Ruflo — ativação automática quando JARVIS detecta tarefa dev/swarm."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

_JARVIS_ROOT = Path(__file__).resolve().parent.parent
_RUFLO_HOME = Path(os.getenv("JARVIS_RUFLO_HOME", str(_JARVIS_ROOT)))
_RUFLO_MARKER = _RUFLO_HOME / ".claude-flow"
_RUFLO_DISABLED = os.getenv("JARVIS_RUFLO", "1").strip().lower() in ("0", "false", "no", "off")

_RUFLO_TASK_RE = re.compile(
    r"\b(?:"
    r"implement(?:ar|e|a)?|refator(?:ar|e|a)?|corrig(?:ir|e|a)|consert(?:ar|e|a)|"
    r"debug(?:ar|e|a)?|cod(?:igo|ificar)|typescript|python|react|next\.?js|fastapi|"
    r"arquitetur|backend|frontend|api\b|schema|migra(?:ção|cao)|deploy|ci/?cd|"
    r"test(?:e|ar|es)?|unit(?:\s+test)?|e2e|qa\b|review(?:\s+de\s+código)?|"
    r"pull\s+request|pr\b|github|commit|branch|stack|swarm|multi-?agent|"
    r"ruflo|claude\s*code|orquestr(?:ar|e)|workflow\s+dev|"
    r"melhor(?:e|ar)\s+(?:o\s+)?jarvis|orb|anima(?:ção|cao)"
    r")\b",
    re.I,
)

_RUFLO_HEAVY_RE = re.compile(
    r"\b(?:"
    r"swarm|multi-?agent|orquestr(?:ar|e)\s+agentes|planej(?:ar|e)\s+dev|"
    r"refator(?:ar|e)\s+tudo|migrar\s+projeto|arquitetur(?:a|e)\s+completa|"
    r"implement(?:ar|e)\s+(?:feature|sistema|módulo|modulo)"
    r")\b",
    re.I,
)

_NPX = shutil.which("npx") or shutil.which("npx.cmd")


def wants_ruflo(user_text: str) -> bool:
    if _RUFLO_DISABLED:
        return False
    raw = (user_text or "").strip()
    if not raw or len(raw) < 8:
        return False
    if raw.lower().startswith(("/agentes", "/ativar", "/quem", "/geral", "/skills")):
        return False
    return bool(_RUFLO_TASK_RE.search(raw))


def ruflo_mode(user_text: str) -> str:
    """swarm = tarefa pesada; assist = dev pontual."""
    if _RUFLO_HEAVY_RE.search(user_text or ""):
        return "swarm"
    return "assist"


def ruflo_configured() -> bool:
    if _RUFLO_DISABLED:
        return False
    for marker in (
        _RUFLO_MARKER,
        _JARVIS_ROOT / ".claude-flow",
        _JARVIS_ROOT / ".mcp.json",
        _JARVIS_ROOT / "CLAUDE.md",
    ):
        if marker.exists():
            return True
    return bool(os.getenv("JARVIS_RUFLO_READY", "").strip() in ("1", "true", "yes"))


async def ensure_ruflo_installed() -> bool:
    """Init leve do Ruflo no projeto JARVIS (idempotente)."""
    if ruflo_configured():
        return True
    if not _NPX:
        return False
    try:
        proc = await asyncio.create_subprocess_exec(
            _NPX,
            "ruflo@latest",
            "init",
            "--yes",
            cwd=str(_JARVIS_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(proc.communicate(), timeout=180)
        except asyncio.TimeoutError:
            proc.kill()
            return False
        if proc.returncode == 0 or (_JARVIS_ROOT / ".claude-flow").is_dir():
            os.environ["JARVIS_RUFLO_READY"] = "1"
            return True
    except Exception as e:
        print(f"[ruflo] init skip: {e}")
    return ruflo_configured()


async def _ruflo_status() -> Dict[str, Any]:
    if not _NPX:
        return {"ok": False, "error": "npx ausente"}
    try:
        proc = await asyncio.create_subprocess_exec(
            _NPX,
            "ruflo@latest",
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=45)
        ver = (out or err or b"").decode("utf-8", errors="ignore").strip()
        return {"ok": proc.returncode == 0, "version": ver[:80]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def build_ruflo_block(user_text: str, *, mode: str) -> str:
    lines = [
        "\n\n=== RUFLO DEV SWARM — ATIVO (auto) ===",
        "O meta-harness Ruflo foi acionado para esta tarefa de engenharia.",
        f"Modo: {mode} — coordene como JARVIS: planeje, execute tools, revise.",
        "Use raciocínio multi-passo: diagnóstico → plano curto → execução → verificação.",
        "Para código JARVIS: respeite motion.ts, agent_orchestrator.py, jarvis_agent fast-paths.",
        "Não mencione 'Ruflo' ou 'swarm' ao usuário — fale como JARVIS competente.",
    ]
    if mode == "swarm":
        lines.append(
            "Tarefa complexa: decomponha em subtarefas, priorize risco, "
            "confirme antes de ações destrutivas no PC."
        )
    return "\n".join(lines)


async def activate_for_turn(
    user_text: str,
    *,
    broadcast: Optional[Any] = None,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Detecta necessidade de Ruflo e prepara contexto para o turno.
    Retorna (ativo, meta dict para anexar ao result).
    """
    if not wants_ruflo(user_text):
        return False, {}

    mode = ruflo_mode(user_text)
    ready = ruflo_configured()

    meta: Dict[str, Any] = {
        "ruflo_active": True,
        "ruflo_mode": mode,
        "ruflo_ready": ready,
        "ruflo_version": "3.16.3" if ready else None,
        "ruflo_reason": "tarefa de desenvolvimento/swarm detectada",
        "ruflo_label": "Ruflo Dev Swarm" if mode == "swarm" else "Ruflo Assist",
        "ruflo_block": build_ruflo_block(user_text, mode=mode),
    }

    if broadcast:
        try:
            await broadcast(
                {
                    "type": "agent_suggestion",
                    "id": "ruflo",
                    "name": meta["ruflo_label"],
                    "reason": meta["ruflo_reason"],
                }
            )
        except Exception:
            pass

    return True, meta


def status_dict() -> Dict[str, Any]:
    return {
        "enabled": not _RUFLO_DISABLED,
        "configured": ruflo_configured(),
        "home": str(_RUFLO_HOME),
        "marker": str(_RUFLO_MARKER),
    }