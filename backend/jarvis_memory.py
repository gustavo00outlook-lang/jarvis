"""
Memória evolutiva do JARVIS — tom emocional + aprendizado no Obsidian.
"""
import asyncio
import re
from typing import Any, Dict, List, Optional, Tuple

import obsidian_notes
from conversation_state import get_user_prefs, update_user_pref

Tone = str  # humor | pegadinha | serio | emocional | neutro | urgente

_TEACH_MARKERS = (
    "lembre que",
    "lembre-se",
    "lembrar que",
    "guarde que",
    "salve que",
    "anote que",
    "meu nome é",
    "minha empresa",
    "eu prefiro",
    "eu gosto",
    "não gosto",
    "sempre use",
    "nunca ",
    "ensinando",
    "aprenda que",
)

_HUMOR_MARKERS = (
    "kkk", "kk", "haha", "rsrs", "brincando", "piada", "engraçado",
    "zoeira", "meme", "😂", "😄", "hehe", "huehue", "lol",
)

_PRANK_MARKERS = (
    "pegadinha", "pegadin", "troll", "te peguei", "caiu na", "aprontando",
    "zoando", "só brincando", "so brincando", "mentira", "falso alarme",
    "pegou?", "fui eu", "gotcha",
)

_DEBATE_MARKERS = (
    "acha que", "você acha", "voce acha", "melhor ou", "vale a pena",
    "discorda", "concorda", "argumenta", "defenda", "por que não",
    "porque não", "faz sentido", "não faz sentido", "nao faz sentido",
)

_EMOTION_MARKERS = (
    "frustrado", "triste", "ansioso", "preocupado", "cansado",
    "estressado", "chateado", "nervoso", "desanimado", "feliz",
    "empolgado", "grato", "obrigado demais",
)

_URGENT_MARKERS = (
    "urgente", "agora", "rápido", "rapido", "imediato", "já",
    "preciso agora", "corre",
)

_SERIOUS_MARKERS = (
    "importante", "sério", "serio", "produção", "producao",
    "deadline", "reunião", "reuniao", "cliente", "contrato",
)


def detect_tone(text: str) -> Tone:
    t = (text or "").lower().strip()
    if not t:
        return "neutro"
    if any(m in t for m in _URGENT_MARKERS):
        return "urgente"
    if any(m in t for m in _EMOTION_MARKERS):
        return "emocional"
    if any(m in t for m in _PRANK_MARKERS):
        return "pegadinha"
    if any(m in t for m in _HUMOR_MARKERS):
        return "humor"
    if any(m in t for m in _SERIOUS_MARKERS):
        return "serio"
    if "?" in t and len(t) < 80:
        return "neutro"
    return "neutro"


def wants_debate(text: str) -> bool:
    """True quando o Gustavo pede opinião, comparação ou argumentação."""
    t = (text or "").lower()
    return any(m in t for m in _DEBATE_MARKERS)


def build_tone_instruction(tone: Tone) -> str:
    instructions = {
        "humor": (
            "TOM ATUAL: humor Thomas — seco, inteligente, cinematográfico. "
            "Pode rir de leve (ha — bem observado, senhor), ironia suave, mesma vibe. "
            "NÃO pesquise no Google nem execute tools sem pedido explícito."
        ),
        "pegadinha": (
            "TOM ATUAL: pegadinha. Reaja com humor inteligente — ria, surpresa breve, devolva a zoeira com classe. "
            "NÃO leve a sério. NÃO pesquise nem execute tools salvo pedido explícito depois."
        ),
        "serio": (
            "TOM ATUAL: direto e profissional. Sem piadas. Preciso e confiante."
        ),
        "emocional": (
            "TOM ATUAL: empático. Reconheça o sentimento do Gustavo em uma frase antes de agir ou aconselhar."
        ),
        "urgente": (
            "TOM ATUAL: urgente. Frases curtíssimas. Priorize ação imediata."
        ),
        "neutro": (
            "TOM ATUAL: Thomas calmo do 0701 — deliberado, competente, cinematográfico ('Projeto fascinante, chefe'). "
            "Frases bem pontuadas, ritmo sem pressa. Decida: se for só conversa → fale; se precisar de fato do mundo → pesquise e opine; se for fazer → execute. "
            "Em conversa: ideia → porquê → fechamento. Em ação: execute e confirme em 1–2 frases. Sem empilhar perguntas."
        ),
    }
    return instructions.get(tone, instructions["neutro"])


def emotion_for_orb(tone: Tone) -> str:
    """Mood para paleta do orb (frontend)."""
    return {
        "humor": "happy",
        "pegadinha": "playful",
        "emocional": "warm",
        "urgente": "alert",
        "serio": "focused",
    }.get(tone, "calm")


