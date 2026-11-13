"""
Integração com o vault Obsidian do Gustavo.

Cérebro canônico: JARVIS/cerebro/
- Aprendizados — pesquisas, estudos, reflexões
- Preferencias — o que o Gustavo ensina (prefs, fatos, estilo)
- Conversas — log diário
- Projetos — Design, reforço multi-agente, dev JARVIS

Antes de salvar: consulta search_obsidian; se já existe → atualiza em vez de duplicar.
"""

import math
import os
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

VAULT = str(Path.home() / "Documents" / "JARVIS-notes")
CEREBRO = os.path.join("JARVIS", "cerebro")
APRENDIZADOS = os.path.join(CEREBRO, "Aprendizados")
PREFERENCIAS = os.path.join(CEREBRO, "Preferencias")
CONVERSAS_SUBDIR = os.path.join(CEREBRO, "Conversas")
PROJETOS = os.path.join(CEREBRO, "Projetos")
REFLECT_SUBDIR = os.path.join(APRENDIZADOS, "Reflexoes")
WATCH_REPORTS_SUBDIR = os.path.join(APRENDIZADOS, "CoAssistir")
PROJETOS_DESIGN = os.path.join(PROJETOS, "Design")
PROJETOS_REFORCO = os.path.join(PROJETOS, "Reforco-Multi-Agente")
BRAIN_INDEX = os.path.join(CEREBRO, "00-INDICE.md")
CALANGO_REF = os.path.join(APRENDIZADOS, "CALANGO-STUDIO-ATUAL.md")

# Aliases legado (memoria/ ainda indexada até migração completa)
TEACH_SUBDIR = PREFERENCIAS
NOTES_SUBDIR = APRENDIZADOS
REFORCO_SUBDIR = PROJETOS_REFORCO
LEGACY_MEMORIA = os.path.join("JARVIS", "memoria")
LEGACY_APRENDIZADO = os.path.join("JARVIS", "Aprendizado")
LEGACY_REFLECT = os.path.join("JARVIS", "Reflexões")
LEGACY_BRAIN = os.path.join(LEGACY_MEMORIA, "00-CEREBRO-JARVIS.md")

SEARCH_DIRS = [
    CEREBRO,
]
MAX_SEARCH_FILES = 80


def _slug(text: str, max_len: int = 60) -> str:
    text = re.sub(r"[<>:\"/\\|?*\n\r]", "", text).strip()
    text = re.sub(r"\s+", " ", text)
    return text[:max_len].strip() or "nota"


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("---", 3)
        if end > 0:
            return text[end + 3 :].strip()
    return text


def _content_needle(text: str, max_len: int = 200) -> str:
    body = _strip_frontmatter(text or "")
    return " ".join(body.lower().split())[:max_len]


def _scan_folder_for_needle(folder_abs: str, needle: str) -> Optional[str]:
    if len(needle) < 8 or not os.path.isdir(folder_abs):
        return None
    try:
        for fn in sorted(os.listdir(folder_abs), reverse=True):
            if not fn.endswith(".md"):
                continue
            path = os.path.join(folder_abs, fn)
            body = _content_needle(open(path, encoding="utf-8", errors="replace").read())
            if needle in body:
                return os.path.relpath(path, VAULT)
    except Exception:
        pass
    return None


def note_already_exists(
    folder_rel: str,
    content: str,
    title: str = "",
    window: int = 200,
) -> Optional[str]:
    """Retorna path relativo se conteúdo/título similar já existe no vault."""
    if not vault_available():
        return None
    needle = _content_needle(content, window)
    if len(needle) >= 8:
        for sub in (folder_rel, APRENDIZADOS, PREFERENCIAS, PROJETOS):
            hit = _scan_folder_for_needle(os.path.join(VAULT, sub), needle)
            if hit:
                return hit
    if title:
        slug = _slug(title).lower()
        folder_abs = os.path.join(VAULT, folder_rel)
        try:
            for fn in os.listdir(folder_abs):
                if not fn.endswith(".md"):
                    continue
                if slug in fn.lower():
                    return os.path.join(folder_rel, fn).replace("\\", "/")
        except Exception:
            pass
    return None


