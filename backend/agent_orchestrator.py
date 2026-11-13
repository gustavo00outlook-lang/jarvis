"""Orquestrador de Agentes JARVIS — AIOS + Xquads.

Roteia cada turno para a persona especialista mais adequada.
Arquivo base: squads Xquads + agentes AIOS (AIOX).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_STORE = (Path.home() / '.hermes' / 'jarvis_active_agent.json')
_XQUADS = Path(os.getenv("JARVIS_XQUADS_PATH", str(Path.home() / 'xquads-squads')))
_AIOS = Path(os.getenv("JARVIS_AIOS_PATH", str(Path.home() / 'aios-core')))

_YAML_BLOCK = re.compile(r"```ya?ml\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


@dataclass
class AgentProfile:
    id: str
    name: str
    squad: str
    source: str
    title: str = ""
    tone: str = ""
    when_to_use: str = ""
    focus: str = ""
    role: str = ""
    style: str = ""
    greeting: str = ""
    keywords: List[str] = field(default_factory=list)
    tier: int = 1
    file_path: str = ""
    # Trecho denso do .md do agente (metodologia / activation) — conhecimento Xquads
    knowledge: str = ""

    def summary_line(self) -> str:
        scope = self.when_to_use or self.focus or self.title
        return f"• **{self.name}** (`{self.id}`) — {self.squad} — {scope[:120]}"


def _parse_simple_yaml(blob: str) -> Dict[str, Any]:
    """Parser leve para blocos YAML dos agentes (sem dependência PyYAML)."""
    data: Dict[str, Any] = {}
    stack: List[Tuple[int, Any]] = [(0, data)]
    key_re = re.compile(r"^(\s*)([\w.-]+):\s*(.*)$")

    for raw in blob.splitlines():
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        m = key_re.match(raw)
        if not m:
            continue
        indent, key, val = len(m.group(1)), m.group(2), m.group(3).strip()
        while stack and indent < stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if val == "" or val == "|":
            node: Any = {}
            parent[key] = node
            stack.append((indent + 2, node))
        elif val.startswith('"') and val.endswith('"'):
            parent[key] = val[1:-1]
        elif val.startswith("'") and val.endswith("'"):
            parent[key] = val[1:-1]
        else:
            parent[key] = val.strip("'\"")
    return data


def _dig(d: Dict[str, Any], *keys: str, default: str = "") -> str:
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return str(cur or default).strip()


def _extract_agent_knowledge(text: str) -> str:
    """Extrai conhecimento denso do .md do agente (activation + corpo útil)."""
    if not text:
        return ""
    chunks: List[str] = []
    # ACTIVATION-NOTICE (bloco de citação no topo dos Xquads)
    m_act = re.search(
        r"ACTIVATION-NOTICE:\s*(.+?)(?:\n\s*\n|\n## |\n```)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if m_act:
        chunks.append(m_act.group(1).strip())
    # Corpo após o YAML principal — frameworks, routing, playbooks
    after_yaml = _YAML_BLOCK.sub("", text, count=1)
    # Remove headings de front matter ruidosos
    after_yaml = re.sub(r"^#+\s*.+$", "", after_yaml, flags=re.M)
    after_yaml = re.sub(r"^>\s*", "", after_yaml, flags=re.M)
    after_yaml = re.sub(r"\n{3,}", "\n\n", after_yaml).strip()
    if after_yaml:
        chunks.append(after_yaml)
    blob = "\n\n".join(chunks).strip()
    # Limpa markdown pesado mas preserva conteúdo
    blob = re.sub(r"```ya?ml[\s\S]*?```", "", blob, flags=re.I)
    blob = re.sub(r"[ \t]+\n", "\n", blob)
    blob = re.sub(r"\n{3,}", "\n\n", blob).strip()
    return blob[:2400]


def _extract_profile(path: Path, source: str, squad: str) -> Optional[AgentProfile]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    m = _YAML_BLOCK.search(text)
    if not m:
        return None
    root = _parse_simple_yaml(m.group(1))
    agent = root.get("agent") if isinstance(root.get("agent"), dict) else root
    if not isinstance(agent, dict):
        agent = root
    aid = str(agent.get("id") or path.stem).strip().lower()
    if not aid:
        return None
    persona = root.get("persona") if isinstance(root.get("persona"), dict) else {}
    pp = root.get("persona_profile") if isinstance(root.get("persona_profile"), dict) else {}
    comm = pp.get("communication") if isinstance(pp.get("communication"), dict) else {}
    squad_name = str(agent.get("squad") or squad).strip()
    tags = []
    if isinstance(root.get("tags"), list):
        tags = [str(t) for t in root["tags"]]
    when = str(agent.get("whenToUse") or agent.get("when_to_use") or "").strip()
    knowledge = _extract_agent_knowledge(text)
    # Também puxa routing/diagnostic do YAML se existir (texto puro)
    for key in ("diagnostic_routing", "routing_logic", "frameworks", "playbook", "core_principles"):
        node = root.get(key)
        if isinstance(node, dict) and node:
            knowledge = (knowledge + "\n\n" + key + ": " + json.dumps(node, ensure_ascii=False)[:900]).strip()
            break
    kw_blob = " ".join(
        [
            aid,
            squad_name,
            when,
            _dig(persona, "focus"),
            _dig(persona, "role"),
            " ".join(tags),
            knowledge[:400],
        ]
    ).lower()
    keywords = list(
        {
            w
            for w in re.split(r"[^\wáàâãéèêíïóôõöúçñ-]+", kw_blob, flags=re.I)
            if len(w) >= 4
        }
    )
    tier_raw = agent.get("tier", 1)
    try:
        tier = int(tier_raw)
    except Exception:
        tier = 1
    return AgentProfile(
        id=aid,
        name=str(agent.get("name") or aid).strip(),
        squad=squad_name,
        source=source,
        title=str(agent.get("title") or "").strip(),
        tone=str(comm.get("tone") or _dig(persona, "style")).strip(),
        when_to_use=when,
        focus=_dig(persona, "focus"),
        role=_dig(persona, "role"),
        style=str(comm.get("style") or _dig(persona, "style")).strip(),
        greeting=str(comm.get("greeting") or "").strip(),
        keywords=keywords[:40],
        tier=tier,
        file_path=str(path),
        knowledge=knowledge[:2400],
    )


# Palavras-chave por squad (roteamento rápido pt-BR + en)
_SQUAD_KEYWORDS: Dict[str, List[str]] = {
    "copy-squad": [
        "copy", "headline", "titular", "email", "vsl", "carta", "funil", "anúncio",
        "anuncio", "cta", "oferta", "vendas", "halbert", "schwartz", "ogilvy",
    ],
    "copy-master": ["copy", "precific", "preço design", "robo precificador"],
    "design-squad": [
        "design", "ui", "ux", "figma", "carrossel", "layout", "tipografia",
        "mockup", "brand visual", "design system", "agenciasetup",
    ],
    "brand-squad": [
        "marca", "branding", "brand", "posicionamento", "positioning",
        "identidade visual", "brand strategy", "brand equity", "posicionamento de marca",
        "aaker", "ries", "kapferer", "neumeier",
    ],
    "hormozi-squad": ["hormozi", "oferta irresistível", "escala", "ltv", "cac", "saas"],
    "traffic-masters": ["tráfego", "trafego", "ads", "facebook ads", "google ads", "mídia paga"],
    "storytelling": [
        "storytelling", "narrativa", "história", "roteiro", "campbell",
        "youtube", "vídeo", "video", "assista", "assistir", "comentar", "argumentar",
        "co-assistir", "cowatch", "debate", "opinião",
    ],
    "data-squad": ["analytics", "métricas", "metricas", "growth", "dados", "kpi"],
    "cybersecurity": ["segurança", "seguranca", "hack", "pentest", "vulnerabil"],
    "advisory-board": ["estratégia", "estrategia", "investimento", "conselho", "naval", "munger"],
    "c-level-squad": ["ceo", "cto", "cmo", "coo", "executivo", "liderança"],
    "movement": ["comunidade", "movimento", "tribo", "audiência"],
    "claude-code-mastery": ["claude code", "aios", "slash command", "agente ia"],
    "aios": [
        "código", "codigo", "implementar", "bug", "refatorar", "api", "backend",
        "frontend", "arquitetura", "prd", "produto", "teste", "qa", "devops",
        "banco de dados", "schema", "sprint", "backlog",
    ],
}

_JARVIS_MEDIA_RE = re.compile(
    r"\b(?:youtube|vídeo|video|assista|assistir|comentar|argumentar|co-assistir|cowatch)\b",
    re.I,
)
_JARVIS_SEARCH_RE = re.compile(
    r"\b(?:pesquis|busc|google|notícia|noticia|o\s+que\s+(?:você|voce)\s+acha)\b",
    re.I,
)

_COMPARE_RE = re.compile(
    r"\b(?:"
    r"ou\s+(?:o\s+|a\s+)?|vs\.?|versus|"
    r"qual\s+vale\s+mais|vale\s+mais\s+a\s+pena|melhor\s+entre|compar[ae]|"
    r"entre\s+.+\s+e\s+|"
    r"copy-chief|gary-halbert|design-chief|dex|architect|hormozi"
    r")\b",
    re.I,
)
_ADVISORY_RE = re.compile(
    r"\b(?:"
    r"qual\s+agente|quem\s+(?:devo\s+)?usar|quem\s+usar|qual\s+especialista|"
    r"suger[ae]|recomend[ae]|vale\s+mais|/sugerir|/comparar|"
    r"qual\s+squad|qual\s+mind|qual\s+copywriter"
    r")\b",
    re.I,
)
_TASK_INTENT_RE = re.compile(
    r"\b(?:"
    r"preciso|quero|vou|fazer|criar|escrever|montar|lançar|lancar|"
    r"copy|design|código|codigo|implementar|estratégia|estrategia|"
    r"funil|carrossel|headline|arquitetura|prd|testar"
    r")\b",
    re.I,
)

_SQUAD_PROMPTS_DIR = Path(__file__).resolve().parent / "assets" / "squad-prompts"
_SQUAD_PROMPT_FILES: Dict[str, str] = {
    "advisory-board": "01-advisory-board.md",
    "brand-squad": "02-brand-squad.md",
    "c-level-squad": "03-c-level-squad.md",
    "claude-code-mastery": "04-claude-code-mastery.md",
    "copy-master": "05-copy-master.md",
    "copy-squad": "06-copy-squad.md",
    "cybersecurity": "07-cybersecurity.md",
    "data-squad": "08-data-squad.md",
    "design-squad": "09-design-squad.md",
    "hormozi-squad": "10-hormozi-squad.md",
    "movement": "11-movement.md",
    "storytelling": "12-storytelling.md",
    "traffic-masters": "13-traffic-masters.md",
}

_AGENT_PREFERRED_TOOLS: Dict[str, List[str]] = {
    "dev": ["run_command", "read_file", "write_file", "browse_open", "web_search"],
    "architect": ["read_file", "web_search", "study_topic", "save_to_obsidian"],
    "qa": ["run_command", "browse_open", "web_search", "look_at_screen"],
    "copy-chief": ["web_search", "write_note", "save_to_obsidian", "study_topic"],
    "design-chief": ["browse_open", "look_at_screen", "write_note", "web_search"],
    "story-chief": ["browse_open", "browse_click", "watch_screen", "web_search"],
    "board-chair": ["web_search", "study_topic", "write_note", "save_to_obsidian"],
    "brand-chief": ["web_search", "look_at_screen", "write_note", "study_topic"],
    "traffic-chief": ["web_search", "browse_open", "study_topic", "save_to_obsidian"],
    "cybersecurity-lead": ["run_command", "web_search", "read_file", "write_note"],
    "analyst": ["web_search", "study_topic", "save_to_obsidian", "browse_open"],
    "cyrus": ["web_search", "write_note", "study_topic"],
    "hormozi-chief": ["web_search", "study_topic", "write_note"],
}

_AIOS_AGENT_HINTS: Dict[str, List[str]] = {
    "dev": ["implement", "código", "codigo", "bug", "refator", "debug", "typescript", "python"],
    "architect": ["arquitetura", "architecture", "api design", "sistema", "microserv"],
    "pm": ["prd", "produto", "roadmap", "prioriz", "épico", "epic", "feature"],
    "po": ["backlog", "story", "acceptance", "sprint"],
    "qa": ["teste", "qualidade", "qa", "regressão", "regressao"],
    "analyst": ["mercado", "competit", "pesquisa de mercado", "brainstorm", "viabilidade"],
    "data-engineer": ["sql", "banco", "supabase", "migração", "schema", "rls"],
    "devops": ["ci/cd", "deploy", "github", "pipeline", "docker"],
    "sm": ["scrum", "retrospectiva", "standup", "história de usuário"],
    "ux-design-expert": ["wireframe", "ux research", "design system", "acessibilidade"],
    "aiox-master": ["orquestrar", "workflow", "aios", "framework"],
    "squad-creator": ["criar squad", "novo squad"],
}


def _always_route_agents() -> bool:
    return os.getenv("JARVIS_ALWAYS_ROUTE_AGENTS", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _route_score_threshold() -> float:
    return 1.5 if _always_route_agents() else 3.0


def _extract_squad_activation(md_text: str) -> str:
    """Extrai bloco de ativação do squad-prompts (zip Xquads)."""
    # Formato: SQUAD ACTIVATION PROMPT ... ```\nYou are...\n```
    m = re.search(
        r"SQUAD ACTIVATION PROMPT[\s\S]{0,400}?```[a-z]*\s*\n(.*?)```",
        md_text,
        re.DOTALL | re.IGNORECASE,
    )
    if m and len(m.group(1).strip()) > 80:
        return m.group(1).strip()[:3200]
    m2 = re.search(
        r"```[a-z]*\s*\n(You are (?:now )?operating as.*?)\n```",
        md_text,
        re.DOTALL | re.I,
    )
    return (m2.group(1).strip()[:2400] if m2 else "")


class AgentOrchestrator:
    def __init__(self) -> None:
        self._agents: Dict[str, AgentProfile] = {}
        self._squad_agents: Dict[str, List[str]] = {}
        self._loaded = False
        self._active_id: Optional[str] = None
        self._general_mode = False
        self._squad_prompt_cache: Dict[str, str] = {}
        self._auto_pin_until: float = 0.0
        self._load_state()

    def _load_state(self) -> None:
        try:
            if _STORE.exists():
                st = json.loads(_STORE.read_text(encoding="utf-8"))
                self._active_id = (st.get("active_agent_id") or "").strip().lower() or None
                self._general_mode = bool(st.get("general_mode"))
        except Exception:
            pass

    def _save_state(self) -> None:
        _STORE.parent.mkdir(parents=True, exist_ok=True)
        _STORE.write_text(
            json.dumps(
                {
                    "active_agent_id": self._active_id,
                    "general_mode": self._general_mode,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._agents.clear()
        self._squad_agents.clear()

        if _XQUADS.is_dir():
            for squad_dir in sorted(_XQUADS.iterdir()):
                if not squad_dir.is_dir() or squad_dir.name.startswith("."):
                    continue
                squad = squad_dir.name
                agents_dir = squad_dir / "agents"
                if not agents_dir.is_dir():
                    continue
                ids: List[str] = []
                for md in sorted(agents_dir.glob("*.md")):
                    prof = _extract_profile(md, "xquads", squad)
                    if prof:
                        self._agents[prof.id] = prof
                        ids.append(prof.id)
                if ids:
                    self._squad_agents[squad] = ids

        aios_skills = _AIOS / ".claude" / "skills" / "AIOX" / "agents"
        if aios_skills.is_dir():
            ids = []
            for skill_dir in sorted(aios_skills.iterdir()):
                skill = skill_dir / "SKILL.md"
                if skill.is_file():
                    prof = _extract_profile(skill, "aios", "aios")
                    if prof:
                        prof.squad = "aios"
                        self._agents[prof.id] = prof
                        ids.append(prof.id)
            if ids:
                self._squad_agents["aios"] = ids

        self._loaded = True

    @property
    def active_agent_id(self) -> Optional[str]:
        return self._active_id

    @property
    def general_mode(self) -> bool:
        return self._general_mode

    def get_agent(self, agent_id: Optional[str]) -> Optional[AgentProfile]:
        self.ensure_loaded()
        if not agent_id:
            return None
        return self._agents.get(agent_id.strip().lower())

    def list_agents(self, limit: int = 80) -> List[AgentProfile]:
        self.ensure_loaded()
        chiefs = [a for a in self._agents.values() if a.tier == 0 or "chief" in a.id]
        rest = [a for a in self._agents.values() if a not in chiefs]
        out = sorted(chiefs, key=lambda x: (x.squad, x.name)) + sorted(
            rest, key=lambda x: (x.squad, x.name)
        )
        return out[:limit]

    def _kw_match(self, kw: str, low: str) -> bool:
        k = (kw or "").strip().lower()
        if not k or not low:
            return False
        if len(k) <= 4 or "-" in k:
            return bool(re.search(r"(?<![\w-])" + re.escape(k) + r"(?![\w-])", low, re.I))
        return k in low

    def _marker_match(self, marker: str, low: str, *, min_len: int = 3) -> bool:
        """Match de id/nome de agente com word boundary — evita 'dex' em 'devo'."""
        m = (marker or "").strip().lower()
        if not m or not low or len(m) < min_len:
            return False
        return bool(re.search(r"(?<![\w-])" + re.escape(m) + r"(?![\w-])", low, re.I))

    def _score_reasons(self, text: str, agent: AgentProfile) -> Tuple[float, List[str]]:
        low = (text or "").lower()
        score = 0.0
        reasons: List[str] = []
        squad_kw = _SQUAD_KEYWORDS.get(agent.squad, [])
        for kw in squad_kw:
            if self._kw_match(kw, low):
                score += 3.0
                reasons.append(f"tema «{kw}» → squad {agent.squad}")
        hints = _AIOS_AGENT_HINTS.get(agent.id, [])
        for kw in hints:
            if self._kw_match(kw, low):
                score += 4.0
                reasons.append(f"pedido menciona «{kw}»")
        for kw in agent.keywords[:25]:
            if len(kw) >= 5 and self._kw_match(kw, low):
                score += 1.5
        if agent.squad == "copy-squad" and self._kw_match("copy", low):
            score += 2.0
            reasons.append("tarefa de copywriting")
        if agent.squad == "design-squad" and self._kw_match("design", low):
            score += 2.0
            reasons.append("tarefa de design")
        if _JARVIS_MEDIA_RE.search(low) and agent.squad in ("storytelling", "traffic-masters"):
            score += 3.5
            reasons.append("pedido de mídia / YouTube / co-assistir")
        if _JARVIS_SEARCH_RE.search(low) and agent.squad in ("data-squad", "advisory-board"):
            score += 4.0
            reasons.append("pedido de pesquisa / análise")
            if agent.id in ("board-chair", "data-chief", "ray-dalio"):
                score += 1.5
        # Pesquisa genérica de mundo/tech — preferir advisory/data, não design/copy
        if re.search(r"\b(?:pesquisa|pesquise|busca|busque|o\s+que\s+(?:é|e)\b)", low) and agent.squad in (
            "design-squad", "copy-squad", "copy-master", "brand-squad", "hormozi-squad",
        ):
            score -= 2.0
        if agent.tier == 0 and score >= 3.0:
            score += 1.5
            reasons.append("orquestrador do squad — melhor ponto de entrada")
        for marker in (agent.id, agent.id.replace("-", " "), agent.name.lower()):
            if self._marker_match(marker, low):
                score += 8.0
                reasons.append(f"você citou {agent.name}")
                break
        if agent.tier == 0:
            score += 0.5
        if self._active_id == agent.id:
            score += 6.0
            reasons.append("agente já fixado com /ativar")
        return score, reasons[:5]

    def _score(self, text: str, agent: AgentProfile) -> float:
        return self._score_reasons(text, agent)[0]

    def rank_agents(
        self, user_text: str, *, top: int = 5
    ) -> List[Tuple[float, AgentProfile, List[str]]]:
        self.ensure_loaded()
        ranked: List[Tuple[float, AgentProfile, List[str]]] = []
        for ag in self._agents.values():
            s, reasons = self._score_reasons(user_text, ag)
            if s > 0:
                ranked.append((s, ag, reasons))
        ranked.sort(key=lambda x: (-x[0], x[1].tier, x[1].name))
        return ranked[:top]

    def _find_mentioned_agents(self, text: str) -> List[AgentProfile]:
        self.ensure_loaded()
        low = (text or "").lower()
        found: List[AgentProfile] = []
        seen: set[str] = set()
        for ag in self._agents.values():
            markers = [
                ag.id,
                ag.id.replace("-", " "),
                ag.name.lower(),
            ]
            for m in markers:
                if self._marker_match(m, low) and ag.id not in seen:
                    found.append(ag)
                    seen.add(ag.id)
                    break
        return found

    def _infer_task_summary(self, text: str) -> str:
        raw = (text or "").strip()
        if len(raw) <= 120:
            return raw
        m = re.search(
            r"(?:preciso|quero|vou|fazer|criar|escrever|montar|lançar|lancar)\s+(.{12,100})",
            raw,
            re.I,
        )
        return (m.group(1) if m else raw[:100]).strip().rstrip(".,!?")

    def _why_agent(self, agent: AgentProfile, reasons: List[str]) -> str:
        if reasons:
            return reasons[0]
        if agent.when_to_use:
            return agent.when_to_use[:140]
        if agent.focus:
            return agent.focus[:140]
        return f"especialista em {agent.squad}"

    def format_suggestion(
        self,
        user_text: str,
        *,
        primary: AgentProfile,
        primary_score: float,
        primary_reasons: List[str],
        secondary: Optional[AgentProfile] = None,
        sec_score: float = 0.0,
        sec_reasons: Optional[List[str]] = None,
    ) -> str:
        task = self._infer_task_summary(user_text)
        why = self._why_agent(primary, primary_reasons)
        lines = [
            f"Senhor, analisei o pedido: «{task}».",
            f"Recomendo **{primary.name}** (`{primary.id}`) do {primary.squad} — {why}.",
        ]
        if secondary and sec_score >= primary_score * 0.55:
            sw = self._why_agent(secondary, sec_reasons or [])
            lines.append(
                f"Complemento opcional: **{secondary.name}** (`{secondary.id}`) — {sw}."
            )
        lines.append(
            f"Para fixar: `/ativar {primary.id}`. Posso seguir já nesta persona ou executar a tarefa."
        )
        return " ".join(lines)

    def format_comparison(self, user_text: str, agents: List[AgentProfile]) -> str:
        self.ensure_loaded()
        if len(agents) < 2:
            ranked = self.rank_agents(user_text, top=2)
            if len(ranked) < 2:
                return (
                    "Senhor, não achei dois especialistas claros para comparar. "
                    "Descreva a tarefa ou cite os nomes (ex.: copy-chief ou gary-halbert)."
                )
            agents = [ranked[0][1], ranked[1][1]]
        a, b = agents[0], agents[1]
        sa, ra = self._score_reasons(user_text, a)
        sb, rb = self._score_reasons(user_text, b)
        winner = a if sa >= sb else b
        loser = b if winner is a else a
        w_score = max(sa, sb)
        l_score = min(sa, sb)
        w_reasons = ra if winner is a else rb
        task = self._infer_task_summary(user_text)
        parts = [
            f"Para «{task}», senhor:",
            f"**{a.name}** (`{a.id}`): score {sa:.0f} — {self._why_agent(a, ra)}.",
            f"**{b.name}** (`{b.id}`): score {sb:.0f} — {self._why_agent(b, rb)}.",
        ]
        if w_score > l_score * 1.15:
            parts.append(
                f"Vale mais **{winner.name}** — encaixa melhor neste pedido "
                f"({self._why_agent(winner, w_reasons)})."
            )
        else:
            parts.append(
                f"Empate técnico — use **{winner.name}** como principal; "
                f"**{loser.name}** complementa em revisão."
            )
        parts.append(f"Ativar vencedor: `/ativar {winner.id}`.")
        return " ".join(parts)

    def wants_comparison(self, text: str) -> bool:
        raw = (text or "").strip()
        if not raw:
            return False
        if _COMPARE_RE.search(raw):
            return True
        if len(self._find_mentioned_agents(raw)) >= 2:
            return True
        return bool(
            re.search(r"\b(?:ou|vs)\b", raw, re.I)
            and _ADVISORY_RE.search(raw)
        )

    def wants_explicit_advisory(self, text: str) -> bool:
        raw = (text or "").strip()
        low = raw.lower()
        if low.startswith("/sugerir") or low.startswith("/comparar"):
            return True
        return bool(_ADVISORY_RE.search(raw))

    def should_suggest_on_task(self, text: str) -> bool:
        raw = (text or "").strip()
        if not raw or len(raw) < 12:
            return False
        if self.wants_comparison(raw) or self.wants_explicit_advisory(raw):
            return False
        if not _TASK_INTENT_RE.search(raw):
            return False
        ranked = self.rank_agents(raw, top=1)
        return bool(ranked and ranked[0][0] >= 4.0)

    def build_advisory_block(
        self,
        user_text: str,
        primary: AgentProfile,
        reasons: List[str],
        secondary: Optional[AgentProfile] = None,
    ) -> str:
        task = self._infer_task_summary(user_text)
        lines = [
            "\n\n=== CONTEXTO INTERNO (NUNCA mencionar ao Gustavo) ===",
            f"Tarefa: {task}",
            f"Persona ativa: {primary.name} ({primary.id}) — {primary.squad}",
            f"Motivo: {self._why_agent(primary, reasons)}",
            "Incorpore essa persona no tom e nas decisões. Fale como JARVIS natural — NUNCA diga 'agente', 'especialista', 'orquestrador' nem explique roteamento.",
            "Se ele citar outro agente, compare só se ele perguntar explicitamente qual vale mais.",
        ]
        if secondary:
            lines.append(
                f"Alternativa: {secondary.name} ({secondary.id}) — use só se o pedido mudar de foco."
            )
        return "\n".join(lines)

    def is_ambiguous_ranking(
        self, ranked: List[Tuple[float, AgentProfile, List[str]]]
    ) -> bool:
        if not ranked:
            return True
        if len(ranked) < 2:
            return ranked[0][0] < 5.0
        top, second = ranked[0], ranked[1]
        if top[0] < 5.0:
            return True
        return top[0] - second[0] < 2.0

    async def advisory_llm_why(
        self,
        user_text: str,
        ranked: List[Tuple[float, AgentProfile, List[str]]],
    ) -> Optional[str]:
        """LLM fast explica escolha quando heurística é ambígua."""
        if (os.getenv("JARVIS_ADVISORY_LLM") or "1").strip().lower() in (
            "0",
            "false",
            "no",
            "off",
        ):
            return None
        if not ranked:
            return None
        try:
            from xai_client import get_client, get_fast_model

            lines = [
                f"Pedido do Gustavo: {self._infer_task_summary(user_text)}",
                "Candidatos (heurística):",
            ]
            for score, ag, reasons in ranked[:3]:
                why = reasons[0] if reasons else ag.squad
                lines.append(f"- {ag.name} ({ag.id}) score {score:.0f} — {why}")
            prompt = (
                "Escolha UM especialista para ESTE pedido e explique em 2 frases curtas pt-BR "
                "por que ele vence os outros. Termine com o id entre crases, ex: `copy-chief`."
            )
            client = get_client()
            resp = await client.chat.completions.create(
                model=get_fast_model(),
                messages=[
                    {
                        "role": "system",
                        "content": "Você é J.A.R.V.I.S. roteando especialistas. Seja objetivo.",
                    },
                    {"role": "user", "content": "\n".join(lines) + "\n\n" + prompt},
                ],
                max_tokens=120,
                temperature=0.25,
            )
            text = (resp.choices[0].message.content or "").strip()
            return text if len(text) >= 20 else None
        except Exception as e:
            print(f"[advisory-llm] skip: {e}")
            return None

    async def advisory_reply_async(self, user_text: str) -> Optional[str]:
        """Sugestão/comparação — com LLM quando ranking ambíguo."""
        raw = (user_text or "").strip()
        if not raw:
            return None
        low = raw.lower()
        if low.startswith("/comparar") or self.wants_comparison(raw):
            return self.advisory_reply(raw)
        if not (low.startswith("/sugerir") or self.wants_explicit_advisory(raw)):
            return self.advisory_reply(raw)

        ranked = self.rank_agents(raw, top=3)
        if not ranked:
            return (
                "Senhor, não identifiquei um especialista claro. "
                "Descreva a tarefa (copy, design, código, estratégia…) que eu roteio."
            )
        p_score, p, p_reasons = ranked[0]
        sec = ranked[1][1] if len(ranked) > 1 else None
        s_score = ranked[1][0] if len(ranked) > 1 else 0.0
        s_reasons = ranked[1][2] if len(ranked) > 1 else []
        base = self.format_suggestion(
            raw,
            primary=p,
            primary_score=p_score,
            primary_reasons=p_reasons,
            secondary=sec,
            sec_score=s_score,
            sec_reasons=s_reasons,
        )
        if self.is_ambiguous_ranking(ranked):
            llm = await self.advisory_llm_why(raw, ranked)
            if llm:
                base += f" Análise fina: {llm}"
        return base

    def advisory_reply(self, user_text: str) -> Optional[str]:
        """Resposta direta: sugestão ou comparação (sem LLM)."""
        raw = (user_text or "").strip()
        if not raw:
            return None
        low = raw.lower()
        if low.startswith("/comparar"):
            rest = raw.split(maxsplit=1)[-1] if " " in raw else raw
            mentioned = self._find_mentioned_agents(rest)
            return self.format_comparison(rest, mentioned)
        if self.wants_comparison(raw):
            mentioned = self._find_mentioned_agents(raw)
            return self.format_comparison(raw, mentioned)
        if low.startswith("/sugerir") or self.wants_explicit_advisory(raw):
            ranked = self.rank_agents(raw, top=3)
            if not ranked:
                return (
                    "Senhor, não identifiquei um especialista claro. "
                    "Descreva a tarefa (copy, design, código, estratégia…) que eu roteio."
                )
            p_score, p, p_reasons = ranked[0]
            sec = ranked[1][1] if len(ranked) > 1 else None
            s_score = ranked[1][0] if len(ranked) > 1 else 0.0
            s_reasons = ranked[1][2] if len(ranked) > 1 else []
            return self.format_suggestion(
                raw,
                primary=p,
                primary_score=p_score,
                primary_reasons=p_reasons,
                secondary=sec,
                sec_score=s_score,
                sec_reasons=s_reasons,
            )
        return None

    def select_agent(
        self,
        user_text: str,
        *,
        forced_id: Optional[str] = None,
    ) -> Tuple[Optional[AgentProfile], Optional[AgentProfile], List[str]]:
        """Retorna (agente principal, complementar opcional, motivos do principal)."""
        self.ensure_loaded()
        # /geral desliga pin fixo, mas ALWAYS_ROUTE continua escolhendo especialista por tarefa
        if self._general_mode and not forced_id and not _always_route_agents():
            return None, None, []
        if forced_id:
            ag = self.get_agent(forced_id)
            return ag, None, (["fixado manualmente"] if ag else [])
        if self._active_id and not self._general_mode:
            ag = self.get_agent(self._active_id)
            if ag:
                return ag, None, ["agente fixado com /ativar"]

        ranked = self.rank_agents(user_text, top=5)
        threshold = _route_score_threshold()
        if not ranked or ranked[0][0] < threshold:
            if _always_route_agents():
                # Fallback inteligente por domínio, não só dev
                low = (user_text or "").lower()
                fallback_id = "dev"
                if any(k in low for k in ("pesquisa", "pesquise", "busca", "busque", "relatório", "relatorio", "análise", "analise", "dados", "o que é", "o que e")):
                    fallback_id = "board-chair" if self.get_agent("board-chair") else "data-chief"
                elif any(k in low for k in ("brand", "marca", "branding", "posicionamento", "positioning")):
                    fallback_id = "brand-chief"
                elif any(k in low for k in ("design", "logo", "ui", "ux", "figma", "visual", "layout")):
                    fallback_id = "design-chief"
                elif any(k in low for k in ("copy", "texto", "headline", "anúncio", "anuncio", "roteiro", "vsl")):
                    fallback_id = "copy-chief"
                elif any(k in low for k in ("tráfego", "trafego", "ads", "meta ads", "google ads")):
                    fallback_id = "traffic-chief"
                elif any(k in low for k in ("segurança", "seguranca", "pentest", "hack", "ciber")):
                    fallback_id = "cyber-chief" if self.get_agent("cyber-chief") else "dev"

                fallback = self.get_agent(fallback_id) or self.get_agent("dev")
                if fallback:
                    return fallback, None, [f"modo always-route — fallback {fallback.id}"]
            return None, None, []

        primary = ranked[0][1]
        reasons = ranked[0][2]
        top_score = ranked[0][0]

        import time

        # NÃO auto-fixar: cada pedido re-ranqueia o especialista certo
        # (auto-pin travava tudo em brand-chief etc.). Pin só com /ativar.
        if os.getenv("JARVIS_AUTO_PIN_AGENTS", "0").strip().lower() in (
            "1", "true", "yes", "on",
        ) and top_score >= 4.0 and not self._active_id:
            self._active_id = primary.id
            self._general_mode = False
            self._auto_pin_until = time.time() + 600
            self._save_state()
            reasons = list(reasons) + ["auto-fixado por 10 min (score alto)"]

        secondary = (
            ranked[1][1]
            if len(ranked) > 1 and ranked[1][0] >= ranked[0][0] * 0.65
            else None
        )
        if secondary and secondary.id == primary.id:
            secondary = None
        return primary, secondary, reasons

    def _load_squad_activation(self, squad: str) -> str:
        if squad in self._squad_prompt_cache:
            return self._squad_prompt_cache[squad]
        fname = _SQUAD_PROMPT_FILES.get(squad)
        if not fname:
            return ""
        path = _SQUAD_PROMPTS_DIR / fname
        if not path.is_file():
            return ""
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
            block = _extract_squad_activation(text)
            self._squad_prompt_cache[squad] = block
            return block
        except Exception:
            return ""

    def preferred_tools_for(self, agent_id: str) -> List[str]:
        return list(_AGENT_PREFERRED_TOOLS.get((agent_id or "").strip().lower(), []))

    def build_persona_block(
        self,
        primary: AgentProfile,
        secondary: Optional[AgentProfile] = None,
    ) -> str:
        lines = [
            "\n\n=== MODO ORQUESTRADOR — PERSONA ATIVA ===",
            "Você é J.A.R.V.I.S. atuando como ORQUESTRADOR: empresta a voz do especialista abaixo.",
            "Responda INTEIRAMENTE na persona — tom, vocabulário, estilo. Mantenha pt-BR natural.",
            "Para ações no PC (tools), execute como JARVIS mas NARRE na voz do especialista.",
            f"\nAGENTE ATIVO: {primary.name} ({primary.id}) | Squad: {primary.squad} | Fonte: {primary.source}",
        ]
        if primary.title:
            lines.append(f"Título: {primary.title}")
        if primary.role:
            lines.append(f"Papel: {primary.role}")
        if primary.tone:
            lines.append(f"Tom: {primary.tone}")
        if primary.style:
            lines.append(f"Estilo: {primary.style[:400]}")
        if primary.focus:
            lines.append(f"Foco: {primary.focus}")
        if primary.when_to_use:
            lines.append(f"Quando usar: {primary.when_to_use[:300]}")
        if primary.greeting and len(primary.greeting) < 220:
            lines.append(f"Referência de abertura (adapte, não copie literal): {primary.greeting}")
        if secondary:
            lines.append(
                f"\nCOMPLEMENTO: perspectiva de {secondary.name} ({secondary.id}) pode enriquecer — "
                f"mencione só se relevante."
            )
        # Compacto em Ollama (ctx 8k); denso em Gemini/cloud
        _compact = os.getenv("JARVIS_LLM_PROVIDER", "ollama").strip().lower() in (
            "ollama", "local", "hermes",
        ) or os.getenv("JARVIS_COMPACT_PERSONA", "1").strip().lower() in (
            "1", "true", "yes", "on",
        )
        know_cap = 800 if _compact else 2000
        act_cap = 1000 if _compact else 3200
        # Squad activation primeiro (mais estável), depois knowledge do agente
        squad_act = self._load_squad_activation(primary.squad)
        if squad_act:
            lines.append(
                f"\nSQUAD ACTIVATION (Xquads — use este conhecimento de squad):\n{squad_act[:act_cap]}"
            )
        if primary.knowledge:
            lines.append(
                "\nCONHECIMENTO DO AGENTE (Xquads — frameworks, routing e playbook; aplique de verdade):\n"
                f"{primary.knowledge[:know_cap]}"
            )
        pref = self.preferred_tools_for(primary.id)
        if pref:
            lines.append(
                f"\nFERRAMENTAS PREFERIDAS deste especialista: {', '.join(pref)} "
                "(use quando fizer sentido; outras tools seguem disponíveis)."
            )
        lines.append(
            "\nREGRAS: não quebre o personagem; recuse fora do escopo NA VOZ do agente; "
            "seja esperto e profundo — raciocine com o conhecimento do squad/agente, não genérico; "
            "mesmo nível de profundidade de um especialista sênior (frameworks, trade-offs, próximos passos)."
        )
        return "\n".join(lines)

    def handle_command(self, text: str) -> Optional[str]:
        raw = (text or "").strip()
        low = raw.lower()

        if low in ("/agentes", "agentes", "lista agentes", "listar agentes"):
            self.ensure_loaded()
            squads: Dict[str, List[AgentProfile]] = {}
            for ag in self.list_agents(120):
                squads.setdefault(ag.squad, []).append(ag)
            parts = [
                f"Senhor, tenho {len(self._agents)} especialistas AIOS + Xquads disponíveis.",
                "Use /ativar [nome] para fixar um agente, /quem para ver o ativo, /geral para modo livre.",
                "",
            ]
            for squad, agents in sorted(squads.items()):
                parts.append(f"**{squad}** ({len(agents)}):")
                for ag in agents[:8]:
                    parts.append(f"  • {ag.name} (`{ag.id}`)")
                if len(agents) > 8:
                    parts.append(f"  … e mais {len(agents) - 8}")
                parts.append("")
            return "\n".join(parts).strip()

        if low.startswith("/ativar ") or low.startswith("ativar agente "):
            key = raw.split(maxsplit=1)[-1].strip().lower() if " " in raw else ""
            self.ensure_loaded()
            ag = self.get_agent(key)
            if not ag:
                for cand in self._agents.values():
                    if key in cand.id or key in cand.name.lower():
                        ag = cand
                        break
            if not ag:
                return f"Não encontrei o agente '{key}', senhor. Digite /agentes para ver a lista."
            self._active_id = ag.id
            self._general_mode = False
            self._save_state()
            return (
                f"Ativado: **{ag.name}** ({ag.id}) — {ag.squad}. "
                f"A partir de agora respondo na persona desse especialista."
            )

        if low in ("/quem", "quem está ativo", "qual agente"):
            if self._general_mode:
                return "Modo geral ativo — sem persona fixa, senhor."
            ag = self.get_agent(self._active_id)
            if ag:
                return f"Agente ativo: **{ag.name}** (`{ag.id}`) — {ag.squad}."
            return "Nenhum agente fixo — roteamento automático por pergunta."

        if low in ("/geral", "modo geral"):
            self._general_mode = True
            self._active_id = None
            self._save_state()
            return "Modo geral ativado, senhor. Personas desativadas até novo /ativar."

        if low.startswith("/sugerir") or low.startswith("/comparar"):
            reply = self.advisory_reply(raw)
            if reply:
                return reply

        return None

    def resolve_for_turn(
        self, user_text: str
    ) -> Tuple[Optional[AgentProfile], Optional[AgentProfile], List[str]]:
        if self.handle_command(user_text):
            return None, None, []
        return self.select_agent(user_text)

    def status_dict(self) -> Dict[str, Any]:
        self.ensure_loaded()
        ag = self.get_agent(self._active_id)
        return {
            "loaded": self._loaded,
            "total_agents": len(self._agents),
            "squads": list(self._squad_agents.keys()),
            "xquads_path": str(_XQUADS),
            "aios_path": str(_AIOS),
            "xquads_available": _XQUADS.is_dir(),
            "aios_available": _AIOS.is_dir(),
            "general_mode": self._general_mode,
            "active_agent_id": self._active_id,
            "active_agent_name": ag.name if ag else None,
        }


_orch: Optional[AgentOrchestrator] = None


def get_orchestrator() -> AgentOrchestrator:
    global _orch
    if _orch is None:
        _orch = AgentOrchestrator()
    return _orch