def apply_emotion_to_speech(text: str, tone: Tone) -> str:
    """Injeta risada/tom na fala TTS quando o Gustavo está brincando."""
    t = (text or "").strip()
    if not t:
        return t
    low = t.lower()
    if tone in ("humor", "pegadinha"):
        if re.search(r"\b(?:ha[\s—-]|hã[\s—-]|rsrs|hehe|huehue|kk)\b", low):
            return t
        if tone == "pegadinha":
            return f"Ha — bem tentado, senhor. {t}"
        if tone == "humor":
            return f"Ha — {t}"
    if tone == "emocional" and not re.search(r"\b(?:entendo|compreendo|sinto)\b", low):
        return f"Entendo, senhor. {t}"
    return t


def _extract_teaching(user_text: str) -> Optional[Tuple[str, str, str]]:
    """Retorna (title, content, category) se houver ensino explícito."""
    raw = (user_text or "").strip()
    low = raw.lower()
    if not any(m in low for m in _TEACH_MARKERS):
        return None

    category = "preferencia"
    if "empresa" in low or "calango" in low or "projeto" in low:
        category = "projeto"
    elif "estilo" in low or "resposta" in low or "curto" in low or "detalhado" in low:
        category = "estilo"
    elif "nome" in low or "sou " in low:
        category = "fato"

    title = raw[:60].strip()
    if len(title) < 8:
        title = "Preferência do Gustavo"
    return title, raw, category


def _should_auto_save(user_text: str) -> bool:
    low = (user_text or "").lower()
    return any(m in low for m in _TEACH_MARKERS)


async def persist_conversation_turn(
    user_text: str,
    jarvis_response: str,
    tools_used: Optional[list] = None,
) -> None:
    """Salva toda conversa no Obsidian + ensino quando detectado."""
    import obsidian_notes

    await asyncio.to_thread(
        obsidian_notes.save_conversation_turn,
        user_text,
        jarvis_response,
        tools_used,
    )


async def learn_from_turn(user_text: str, jarvis_response: str, tone: Tone) -> Optional[str]:
    """Salva aprendizado em Ensinando-JARVIS quando detectado."""
    teaching = _extract_teaching(user_text)
    if not teaching:
        return None

    title, content, category = teaching
    note_body = (
        f"**Categoria:** {category}\n"
        f"**Tom da conversa:** {tone}\n\n"
        f"{content}\n\n"
        f"---\n*Resposta JARVIS:* {jarvis_response[:300]}"
    )
    return await asyncio.to_thread(
        obsidian_notes.save_teaching,
        title,
        note_body,
        category,
    )


_CORE_KNOWLEDGE = """=== CONHECIMENTO NÚCLEO (sempre ativo) ===
- Usuário: Gustavo | Papel: fundador Calango Studio | Local: Caçador/SC.
- Calango: agência de design/marca/web/tráfego/conteúdo; priorize soluções práticas de estúdio.
- JARVIS: assistente de voz + PC + web embutido; tom Thomas cinematográfico calmo; trate por senhor.
- Stack: Next.js :3000, FastAPI :8000, Ollama hermes3, voz XTTS local master.wav (thomas-0701).
- Vault canônico: C:\\Agencia calango\\calango.studio\\JARVIS\\cerebro (Aprendizados, Preferencias, Conversas).
- Xquads/AIOS: só quando a tarefa pedir agente. Conversa curta = sem orquestrador.
- Pesquisa: Gemini grounding OU DuckDuckGo+Wikipedia + painel Google — nunca diga que não pode pesquisar.
- Habilidades nível Grok: programar, depurar, orquestrar agentes, pesquisar web, relatórios Obsidian, ver tela, co-assistir YouTube, design critique, copy, tráfego, segurança, dados.
- Ao ensinar: teach_jarvis. Ao estudar: study_topic + web_search + resumo em voz + opinião.
- Decida: conversa/humor = falar; fato do mundo = pesquisar+opinar; ação = executar tools; marca/copy/ads/dev = persona de squad.
- Voz: nunca grite, nunca bullets falados; frases elegantes no ritmo do sample 0701."""


def get_memory_context() -> str:
    """Contexto de memória para injetar no system prompt."""
    parts: List[str] = [_CORE_KNOWLEDGE]
    try:
        import jarvis_design_memory
        design = jarvis_design_memory.load_design_context(700)
        if design:
            parts.append("Design Calango:\n" + design)
    except Exception:
        pass
    calango = obsidian_notes.load_calango_reference()
    if calango:
        parts.append("Calango Studio:\n" + calango[:900])
    teach = obsidian_notes.load_teaching_index(6)
    if teach:
        parts.append("Preferências do Gustavo:\n" + teach)
    conv = obsidian_notes.load_recent_conversation_log(days_back=2, max_entries=6, max_chars=1200)
    if conv:
        parts.append(conv)
    prefs = get_user_prefs()
    if prefs:
        safe_prefs = {
            k: v for k, v in prefs.items()
            if "senha" not in k.lower() and "password" not in k.lower()
        }
        if safe_prefs:
            parts.append(
                "Preferências em runtime: "
                + ", ".join(f"{k}={v}" for k, v in list(safe_prefs.items())[:8])
            )
    return "\n\n".join(parts)