def consult_before_save(title: str, content: str, folder_rel: str = "") -> Optional[str]:
    """Consulta memória cerebro/ antes de salvar — retorna path para atualizar."""
    folders = []
    if folder_rel:
        folders.append(folder_rel)
    for f in (APRENDIZADOS, PREFERENCIAS, PROJETOS, REFLECT_SUBDIR, PROJETOS_DESIGN):
        if f not in folders:
            folders.append(f)
    for folder in folders:
        hit = note_already_exists(folder, content, title)
        if hit:
            return hit
    return None


def _update_existing_note(rel_path: str, title: str, content: str, source: str) -> str:
    """Atualiza nota existente (append) em vez de criar duplicata."""
    path = os.path.join(VAULT, rel_path.replace("/", os.sep))
    if not os.path.isfile(path):
        return _write_note(APRENDIZADOS, title, content, source, ["aprendizado"], dedup=False)
    now = datetime.now()
    try:
        old = open(path, encoding="utf-8", errors="replace").read()
    except Exception:
        return f"Erro ao ler nota existente: {rel_path}"
    needle = _content_needle(content, 200)
    if len(needle) >= 12 and needle in _content_needle(old, max(len(old), 4000)):
        return f"Já consta na memória (sem duplicar): {rel_path}"
    block = (
        f"\n\n## Atualização {now:%Y-%m-%d %H:%M}\n"
        f"*source: {source}*\n\n"
        f"{content.strip()}\n"
    )
    with open(path, "a", encoding="utf-8") as f:
        f.write(block)
    return f"Nota atualizada no Obsidian: {rel_path}"


def vault_available() -> bool:
    return os.path.isdir(VAULT)


