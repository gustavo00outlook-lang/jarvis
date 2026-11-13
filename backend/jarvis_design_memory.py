"""
Memória de design do JARVIS — análises @agenciasetup, padrões Calango Studio,
persona Senior Design PhD. Tudo persiste no Obsidian para evolução contínua.
"""

import os
import re
from datetime import datetime
from typing import List, Optional

import obsidian_notes

DESIGN_SUBDIR = os.path.join("JARVIS", "cerebro", "Projetos", "Design")
DESIGN_MASTER = os.path.join(DESIGN_SUBDIR, "JARVIS-Senior-Design-PhD.md")
STUDIO_REF = os.path.join(DESIGN_SUBDIR, "CALANGO-STUDIO-MODO-STUDIO.md")
IG_ANALYSIS = os.path.join(DESIGN_SUBDIR, "DESIGN-agenciasetup-analise-posts.md")

CATEGORIES = ("tipografia", "cor", "textura", "layout", "carrossel", "cta", "marca", "geral")


def _vault_path(rel: str) -> str:
    return os.path.join(obsidian_notes.VAULT, rel.replace("/", os.sep))


def save_design_knowledge(
    title: str,
    content: str,
    category: str = "geral",
    source: str = "analise",
    tags: Optional[str] = None,
) -> str:
    """Salva insight de design em memoria/Design/."""
    cat = category if category in CATEGORIES else "geral"
    tag_list = ["design", "calango", cat]
    if tags:
        tag_list.extend(t.strip().lstrip("#") for t in tags.split(",") if t.strip())
    body = f"**Categoria:** {cat}\n**Fonte:** {source}\n\n{content.strip()}\n"
    return obsidian_notes._write_note(DESIGN_SUBDIR, title, body, "design-memory", tag_list)


def append_to_ig_analysis(section: str) -> str:
    """Append em DESIGN-agenciasetup-analise-posts.md (cria se não existir)."""
    path = _vault_path(IG_ANALYSIS)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    now = datetime.now()
    block = f"\n\n## {now:%Y-%m-%d %H:%M}\n{section.strip()}\n"

    if os.path.isfile(path):
        with open(path, "a", encoding="utf-8") as f:
            f.write(block)
    else:
        header = (
            "---\n"
            f"created: {now:%Y-%m-%d}\n"
            "source: jarvis-design\n"
            "tags: [jarvis, design, agenciasetup, instagram, calango]\n"
            "---\n\n"
            "# @agenciasetup — análise de posts (evolução contínua)\n\n"
            "> Perfil: Calango | Agência Setup — referência visual da marca.\n"
            "> Para carrosséis: use `browse_carousel_slide` ou `?img_index=N` na URL.\n"
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(header + block)

    return f"Análise atualizada: {IG_ANALYSIS}"


def load_design_context(max_chars: int = 3200) -> str:
    """Carrega persona PhD + refs Studio + trecho da análise IG para o agente."""
    parts: List[str] = []
    for rel in (DESIGN_MASTER, STUDIO_REF):
        path = _vault_path(rel)
        if not os.path.isfile(path):
            continue
        try:
            text = open(path, "r", encoding="utf-8", errors="replace").read()
            if text.startswith("---"):
                end = text.find("---", 3)
                if end > 0:
                    text = text[end + 3 :].strip()
            parts.append(text[:1600])
        except Exception:
            continue

    ig_path = _vault_path(IG_ANALYSIS)
    if os.path.isfile(ig_path):
        try:
            text = open(ig_path, "r", encoding="utf-8", errors="replace").read()
            parts.append("Últimas análises @agenciasetup:\n" + text[-1200:])
        except Exception:
            pass

    combined = "\n\n---\n\n".join(parts)
    return combined[:max_chars]


def search_design_notes(query: str, limit: int = 4) -> str:
    """Busca só em memoria/Design/."""
    folder = _vault_path(DESIGN_SUBDIR)
    if not os.path.isdir(folder):
        return "Pasta Design vazia — ainda sem notas."
    terms = [t for t in re.split(r"\W+", (query or "").lower()) if len(t) > 2]
    if not terms:
        return "Consulta vazia."
    scored = []
    for name in os.listdir(folder):
        if not name.endswith(".md"):
            continue
        path = os.path.join(folder, name)
        try:
            text = open(path, "r", encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        low = text.lower()
        score = sum(low.count(t) for t in terms)
        if score <= 0:
            continue
        snippet = " ".join(text.split())[:300]
        scored.append((score, name, snippet))
    if not scored:
        return f"Nada em Design sobre: {query}"
    scored.sort(reverse=True)
    lines = [f"{len(scored)} nota(s) de design:"]
    for _, name, snippet in scored[:limit]:
        lines.append(f"--- {name}\n{snippet}")
    return "\n".join(lines)