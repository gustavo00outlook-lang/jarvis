"""Registry de skills Grok/Cursor usadas pelo assistente — expostas ao JARVIS."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

_SKILL_ROOTS = [
    Path(os.getenv("JARVIS_GROK_SKILLS", str(Path.home() / '.grok' / 'skills'))),
    (Path.home() / '.grok' / 'bundled' / 'skills'),
    Path(os.getenv("JARVIS_AGENTS_SKILLS", str(Path.home() / '.agents' / 'skills'))),
    (Path(__file__).resolve().parent.parent / '.grok' / 'skills'),
    (Path(__file__).resolve().parent.parent / '.claude' / 'skills'),
]

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
_NAME = re.compile(r"^name:\s*(.+)$", re.M)
_DESC = re.compile(r"^description:\s*(.+)$", re.M | re.S)


@dataclass
class JarvisSkill:
    id: str
    name: str
    description: str
    path: str
    source: str

    def summary(self) -> str:
        d = (self.description or "").replace("\n", " ").strip()
        if len(d) > 160:
            d = d[:157] + "…"
        return f"• {self.name} (`{self.id}`) — {d}"


_cache: Optional[List[JarvisSkill]] = None


def _parse_skill(path: Path, source: str) -> Optional[JarvisSkill]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    blob = text
    m = _FRONTMATTER.match(text)
    if m:
        blob = m.group(1)
    name_m = _NAME.search(blob)
    desc_m = _DESC.search(blob)
    name = (name_m.group(1).strip() if name_m else path.parent.name).strip("\"'")
    desc = (desc_m.group(1).strip() if desc_m else "").strip("\"'")
    if not name:
        return None
    sid = re.sub(r"[^\w-]+", "-", name.lower()).strip("-") or path.parent.name
    return JarvisSkill(id=sid, name=name, description=desc, path=str(path), source=source)


def load_skills(force: bool = False) -> List[JarvisSkill]:
    global _cache
    if _cache is not None and not force:
        return _cache
    found: Dict[str, JarvisSkill] = {}
    for root in _SKILL_ROOTS:
        if not root.is_dir():
            continue
        source = root.name
        for skill_md in root.rglob("SKILL.md"):
            if "node_modules" in str(skill_md):
                continue
            prof = _parse_skill(skill_md, source)
            if prof and prof.id not in found:
                found[prof.id] = prof
    _cache = sorted(found.values(), key=lambda s: s.name.lower())
    return _cache


def skills_by_source() -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for s in load_skills():
        counts[s.source] = counts.get(s.source, 0) + 1
    return counts


def skills_status() -> Dict[str, Any]:
    skills = load_skills()
    roots = [str(p) for p in _SKILL_ROOTS if p.is_dir()]
    return {
        "total": len(skills),
        "roots": roots,
        "by_source": skills_by_source(),
        "skills": [
            {"id": s.id, "name": s.name, "description": s.description[:220], "source": s.source}
            for s in skills
        ],
    }


def match_skills(user_text: str, *, top: int = 8) -> List[JarvisSkill]:
    """Pontua skills pelo pedido — as mais relevantes sobem no prompt do agente."""
    raw = (user_text or "").lower()
    if not raw.strip():
        return []
    tokens = set(re.findall(r"[a-záéíóúâêôãõç0-9]{3,}", raw, flags=re.I))
    scored: List[tuple] = []
    for s in load_skills():
        blob = f"{s.id} {s.name} {s.description}".lower()
        score = 0.0
        for t in tokens:
            if t in blob:
                score += 1.2 if t in s.id or t in s.name.lower() else 0.6
        # boosts por domínio
        boosts = (
            (("jarvis", "orb", "voz", "tts", "backend", "fastapi"), ("jarvis-dev", "jarvis-obsidian-sync"), 3.0),
            (("browser", "playwright", "teste ui", "qa", "screenshot"), ("browser-qa", "dev-browser", "browser-review", "browser"), 3.0),
            (("github", "pr", "pull request", "release", "ci"), ("github-code-review", "github-release-management", "github-workflow-automation", "pr-babysit", "review"), 2.5),
            (("docx", "word", "xlsx", "excel", "pptx", "powerpoint", "planilha"), ("docx", "xlsx", "pptx"), 3.5),
            (("design", "landing", "cinematic", "seo"), ("design", "cinematic-landing", "seo-audit"), 2.5),
            (("swarm", "multi-agent", "orquestr"), ("swarm-orchestration", "swarm-advanced", "smart-orchestrator", "aiox-orchestrator"), 2.5),
            (("segurança", "security", "pentest", "ciber"), ("cybersecurity-squad", "v3-security-overhaul"), 3.0),
            (("plano", "design doc", "arquitetura", "sparc"), ("design", "execute-plan", "sparc-methodology"), 2.0),
            (("memory", "agentdb", "vector", "rag"), ("agentdb-vector-search", "agentdb-memory-patterns", "reasoningbank-with-agentdb"), 2.5),
        )
        for keys, ids, w in boosts:
            if any(k in raw for k in keys) and s.id in ids:
                score += w
        if score > 0:
            scored.append((score, s))
    scored.sort(key=lambda x: (-x[0], x[1].name.lower()))
    return [s for _, s in scored[:top]]


def build_skills_prompt_block(limit: int = 55, user_text: str = "") -> str:
    skills = load_skills()
    if not skills:
        return ""
    # Ollama/local: prompt compacto (só matched + core). Cloud: amostra maior.
    provider = os.getenv("JARVIS_LLM_PROVIDER", "ollama").strip().lower()
    compact_flag = os.getenv("JARVIS_COMPACT_SKILLS", "1").strip().lower() in (
        "1", "true", "yes", "on",
    )
    compact = provider in ("ollama", "local", "hermes") and compact_flag
    effective_limit = min(limit, 14 if compact else limit)
    matched = match_skills(user_text, top=min(8, effective_limit)) if user_text else []
    # Always include core execution skills
    core_ids = {
        "smart-orchestrator", "jarvis-dev", "browser-qa", "dev-browser",
        "implement", "review", "docx", "xlsx", "pptx", "pdf", "seo-audit",
        "swarm-orchestration", "check-work", "aiox-orchestrator",
        "imagine", "design", "create-skill", "modes",
        "long-running-background-tasks", "cinematic-landing", "build-with-ai",
    }
    by_id = {s.id: s for s in skills}
    ordered: List[JarvisSkill] = []
    seen = set()
    for s in matched:
        if s.id not in seen:
            ordered.append(s)
            seen.add(s.id)
    for cid in core_ids:
        if cid in by_id and cid not in seen:
            ordered.append(by_id[cid])
            seen.add(cid)
    if not compact:
        for s in skills:
            if s.id not in seen:
                ordered.append(s)
                seen.add(s.id)
            if len(ordered) >= effective_limit:
                break

    lines = [
        "\n\n=== SKILLS GROK/CURSOR (capacidades internas — use quando o pedido combinar) ===",
        f"Tenho {len(skills)} skills especializadas. Roteie internamente para a skill certa; "
        "não liste tudo ao Gustavo salvo /skills. Combine com os 166 agentes AIOS/Xquads.",
    ]
    if matched:
        lines.append("SKILLS MAIS RELEVANTES PARA ESTE PEDIDO:")
        for s in matched[:6]:
            lines.append(s.summary())
        if not compact:
            lines.append("OUTRAS SKILLS DISPONÍVEIS (amostra):")
    if compact:
        # Só core + matched (cabe no contexto Ollama 8k)
        for s in ordered[:effective_limit]:
            if matched and s in matched[:6]:
                continue
            lines.append(s.summary())
    else:
        for s in ordered[:effective_limit]:
            if matched and s in matched[:6]:
                continue
            lines.append(s.summary())
    if len(skills) > effective_limit:
        lines.append(f"… e mais {len(skills) - effective_limit} skills. Comando: /skills")
    lines.append(
        "Playbook: smart-orchestrator/aiox para rotear; jarvis-dev para o app JARVIS; "
        "browser-qa/dev-browser para testar sites; implement/review/check-work para código; "
        "docx/xlsx/pptx para documentos; swarm-* para tarefas multi-agente; "
        "seo-audit/design/cinematic-landing para marca e web."
    )
    return "\n".join(lines)


_SKILLS_CMD_RE = re.compile(
    r"(?:^/skills(?:\s+reload)?$|^skills$|lista\s+skills|quais\s+skills|"
    r"quais\s+habil|suas\s+habil|lista\s+habil|habilidades|habulidades|"
    r"skills\s+dispon|skills\s+ativas?)",
    re.I,
)


def handle_skills_command(text: str) -> Optional[str]:
    low = (text or "").strip().lower()
    if not _SKILLS_CMD_RE.search(low):
        return None
    skills = load_skills(force=low.startswith("/skills reload"))
    if not skills:
        return (
            "Senhor, nenhuma skill externa carregada no momento — nenhuma pasta de skills "
            "foi encontrada no disco. Sigo operando com as ferramentas nativas: "
            "PC, painel web, voz, memória Obsidian e pesquisa."
        )
    by_source = skills_by_source()
    src_txt = ", ".join(
        f"{n} de {src}" for src, n in sorted(by_source.items(), key=lambda kv: -kv[1])
    )
    parts = [
        f"Senhor, tenho {len(skills)} skills ativas ({src_txt}).",
        "Exemplos:",
    ]
    for s in skills[:28]:
        parts.append(f"  • **{s.name}** — {s.description[:100]}")
    if len(skills) > 28:
        parts.append(f"  … e mais {len(skills) - 28}.")
    agents_total = 0
    try:
        from agent_orchestrator import get_orchestrator

        agents_total = int(get_orchestrator().status_dict().get("total_agents") or 0)
    except Exception:
        pass
    parts.append(
        f"Os {agents_total} agentes AIOS/Xquads complementam: /agentes para ver todos."
        if agents_total
        else "Agentes AIOS/Xquads complementam: /agentes para ver todos."
    )
    return "\n".join(parts)