def _write_note(
    folder_rel: str,
    title: str,
    content: str,
    source: str,
    tag_list: List[str],
    dedup: bool = True,
) -> str:
    if not content or not content.strip():
        return "Nada para salvar (conteúdo vazio)."
    if not vault_available():
        return f"Vault Obsidian não encontrado em {VAULT}."

    if dedup:
        existing = consult_before_save(title, content, folder_rel)
        if existing:
            return _update_existing_note(existing, title, content, source)

    folder = os.path.join(VAULT, folder_rel)
    os.makedirs(folder, exist_ok=True)

    now = datetime.now()
    base = f"{now:%Y-%m-%d} {_slug(title)}"
    path = os.path.join(folder, base + ".md")
    if os.path.exists(path):
        path = os.path.join(folder, f"{base} {now:%H%M%S}.md")

    tags = list(dict.fromkeys(["jarvis"] + [t.lstrip("#") for t in tag_list if t]))

    note = (
        "---\n"
        f"created: {now:%Y-%m-%d %H:%M}\n"
        f"source: {source}\n"
        f"tags: [{', '.join(tags)}]\n"
        "---\n\n"
        f"# {title.strip() or 'Nota do JARVIS'}\n\n"
        f"{content.strip()}\n"
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write(note)

    rel = os.path.relpath(path, VAULT)
    return f"Nota salva no Obsidian: {rel}"


def save_note(
    title: str,
    content: str,
    source: str = "jarvis",
    tags: Optional[str] = None,
    subdir: Optional[str] = None,
) -> str:
    """Salva nota em Aprendizado (ou subdir legado)."""
    tag_list = ["aprendizado"]
    if tags:
        tag_list.extend(t.strip().lstrip("#") for t in tags.split(",") if t.strip())
    folder = subdir or NOTES_SUBDIR
    return _write_note(folder, title, content, source, tag_list)


def save_note_if_new(
    title: str,
    content: str,
    source: str = "jarvis",
    tags: Optional[str] = None,
    subdir: Optional[str] = None,
) -> str:
    """Salva ou atualiza se já existe (consulta antes)."""
    return save_or_update_note(title, content, source, tags, subdir)


def save_or_update_note(
    title: str,
    content: str,
    source: str = "jarvis",
    tags: Optional[str] = None,
    subdir: Optional[str] = None,
) -> str:
    """Consulta memória → atualiza nota existente ou cria nova."""
    folder = subdir or NOTES_SUBDIR
    existing = consult_before_save(title, content, folder)
    if existing:
        return _update_existing_note(existing, title, content, source)
    tag_list = ["aprendizado"]
    if tags:
        tag_list.extend(t.strip().lstrip("#") for t in tags.split(",") if t.strip())
    return _write_note(folder, title, content, source, tag_list, dedup=False)


def teaching_already_known(content: str) -> bool:
    """True se preferência/fato já está na memória."""
    needle = _content_needle(content, 160)
    for folder in (PREFERENCIAS, os.path.join(LEGACY_MEMORIA, "Ensinando-JARVIS")):
        if _scan_folder_for_needle(os.path.join(VAULT, folder), needle):
            return True
    return False


def save_teaching(title: str, content: str, category: str = "fato") -> str:
    """Salva em Preferencias — consulta antes; atualiza se já sabe."""
    body = f"**Categoria:** {category}\n\n{content.strip()}"
    existing = consult_before_save(title, body, PREFERENCIAS)
    if existing:
        return _update_existing_note(existing, title, body, "ensinando")
    tags = ["preferencia", "ensinando-jarvis", category]
    if category in ("preferencia", "estilo"):
        tags.append("preferencia")
    return _write_note(PREFERENCIAS, title, body, "ensinando", tags, dedup=False)


_SEM_INDEX_CACHE: Dict[str, object] = {"at": 0.0, "docs": []}
_SEM_TTL_SEC = 300


def _memory_tokenize(text: str) -> List[str]:
    return [t for t in re.split(r"\W+", (text or "").lower()) if len(t) > 2]


def _iter_memory_corpus_files() -> List[str]:
    roots = [
        os.path.join(VAULT, PREFERENCIAS),
        os.path.join(VAULT, CONVERSAS_SUBDIR),
        os.path.join(VAULT, APRENDIZADOS),
        os.path.join(VAULT, CEREBRO),
        os.path.join(VAULT, LEGACY_MEMORIA),
    ]
    out: List[str] = []
    seen: set[str] = set()
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, _, files in os.walk(root):
            for fn in files:
                if not fn.endswith(".md"):
                    continue
                path = os.path.join(dirpath, fn)
                if path in seen:
                    continue
                seen.add(path)
                out.append(path)
                if len(out) >= 280:
                    return out
    return out


def _build_semantic_index() -> List[Dict[str, object]]:
    now = time.time()
    cached = _SEM_INDEX_CACHE.get("docs")
    if cached and now - float(_SEM_INDEX_CACHE.get("at") or 0) < _SEM_TTL_SEC:
        return cached  # type: ignore[return-value]

    docs: List[Dict[str, object]] = []
    df: Counter[str] = Counter()
    raw_docs: List[Tuple[str, str, List[str]]] = []

    for path in _iter_memory_corpus_files():
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        if len(text) < 40:
            continue
        tokens = _memory_tokenize(text)
        if len(tokens) < 8:
            continue
        rel = os.path.relpath(path, VAULT).replace("\\", "/")
        raw_docs.append((rel, text, tokens))
        df.update(set(tokens))

    n_docs = max(len(raw_docs), 1)
    for rel, text, tokens in raw_docs:
        tf = Counter(tokens)
        vec: Dict[str, float] = {}
        for term, cnt in tf.items():
            idf = math.log((1 + n_docs) / (1 + df[term])) + 1.0
            vec[term] = (cnt / len(tokens)) * idf
        docs.append({"path": rel, "text": text, "vec": vec})

    _SEM_INDEX_CACHE["at"] = now
    _SEM_INDEX_CACHE["docs"] = docs
    return docs


def semantic_memory_search(
    query: str, *, top_k: int = 3, min_score: float = 0.06
) -> List[Tuple[str, str, float]]:
    """Busca semântica leve (TF-IDF) no vault — complementa memory_knows_about."""
    q = (query or "").strip()
    if len(q) < 8:
        return []
    q_tokens = _memory_tokenize(q)
    if not q_tokens:
        return []

    docs = _build_semantic_index()
    if not docs:
        return []

    q_tf = Counter(q_tokens)
    q_vec: Dict[str, float] = {}
    for term, cnt in q_tf.items():
        q_vec[term] = cnt / len(q_tokens)

    ranked: List[Tuple[float, str, str]] = []
    for doc in docs:
        vec = doc.get("vec") or {}
        if not isinstance(vec, dict):
            continue
        score = 0.0
        for term, w in q_vec.items():
            score += w * float(vec.get(term, 0.0))
        if score < min_score:
            continue
        text = str(doc.get("text") or "")
        rel = str(doc.get("path") or "")
        idx = min((text.lower().find(t) for t in q_tokens if t in text.lower()), default=0)
        snippet = " ".join(text[max(0, idx - 30) : idx + 220].split())
        ranked.append((score, rel, snippet))

    ranked.sort(key=lambda x: -x[0])
    return [(r, s, sc) for sc, r, s in ranked[:top_k]]


def memory_knows_about(topic: str) -> Tuple[bool, str]:
    """Consulta cerebro/ antes de agir/perguntar. Retorna (sabe, snippet)."""
    q = (topic or "").strip()
    if len(q) < 6:
        return False, ""
    terms = [t for t in re.split(r"\W+", q.lower()) if len(t) > 2][:6]
    if not terms:
        return False, ""
    best: Tuple[float, str, str] = (0.0, "", "")
    cerebro_root = os.path.join(VAULT, CEREBRO)
    if not os.path.isdir(cerebro_root):
        return False, ""
    for path in _iter_note_files():
        rel = path.replace("\\", "/")
        if "/cerebro/" not in rel and not rel.endswith("/cerebro"):
            continue
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        low = text.lower()
        score = sum(low.count(t) for t in terms)
        if score <= 0:
            continue
        idx = min((low.find(t) for t in terms if t in low), default=0)
        snippet = " ".join(text[max(0, idx - 40) : idx + 240].split())
        rel_path = os.path.relpath(path, VAULT).replace("\\", "/")
        if score > best[0]:
            best = (score, rel_path, snippet)
    if best[0] <= 0:
        return False, ""
    return True, f"{best[1]}: {best[2]}"


def save_reflection(title: str, content: str) -> str:
    return _write_note(REFLECT_SUBDIR, title, content, "reflexao", ["reflexao"], dedup=True)


def save_watch_report(
    title: str,
    *,
    source_url: str = "",
    user_request: str = "",
    narrations: Optional[List[str]] = None,
    summary: str = "",
) -> str:
    """Relatório estruturado pós sessão de co-assistir vídeo."""
    narrations = narrations or []
    parts = [
        f"**Pedido:** {(user_request or '').strip()[:600]}",
        f"**Fonte:** {source_url or 'painel JARVIS'}",
        "",
        "## Comentários ao vivo",
    ]
    if narrations:
        for i, line in enumerate(narrations, 1):
            parts.append(f"{i}. {line.strip()}")
    else:
        parts.append("(sem narrações capturadas)")
    if summary:
        parts.extend(["", "## Resumo / análise", summary.strip()])
    body = "\n".join(parts)
    safe_title = title.strip() or "Sessão co-assistir"
    return _write_note(
        WATCH_REPORTS_SUBDIR,
        safe_title,
        body,
        "cowatch",
        ["cowatch", "video", "relatorio"],
        dedup=False,
    )


def save_conversation_turn(
    user_text: str,
    jarvis_response: str,
    tools_used: Optional[List[str]] = None,
) -> str:
    """Append em log diário — toda conversa com o JARVIS."""
    if not vault_available():
        return ""
    folder = os.path.join(VAULT, CONVERSAS_SUBDIR)
    os.makedirs(folder, exist_ok=True)
    now = datetime.now()
    path = os.path.join(folder, f"{now:%Y-%m-%d}.md")

    tools_line = ""
    if tools_used:
        tools_line = f" | tools: {', '.join(tools_used[:6])}"

    entry = (
        f"\n\n## {now:%H:%M:%S}\n"
        f"**Gustavo:** {user_text.strip()[:800]}\n\n"
        f"**JARVIS:** {jarvis_response.strip()[:1200]}{tools_line}\n"
    )

    if os.path.exists(path):
        with open(path, "a", encoding="utf-8") as f:
            f.write(entry)
    else:
        header = (
            "---\n"
            f"created: {now:%Y-%m-%d}\n"
            "source: jarvis-auto\n"
            "tags: [jarvis, conversa, auto-save]\n"
            "---\n\n"
            f"# Conversas JARVIS — {now:%Y-%m-%d}\n"
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(header + entry)

    return os.path.relpath(path, VAULT)


def load_calango_reference(max_chars: int = 900) -> str:
    """Carrega nota canônica Calango Studio para o agente."""
    path = os.path.join(VAULT, CALANGO_REF.replace("/", os.sep))
    if not os.path.isfile(path):
        return ""
    try:
        text = open(path, "r", encoding="utf-8", errors="replace").read()
        if text.startswith("---"):
            end = text.find("---", 3)
            if end > 0:
                text = text[end + 3 :].strip()
        return text[:max_chars]
    except Exception:
        return ""


def _iter_note_files(include_reviews: bool = False) -> List[str]:
    files: List[str] = []
    seen = set()
    for sub in SEARCH_DIRS:
        root = os.path.join(VAULT, sub)
        if not os.path.isdir(root):
            continue
        for dirpath, _, names in os.walk(root):
            rel = dirpath.replace("\\", "/")
            if "_arquivo" in rel:
                continue
            if not include_reviews and ("/reviews" in rel or rel.endswith("/reviews")):
                continue
            for n in names:
                if n.endswith(".md"):
                    p = os.path.join(dirpath, n)
                    if p not in seen:
                        seen.add(p)
                        files.append(p)
    # Prioriza Ensinando-JARVIS no sort (mais recente dentro de cada grupo)
    def sort_key(p: str) -> Tuple[int, float]:
        rel = p.replace("\\", "/")
        priority = 0
        if "Preferencias" in rel or "Ensinando-JARVIS" in rel:
            priority = 4
        elif "Aprendizados" in rel or "Aprendizado" in rel:
            priority = 3
        elif "Conversas" in rel:
            priority = 2
        elif "Reflex" in rel:
            priority = 1
        return (priority, os.path.getmtime(p))

    files.sort(key=sort_key, reverse=True)
    return files[:MAX_SEARCH_FILES]


_PREF_QUERY_MARKERS = (
    "favorit", "prefiro", "gosto", "lembre", "ensin", "cor ", "nome ",
    "empresa", "calango", "estilo", "sempre", "nunca",
)


def search_notes(query: str, limit: int = 5) -> str:
    if not vault_available():
        return f"Vault Obsidian não encontrado em {VAULT}."
    terms = [t for t in re.split(r"\W+", (query or "").lower()) if len(t) > 2]
    if not terms:
        return "Consulta vazia."

    qlow = (query or "").lower()
    prefer_teach = any(m in qlow for m in _PREF_QUERY_MARKERS)

    scored: List[Tuple[float, str, str]] = []
    for path in _iter_note_files(include_reviews=not prefer_teach):
        try:
            text = open(path, "r", encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        low = text.lower()
        name_low = os.path.basename(path).lower()
        score = sum(low.count(t) for t in terms) + sum(3 for t in terms if t in name_low)
        rel_path = path.replace("\\", "/")
        if "Preferencias" in rel_path or "Ensinando-JARVIS" in rel_path:
            score += 40 if prefer_teach else 25
        if "ensinando-jarvis" in low:
            score += 10
        if "Projetos/Design" in rel_path.replace("\\", "/") or "memoria/Design" in rel_path.replace("\\", "/"):
            if any(t in qlow for t in ("design", "agenciasetup", "studio", "tipografia", "carrossel", "mockup")):
                score += 35
        if score <= 0:
            continue
        idx = min((low.find(t) for t in terms if t in low), default=0)
        start = max(0, idx - 80)
        snippet = " ".join(text[start : start + 420].split())
        scored.append((score, os.path.relpath(path, VAULT), snippet))

    if not scored:
        return f"Nada encontrado na memória sobre: {query}"
    scored.sort(reverse=True)
    out = [f"{len(scored)} nota(s) relevantes na memória:"]
    for _, rel, snippet in scored[:limit]:
        out.append(f"--- {rel}\n{snippet}")
    return "\n".join(out)


def recent_notes_index(n: int = 6) -> str:
    if not vault_available():
        return ""
    names = [os.path.relpath(p, VAULT) for p in _iter_note_files()[:n]]
    return "; ".join(names)


def load_brain_summary(max_chars: int = 2200) -> str:
    """Resumo do índice cerebro/00-INDICE.md para contexto do agente."""
    if not vault_available():
        return ""
    path = os.path.join(VAULT, BRAIN_INDEX)
    if not os.path.isfile(path):
        path = os.path.join(VAULT, LEGACY_BRAIN)
    if not os.path.isfile(path):
        return ""
    try:
        text = open(path, "r", encoding="utf-8", errors="replace").read()
        body = re.sub(r"^---.*?---\s*", "", text, count=1, flags=re.DOTALL).strip()
        if len(body) > max_chars:
            body = body[:max_chars] + " [...]"
        return f"Cérebro JARVIS (resumo Obsidian):\n{body}"
    except Exception:
        return ""


def load_recent_conversation_log(days_back: int = 5, max_entries: int = 14, max_chars: int = 4200) -> str:
    """Carrega conversas salvas em memoria/Conversas/ para o JARVIS lembrar do que já falaram."""
    if not vault_available():
        return ""
    folder = os.path.join(VAULT, CONVERSAS_SUBDIR)
    if not os.path.isdir(folder):
        return ""

    from datetime import timedelta

    now = datetime.now()
    files: List[str] = []
    for d in range(days_back):
        day = now - timedelta(days=d)
        path = os.path.join(folder, f"{day:%Y-%m-%d}.md")
        if os.path.isfile(path):
            files.append(path)

    if not files:
        return ""

    entries: List[str] = []
    for path in sorted(files, reverse=True):
        try:
            text = open(path, "r", encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        parts = re.split(r"\n## \d{2}:\d{2}:\d{2}\n", text)
        for block in parts[1:]:
            block = block.strip()
            if not block:
                continue
            one = " ".join(block.split())[:380]
            if one:
                entries.append(one)
        if len(entries) >= max_entries:
            break

    if not entries:
        return ""

    entries = list(reversed(entries[-max_entries:]))
    body = "\n".join(f"- {e}" for e in entries)
    if len(body) > max_chars:
        body = body[-max_chars:]
    return f"Conversas recentes com o Gustavo (Obsidian cerebro/Conversas):\n{body}"


def load_teaching_index(n: int = 10) -> str:
    """Resumo das preferências em cerebro/Preferencias para o system prompt."""
    teach_dir = os.path.join(VAULT, PREFERENCIAS)
    if not os.path.isdir(teach_dir):
        teach_dir = os.path.join(VAULT, os.path.join(LEGACY_MEMORIA, "Ensinando-JARVIS"))
    if not os.path.isdir(teach_dir):
        return ""
    files = sorted(
        [os.path.join(teach_dir, f) for f in os.listdir(teach_dir) if f.endswith(".md")],
        key=os.path.getmtime,
        reverse=True,
    )[:n]
    lines = []
    for path in files:
        try:
            text = open(path, "r", encoding="utf-8", errors="replace").read()
            title = os.path.basename(path).replace(".md", "")
            snippet = " ".join(text.split())[:120]
            lines.append(f"- {title}: {snippet}")
        except Exception:
            continue
    return "\n".join(lines)


def weekly_vault_review(days_back: int = 7) -> str:
    """Revisão semanal do vault — workflow segundo cérebro (Felipe Tâmbara)."""
    if not vault_available():
        return f"Vault Obsidian não encontrado em {VAULT}."

    from datetime import timedelta

    now = datetime.now()
    conv_folder = os.path.join(VAULT, CONVERSAS_SUBDIR)
    learnings: List[str] = []
    decisions: List[str] = []
    open_loops: List[str] = []

    for d in range(days_back):
        day = now - timedelta(days=d)
        path = os.path.join(conv_folder, f"{day:%Y-%m-%d}.md")
        if not os.path.isfile(path):
            continue
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        for block in re.split(r"\n## \d{2}:\d{2}:\d{2}\n", text)[1:]:
            block_l = block.lower()
            if "jarvis:" in block:
                resp = block.split("**JARVIS:**", 1)[-1].split("\n", 1)[0][:200]
                learnings.append(resp.strip())
            if any(w in block_l for w in ("decidi", "vou ", "prefiro", "teach", "aprend")):
                decisions.append(" ".join(block.split())[:180])
            if any(w in block_l for w in ("depois", "amanhã", "pendente", "falta", "próximo")):
                open_loops.append(" ".join(block.split())[:160])

    recent_learn = _iter_note_files()[:8]
    learn_files = [
        os.path.relpath(p, VAULT).replace("\\", "/")
        for p in recent_learn
        if "Aprendizados" in p.replace("\\", "/")
    ]

    parts = [
        f"# Revisão semanal vault — {now:%Y-%m-%d}",
        "",
        "## O que avançou (conversas)",
    ]
    if learnings:
        parts.extend(f"- {x}" for x in learnings[-6:])
    else:
        parts.append("- (poucas conversas registradas nesta semana)")

    parts.extend(["", "## Aprendizados recentes no vault"])
    if learn_files:
        parts.extend(f"- [[{f}]]" for f in learn_files[:6])
    else:
        parts.append("- (nenhum)")

    parts.extend(["", "## Decisões / ensinos capturados"])
    if decisions:
        parts.extend(f"- {x}" for x in decisions[-5:])
    else:
        parts.append("- (nenhum explícito)")

    parts.extend(["", "## Loops abertos"])
    if open_loops:
        parts.extend(f"- {x}" for x in open_loops[-5:])
    else:
        parts.append("- (nenhum detectado)")

    parts.extend([
        "",
        "## Próximas ações sugeridas",
        "- Rodar vault_cleanup se links quebrados acumularem",
        "- Atualizar cerebro/Preferencias com novos ensinos do Gustavo",
        "",
        "#jarvis #revisao-semanal [[00-INDEX]]",
    ])

    body = "\n".join(parts)
    title = f"Revisão semanal vault {now:%Y-%m-%d}"
    return _write_note(APRENDIZADOS, title, body, "weekly_review", ["revisao-semanal", "segundo-cerebro"])


def vault_cleanup_scan() -> str:
    """Faxina do vault: links quebrados e notas vazias (só relatório, sem apagar)."""
    if not vault_available():
        return f"Vault Obsidian não encontrado em {VAULT}."

    all_md: dict[str, str] = {}
    for path in _iter_note_files(include_reviews=True):
        rel = os.path.relpath(path, VAULT).replace("\\", "/")
        try:
            all_md[rel] = open(path, encoding="utf-8", errors="replace").read()
        except Exception:
            continue

    stems = {Path(r).stem.lower() for r in all_md}
    empty: List[str] = []
    broken: List[str] = []

    for rel, text in all_md.items():
        body = _strip_frontmatter(text)
        if len(body.strip()) < 40:
            empty.append(rel)
        for m in re.finditer(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]", text):
            target = m.group(1).strip()
            if not target:
                continue
            target_path = target.replace("\\", "/")
            if not target_path.endswith(".md"):
                target_path += ".md"
            candidates = [
                target_path,
                f"JARVIS/{target_path}",
                target.replace(" ", "-") + ".md",
            ]
            found = any(
                (Path(VAULT) / c.replace("/", os.sep)).is_file()
                or any(c.lower() in s for s in stems)
                for c in candidates
            )
            if not found and target not in ("00-INDEX", "LIVE_CHANGES", "SHARED_CONTEXT"):
                broken.append(f"{rel} → [[{target}]]")

    lines = [
        "=== Faxina vault Obsidian (scan) ===",
        f"Notas analisadas: {len(all_md)}",
        f"Notas vazias/curtas (<40 chars): {len(empty)}",
        f"Links [[wikilink]] possivelmente quebrados: {len(broken)}",
    ]
    if empty:
        lines.append("\nNotas vazias:")
        lines.extend(f"  • {e}" for e in empty[:10])
    if broken:
        lines.append("\nLinks quebrados (amostra):")
        lines.extend(f"  • {b}" for b in broken[:15])
    if not empty and not broken:
        lines.append("\n✓ Vault limpo — nenhum problema óbvio.")
    lines.append("\nUse teach_jarvis para corrigir notas que precisam de decisão humana.")
    return "\n".join(lines)


def weekly_vault_review(days_back: int = 7) -> str:
    """Revisão semanal do vault — workflow segundo cérebro (Felipe Tâmbara)."""
    if not vault_available():
        return f"Vault Obsidian não encontrado em {VAULT}."

    from datetime import timedelta

    now = datetime.now()
    conv_folder = os.path.join(VAULT, CONVERSAS_SUBDIR)
    learnings: List[str] = []
    decisions: List[str] = []
    open_loops: List[str] = []

    for d in range(days_back):
        day = now - timedelta(days=d)
        path = os.path.join(conv_folder, f"{day:%Y-%m-%d}.md")
        if not os.path.isfile(path):
            continue
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        for block in re.split(r"\n## \d{2}:\d{2}:\d{2}\n", text)[1:]:
            block_l = block.lower()
            if "jarvis:" in block:
                resp = block.split("**JARVIS:**", 1)[-1].split("\n", 1)[0][:200]
                learnings.append(resp.strip())
            if any(w in block_l for w in ("decidi", "vou ", "prefiro", "teach", "aprend")):
                decisions.append(" ".join(block.split())[:180])
            if any(w in block_l for w in ("depois", "amanhã", "pendente", "falta", "próximo")):
                open_loops.append(" ".join(block.split())[:160])

    recent_learn = _iter_note_files()[:8]
    learn_files = [
        os.path.relpath(p, VAULT).replace("\\", "/")
        for p in recent_learn
        if "Aprendizados" in p.replace("\\", "/")
    ]

    parts = [
        f"# Revisão semanal vault — {now:%Y-%m-%d}",
        "",
        "## O que avançou (conversas)",
    ]
    if learnings:
        parts.extend(f"- {x}" for x in learnings[-6:])
    else:
        parts.append("- (poucas conversas registradas nesta semana)")

    parts.extend(["", "## Aprendizados recentes no vault"])
    if learn_files:
        parts.extend(f"- [[{f}]]" for f in learn_files[:6])
    else:
        parts.append("- (nenhum)")

    parts.extend(["", "## Decisões / ensinos capturados"])
    if decisions:
        parts.extend(f"- {x}" for x in decisions[-5:])
    else:
        parts.append("- (nenhum explícito)")

    parts.extend(["", "## Loops abertos"])
    if open_loops:
        parts.extend(f"- {x}" for x in open_loops[-5:])
    else:
        parts.append("- (nenhum detectado)")

    parts.extend([
        "",
        "## Próximas ações sugeridas",
        "- Rodar vault_cleanup se links quebrados acumularem",
        "- Atualizar cerebro/Preferencias com novos ensinos do Gustavo",
        "",
        "#jarvis #revisao-semanal [[00-INDEX]]",
    ])

    body = "\n".join(parts)
    title = f"Revisão semanal vault {now:%Y-%m-%d}"
    return _write_note(APRENDIZADOS, title, body, "weekly_review", ["revisao-semanal", "segundo-cerebro"])


def vault_cleanup_scan() -> str:
    """Faxina do vault: links quebrados e notas vazias (só relatório, sem apagar)."""
    if not vault_available():
        return f"Vault Obsidian não encontrado em {VAULT}."

    all_md: dict[str, str] = {}
    for path in _iter_note_files(include_reviews=True):
        rel = os.path.relpath(path, VAULT).replace("\\", "/")
        try:
            all_md[rel] = open(path, encoding="utf-8", errors="replace").read()
        except Exception:
            continue

    stems = {Path(r).stem.lower() for r in all_md}
    empty: List[str] = []
    broken: List[str] = []

    for rel, text in all_md.items():
        body = _strip_frontmatter(text)
        if len(body.strip()) < 40:
            empty.append(rel)
        for m in re.finditer(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]", text):
            target = m.group(1).strip()
            if not target:
                continue
            target_path = target.replace("\\", "/")
            if not target_path.endswith(".md"):
                target_path += ".md"
            candidates = [
                target_path,
                f"JARVIS/{target_path}",
                target.replace(" ", "-") + ".md",
            ]
            found = any(
                (Path(VAULT) / c.replace("/", os.sep)).is_file()
                or any(c.lower() in s for s in stems)
                for c in candidates
            )
            if not found and target not in ("00-INDEX", "LIVE_CHANGES", "SHARED_CONTEXT"):
                broken.append(f"{rel} → [[{target}]]")

    lines = [
        "=== Faxina vault Obsidian (scan) ===",
        f"Notas analisadas: {len(all_md)}",
        f"Notas vazias/curtas (<40 chars): {len(empty)}",
        f"Links [[wikilink]] possivelmente quebrados: {len(broken)}",
    ]
    if empty:
        lines.append("\nNotas vazias:")
        lines.extend(f"  • {e}" for e in empty[:10])
    if broken:
        lines.append("\nLinks quebrados (amostra):")
        lines.extend(f"  • {b}" for b in broken[:15])
    if not empty and not broken:
        lines.append("\n✓ Vault limpo — nenhum problema óbvio.")
    lines.append("\nUse teach_jarvis para corrigir notas que precisam de decisão humana.")
    return "\n".join(lines)