"""
JARVIS ao vivo — co-assistir, ver painel em tempo real, ajudar na tela do desktop.

Painel browse (Google/IG/YT): preview contínuo + texto DOM/OCR (funciona mesmo sem API visão).
Desktop (WhatsApp/CapCut): look_at_screen/watch_screen + OCR + ação.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional, Awaitable

import desktop_control
import jarvis_memory
import local_vision
import obsidian_notes
import web_browser
from desktop_control import look_at_screen, watch_screen, type_text
from xai_client import fast_mode_enabled, get_client, get_fast_model

Broadcast = Callable[[Dict[str, Any]], Awaitable[None]]

_cowatch_active = False
_cowatch_bg_task: Optional[asyncio.Task] = None


def _cowatch_max_iter() -> int:
    """Duração do co-assistir em ciclos (~1.2s cada ≈ minutos de comentário)."""
    if fast_mode_enabled():
        return int(os.getenv("JARVIS_COWATCH_ITER", "20") or "20")
    # ~2–3 min de comentários automáticos (ajustável via env)
    return int(os.getenv("JARVIS_COWATCH_ITER", "48") or "48")


def is_cowatch_active() -> bool:
    return _cowatch_active


def set_cowatch_active(active: bool) -> None:
    global _cowatch_active
    _cowatch_active = bool(active)


def _cancel_cowatch_bg() -> None:
    global _cowatch_bg_task
    if _cowatch_bg_task and not _cowatch_bg_task.done():
        _cowatch_bg_task.cancel()
    _cowatch_bg_task = None


async def _vision_comment(
    user_text: str,
    images_b64: List[str],
    *,
    mode: str = "painel",
    context: str = "",
    tone: str = "neutro",
    debate: bool = False,
) -> str:
    return await local_vision.comment_live(
        user_text,
        images_b64,
        mode=mode,
        context=context,
        tone=tone,
        debate=debate,
    )


_WATCH_REPORT_RE = re.compile(
    r"\b(?:relat[oó]rio|resum[oa]|resuma|resume|analis[ae]|faz\s+(?:um\s+)?(?:relat|resum))",
    re.I,
)


def _wants_watch_report(text: str) -> bool:
    return bool(_WATCH_REPORT_RE.search(text or ""))


async def _build_watch_summary(
    user_text: str,
    narrations: List[str],
    *,
    source_url: str = "",
) -> str:
    """Síntese curta para relatório Obsidian."""
    if not narrations:
        return "Sessão aberta no painel; poucos comentários capturados."
    joined = "\n".join(f"- {n}" for n in narrations[-8:])
    try:
        client = get_client()
        resp = await client.chat.completions.create(
            model=get_fast_model(),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "JARVIS resume sessão de co-assistir vídeo em 4-6 frases pt-BR. "
                        "Inclua pontos fortes, críticas construtivas e conclusão. Sem markdown."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Pedido: {user_text[:200]}\nURL: {source_url}\nComentários:\n{joined}",
                },
            ],
            max_tokens=220,
            temperature=0.35,
        )
        ans = (resp.choices[0].message.content or "").strip()
        if ans and "403" not in ans and len(ans) > 30:
            return ans
    except Exception:
        pass
    return " ".join(narrations[-3:])[:500]


_MEMORY_RECALL_INTENT_RE = re.compile(
    r"\b(?:lembra|lembre|lembramos|falamos|conversamos|pesquisamos|disse|salvamos|"
    r"o\s+que\s+(?:pesquis|fal|convers|fiz|você\s+sabe|voce\s+sabe)|"
    r"ja\s+pesquis|já\s+pesquis|memória|memoria|no\s+obsidian|"
    r"o\s+que\s+(?:já|ja)\s+(?:falamos|conversamos|discutimos)|"
    r"me\s+conta\s+o\s+que)\b",
    re.I,
)


async def memory_first_answer(user_text: str) -> Optional[str]:
    """Responde da memória Obsidian SOMENTE quando o usuário pede recall explícito."""
    raw = (user_text or "").strip()
    if len(raw) < 12:
        return None
    if not _MEMORY_RECALL_INTENT_RE.search(raw):
        return None
    try:
        hits = await asyncio.to_thread(obsidian_notes.search_notes, raw[:160])
    except Exception:
        return None
    if not hits or len(str(hits)) < 80:
        return None
    snippet = str(hits)[:2400]
    try:
        client = get_client()
        resp = await client.chat.completions.create(
            model=get_fast_model(),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "JARVIS. Use SOMENTE a memória abaixo para responder. "
                        "Se não houver resposta suficiente, diga exatamente: SEM_MEMORIA. "
                        "Pt-BR, 2-5 frases naturais, sem markdown."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Pergunta: {raw}\n\nMemória Obsidian:\n{snippet}",
                },
            ],
            max_tokens=280,
            temperature=0.25,
        )
        ans = (resp.choices[0].message.content or "").strip()
        if not ans or "SEM_MEMORIA" in ans.upper() or len(ans) < 20:
            return None
        return ans
    except Exception:
        # Sem créditos xAI ou erro de API — não despejar memória crua; deixa o agente seguir.
        return None


def _extract_ig_url(text: str) -> Optional[str]:
    m = re.search(r"https?://(?:www\.)?instagram\.com/\S+", text, re.I)
    if m:
        return m.group(0).rstrip(").,")
    return None


def _extract_whatsapp_web_url(text: str) -> Optional[str]:
    m = re.search(r"https?://(?:www\.)?web\.whatsapp\.com/\S*", text, re.I)
    if m:
        return m.group(0).rstrip(").,")
    return None


def _cowatch_target_url(text: str) -> Optional[str]:
    ig = _extract_ig_url(text)
    if ig:
        return ig
    if re.search(r"\binstagram\b", text, re.I):
        reel = re.search(r"instagram\.com/(?:reel|p|tv)/[\w-]+", text, re.I)
        if reel:
            return reel.group(0).rstrip(").,")
        return "https://www.instagram.com/reels/"
    # WhatsApp Web support
    wa = _extract_whatsapp_web_url(text)
    if wa:
        return wa
    if re.search(r"\b(?:whatsapp\s+web|web\s+whatsapp|zap\s+web)\b", text, re.I):
        return "https://web.whatsapp.com"
    if re.search(r"\byoutube\b", text, re.I):
        q = re.search(
            r"(?:assista|veja|ver)\s+(?:o\s+)?(?:vídeo|video)?\s*(?:de|sobre)?\s*(.+)",
            text,
            re.I,
        )
        if q and len((q.group(1) or "").strip()) > 3:
            import urllib.parse
            from query_intelligence import normalize_search_query
            term = normalize_search_query(q.group(1), platform="youtube")[:80]
            return (
                "https://www.youtube.com/results?search_query="
                + urllib.parse.quote_plus(term)
            )
        return "https://www.youtube.com"
    return None


def _is_technical_screen_comment(text: str) -> bool:
    low = (text or "").lower()
    junk = (
        "screenshot capturado",
        "1920x1080",
        "1280x720",
        "quadros em sequência",
        "assisti a tela por",
        "multiplicando por 1.500",
    )
    return any(j in low for j in junk)


def _screen_ocr_context(images: List[str]) -> str:
    """OCR da captura — evita falar metadados técnicos de resolução."""
    if not images:
        return ""
    try:
        raw = local_vision.ocr_from_b64_jpeg(images[0])
        return local_vision._sanitize_ocr_text(raw or "", max_len=900)
    except Exception:
        return ""


def _ocr_looks_like_wrong_app(mode: str, ocr: str) -> bool:
    low = (ocr or "").lower()
    if mode != "capcut" or len(low) < 8:
        return False
    wrong = ("excel", "página inicial", "pagina inicial", "visual studio", "cursor")
    return any(w in low for w in wrong) and "capcut" not in low and "cap cut" not in low


def _spoken_screen_fallback(mode: str, ocr: str, user_text: str) -> str:
    vis = (ocr or "").strip()
    if _ocr_looks_like_wrong_app(mode, vis):
        return (
            "Abri o CapCut, senhor — a janela ainda não está em primeiro plano. "
            "Clique no CapCut e diga o corte ou exportação que quer."
        )
    if len(vis) < 12 or not local_vision.ocr_quality_ok(vis):
        if mode == "capcut":
            return "CapCut em foco, senhor — diga o corte, efeito ou exportação que quer."
        if mode == "whatsapp":
            return "WhatsApp aberto, senhor — diga para quem enviar ou o que precisa ver."
        if mode == "design_review":
            return (
                "Estou na tela, senhor, mas ainda sem leitura nítida o bastante para criticar o design. "
                "Deixe a janela em primeiro plano e peça de novo — aí eu opino e mostro como ficaria."
            )
        return "Estou vendo sua tela, senhor — diga o que fazer em seguida."
    if mode == "design_review":
        return local_vision.narrate_from_visible_text(user_text, vis, mode="design_review")
    if mode == "capcut":
        return f"No CapCut vejo: {vis[:320]}. Posso orientar cortes e exportação, senhor."
    if mode == "whatsapp":
        return f"No WhatsApp: {vis[:300]}. Diga se quer que eu digite uma resposta, senhor."
    return f"Vejo na tela: {vis[:360]}. O que executo agora, senhor?"


def _wants_realtime_screen(text: str) -> bool:
    return bool(
        re.search(
            r"\b(?:tempo\s+real|ao\s+vivo|em\s+tempo\s+real|agora\s+mesmo)\b"
            r"|\b(?:veja|olhe|olha)\s+(?:a\s+)?(?:minha\s+)?tela\s+(?:agora|ao\s+vivo)",
            text,
            re.I,
        )
    )


async def _cowatch_narration_loop(
    user_text: str,
    broadcast: Broadcast,
    *,
    tone: str,
    debate: bool,
    want_report: bool,
    source_url: str,
    feedback: str,
    humor: bool = True,
) -> None:
    """Loop em background: comenta, argumenta e reage (humor) ao vídeo ao vivo."""
    narrations: List[str] = []
    prev_text = ""
    prev_img_sig = ""
    last_spoke_at = 0.0
    last_comment = ""
    try:
        max_iter = _cowatch_max_iter()
        # Ciclo um pouco mais longo que o TTS para não atropelar a fala
        sleep_s = 1.0 if fast_mode_enabled() else 1.35
        # Intervalo entre falas: debate mais frequente
        min_gap = 3.2 if debate else 4.2
        for i in range(max_iter):
            await asyncio.sleep(sleep_s if i else 0.4)
            try:
                preview = await asyncio.wait_for(web_browser.get_preview(), timeout=10.0)
            except Exception:
                preview = {}
            if preview.get("image") or preview.get("url"):
                await broadcast({"type": "browser_preview", **preview})
            visible = (preview.get("text") or preview.get("title") or "").strip()
            img = preview.get("image") or ""
            if preview.get("url"):
                source_url = preview["url"]
            if not img and not visible:
                continue

            # Assinatura leve da imagem (muda com o frame do vídeo)
            img_sig = img[:96] if img else ""
            frame_changed = bool(img_sig and img_sig != prev_img_sig)
            text_changed = bool(visible and visible != prev_text)
            if visible:
                prev_text = visible
            if img_sig:
                prev_img_sig = img_sig

            now = time.monotonic()
            # Sempre comenta no 1º frame; depois a cada min_gap se algo mudou
            time_ok = (now - last_spoke_at) >= min_gap
            should_speak = (i == 0) or (
                time_ok and (frame_changed or text_changed or (i % 3 == 0))
            )
            if not should_speak:
                continue

            ctx_bits = [
                visible[:700] if visible else "",
                str(feedback)[:300] if feedback else "",
                f"frame={i + 1}/{max_iter}",
            ]
            context = " | ".join(b for b in ctx_bits if b)

            try:
                comment = await asyncio.wait_for(
                    _vision_comment(
                        user_text,
                        [img] if img else [],
                        mode="cowatch",
                        context=context,
                        tone="humor" if humor and tone not in ("serio", "urgente") else tone,
                        debate=True,  # co-assistir sempre argumenta
                    ),
                    timeout=14.0,
                )
            except Exception:
                continue

            if not comment or len(comment) < 12:
                continue
            if "análise falhou" in comment.lower() or "error code" in comment.lower():
                continue
            # Evita repetir a mesma frase
            if comment.strip()[:80].lower() == last_comment[:80].lower():
                continue

            last_comment = comment.strip()
            narrations.append(last_comment)
            last_spoke_at = now
            spoken = last_comment[:320]
            await broadcast({"type": "jarvis_narration", "text": spoken})
            # transcript → frontend fala com TTS (ws.ts)
            await broadcast({
                "type": "transcript",
                "role": "jarvis",
                "text": spoken,
                "tone": "humor" if humor else tone,
            })
            await broadcast({"type": "state", "state": "speaking", "text": spoken})
            # Humor no orb
            if humor and re.search(r"\b(?:ha|hã|kk|riso|engraçad|hilár)\b", spoken, re.I):
                await broadcast({
                    "type": "tone",
                    "tone": "humor",
                    "mood": jarvis_memory.emotion_for_orb("humor"),
                })
    except asyncio.CancelledError:
        pass
    finally:
        set_cowatch_active(False)
        await broadcast({"type": "cowatch_end"})
        if narrations and (want_report or len(narrations) >= 2):
            try:
                summary = await _build_watch_summary(user_text, narrations, source_url=source_url)
                title = f"Co-assistir {source_url.split('/')[-1][:40] or 'video'}"
                save_fb = await asyncio.to_thread(
                    obsidian_notes.save_watch_report,
                    title,
                    source_url=source_url,
                    user_request=user_text,
                    narrations=narrations,
                    summary=summary,
                )
                await broadcast({
                    "type": "tool_call",
                    "tool": "save_watch_report",
                    "status": "done",
                    "result": str(save_fb)[:200],
                })
                closing = (
                    f"{summary} Relatório salvo no Obsidian, senhor."
                    if want_report
                    else f"Fim do co-assistir, senhor. {summary[:220]}"
                )
                await broadcast({
                    "type": "transcript",
                    "role": "jarvis",
                    "text": closing[:400],
                })
            except Exception:
                pass


async def cowatch_with_user(
    user_text: str,
    broadcast: Broadcast,
    *,
    open_url_fn,
    broadcast_preview_fn,
) -> Dict[str, Any]:
    """Abre YouTube/painel e devolve rápido; narração contínua roda em background."""
    try:
        return await _cowatch_with_user_impl(
            user_text,
            broadcast,
            open_url_fn=open_url_fn,
            broadcast_preview_fn=broadcast_preview_fn,
        )
    except Exception as e:
        print(f"[cowatch] falha suave: {e}")
        try:
            set_cowatch_active(False)
            await broadcast({"type": "cowatch_end"})
        except Exception:
            pass
        return {
            "response": (
                "Senhor, não consegui iniciar o co-assistir agora, mas sigo online. "
                "Pode repetir com o link ou o tema do vídeo?"
            ),
            "tools_used": [],
            "cowatch_active": False,
        }


async def _cowatch_with_user_impl(
    user_text: str,
    broadcast: Broadcast,
    *,
    open_url_fn,
    broadcast_preview_fn,
) -> Dict[str, Any]:
    global _cowatch_bg_task
    _cancel_cowatch_bg()

    url = _cowatch_target_url(user_text)
    yt_play = None
    is_whatsapp_web = False
    if not url:
        m_yt = re.search(
            r"\b(?:assista|veja|ver|abre)\s+(?:comigo\s+)?(?:um\s+)?(?:vídeo|video)\s+(?:sobre|de|no)\s+(.+)",
            user_text,
            re.I,
        )
        if m_yt:
            from query_intelligence import resolve_search_query
            yt_play = (await resolve_search_query(m_yt.group(1), platform="youtube"))[:100]
            url = None
        else:
            url = web_browser.build_nav_url(
                re.sub(r"\b(?:assista|veja|ver|abre)\s+comigo\s*", "", user_text, flags=re.I).strip()
            )
    else:
        # Check if it's WhatsApp Web
        if url and "web.whatsapp.com" in url.lower():
            is_whatsapp_web = True

    set_cowatch_active(True)
    await broadcast({"type": "cowatch_start", "url": url or "youtube"})

    tool = "browse_open"
    tools_row: List[Dict[str, str]] = []
    feedback = ""

    if yt_play:
        await broadcast({
            "type": "tool_call",
            "tool": tool,
            "status": "running",
            "desc": f"YouTube: {yt_play}",
        })
        try:
            feedback = await asyncio.wait_for(
                web_browser.youtube_search_and_play(yt_play),
                timeout=35.0,
            )
        except Exception as e:
            feedback = str(e)
        await broadcast({
            "type": "tool_call",
            "tool": tool,
            "status": "done",
            "result": str(feedback)[:200],
        })
        tools_row.append({"tool": tool, "result": str(feedback)[:200]})
        await broadcast_preview_fn(broadcast, tool, {"url": "youtube"}, str(feedback))
    else:
        args = {"url": url}
        await broadcast({"type": "tool_call", "tool": tool, "status": "running", "desc": f"Abrindo {url}"})
        await broadcast({"type": "browser_preview", **web_browser.preview_from_url(url or "", "", "")})
        try:
            feedback = await asyncio.wait_for(
                web_browser.open_url(url or "https://www.youtube.com"),
                timeout=35.0,
            )
        except Exception as e:
            feedback = str(e)
        await broadcast({"type": "tool_call", "tool": tool, "status": "done", "result": str(feedback)[:200]})
        await broadcast_preview_fn(broadcast, tool, args, str(feedback))
        tools_row.append({"tool": tool, "result": str(feedback)[:200]})

    tone = jarvis_memory.detect_tone(user_text)
    
    if is_whatsapp_web:
        # WhatsApp Web: não é vídeo, não precisa do loop de narração contínua
        # Apenas abre e fica disponível para ajudar via painel
        opening = (
            "WhatsApp Web aberto no painel, senhor. "
            "Estou vendo suas conversas — pode pedir para ler mensagens, responder, "
            "buscar contatos ou o que precisar."
        )
        if want_report:
            opening += " No final deixo um relatório no Obsidian."
        
        return {
            "response": opening[:480],
            "tools_used": tools_row,
            "cowatch_active": True,
            "tone": tone,
            "mood": jarvis_memory.emotion_for_orb(tone),
            "whatsapp_web": True,
        }

    # Co-assistir = SEMPRE argumenta e reage; humor on a menos que peça sério
    debate = True
    humor = not bool(re.search(r"\b(?:s[eé]rio|sem\s+piada|profissional|formal)\b", user_text, re.I))
    if humor or re.search(r"\b(?:ri|risada|humor|zoeira|engraçad)\b", user_text, re.I):
        tone = "humor" if tone not in ("urgente", "emocional") else tone
    want_report = _wants_watch_report(user_text) or bool(
        re.search(r"\b(?:relat[oó]rio|resumo\s+final|salva)\b", user_text, re.I)
    )
    source_url = url or (yt_play and f"youtube:{yt_play}") or "painel"

    await broadcast({
        "type": "tone",
        "tone": tone,
        "mood": jarvis_memory.emotion_for_orb(tone if tone != "humor" else "humor"),
    })

    _cowatch_bg_task = asyncio.create_task(
        _cowatch_narration_loop(
            user_text,
            broadcast,
            tone=tone,
            debate=debate,
            want_report=want_report,
            source_url=source_url,
            feedback=str(feedback),
            humor=humor,
        )
    )

    opening = (
        "YouTube aberto, senhor. Vou assistir com você ao vivo: comento o que acontece, "
        "argumento sozinho e rio se for engraçado."
        if yt_play or "youtube" in (url or "").lower()
        else "Painel aberto, senhor. Estou vendo junto — comento e argumento ao vivo."
    )
    if want_report:
        opening += " No final deixo um relatório no Obsidian."

    return {
        "response": opening[:480],
        "tools_used": tools_row,
        "cowatch_active": True,
        "tone": tone,
        "mood": jarvis_memory.emotion_for_orb(tone if tone != "humor" else "humor"),
    }


def _wants_design_review(text: str) -> bool:
    """Opinião/melhorias sobre a TELA visível — não opinião genérica de tema (ex.: 'IA no design')."""
    raw = text or ""
    # Âncora visual obrigatória
    has_screen = bool(
        re.search(
            r"\b(?:"
            r"tela|nesta\s+tela|na\s+tela|minha\s+tela|"
            r"layout\s+da\s+tela|interface\s+na\s+tela|"
            r"disso\s+aqui|isso\s+aqui|figma|canva|"
            r"landing\s+page\s+na\s+tela|site\s+aberto"
            r")\b",
            raw,
            re.I,
        )
    )
    if not has_screen:
        return False
    return bool(
        re.search(
            r"\b(?:"
            r"analis[ae]|avalia|avalie|critique|critica|"
            r"opini[aã]o|o\s+que\s+(?:você|voce|vc)\s+(?:acha|pensa)|"
            r"melhorias?|ideias?\s+de\s+melhoria|como\s+melhorar|"
            r"como\s+ficar(?:ia)?|sugest(?:[aã]o|ões|oes)|"
            r"feedback|parecer|refin[ae]|otimiz[ae]|"
            r"melhor[ae]\s+(?:o\s+)?(?:design|layout|visual|tela|interface)"
            r")\b",
            raw,
            re.I,
        )
    )


async def screen_assist(
    user_text: str,
    broadcast: Broadcast,
    *,
    open_app_fn=None,
) -> Dict[str, Any]:
    """Ajuda vendo a tela real (WhatsApp, CapCut, design review, qualquer app)."""
    try:
        return await _screen_assist_impl(
            user_text, broadcast, open_app_fn=open_app_fn
        )
    except Exception as e:
        print(f"[screen] falha suave: {e}")
        return {
            "response": (
                "Senhor, não consegui analisar a tela agora, mas sigo online. "
                "Deixe a janela em primeiro plano e peça de novo."
            ),
            "tools_used": [],
        }


async def _screen_assist_impl(
    user_text: str,
    broadcast: Broadcast,
    *,
    open_app_fn=None,
) -> Dict[str, Any]:
    tools_row: List[Dict[str, str]] = []
    low = user_text.lower()
    realtime = _wants_realtime_screen(user_text)
    design_review = _wants_design_review(user_text)

    capcut_edit = bool(
        re.search(r"\bcap\s*cut\b", low)
        and re.search(
            r"\b(?:edit[ae]|cort[ae]|mont[ae]|export[ae]|ajud[ae]|faz|fazer|arrum[ae])\b",
            low,
        )
    ) or bool(
        re.search(r"\b(?:edit[ae]|cort[ae]|mont[ae])\b", low)
        and re.search(r"\b(?:vídeo|video)\b", low)
    )

    app_to_open = None
    for key in ("whatsapp", "capcut", "cap cut", "chrome", "obsidian", "notion"):
        if key in low and re.search(
            r"\b(?:abre|abra|abrir|veja|ver|edit[ae]|ajud[ae]|mex[ae])\b", low
        ):
            app_to_open = "capcut" if "cap" in key else key.replace(" ", "")
            break

    if app_to_open and open_app_fn:
        await broadcast({
            "type": "tool_call",
            "tool": "open_app",
            "status": "running",
            "desc": f"Abrindo {app_to_open}",
        })
        fb = await open_app_fn({"app_name": app_to_open})
        await broadcast({
            "type": "tool_call",
            "tool": "open_app",
            "status": "done",
            "result": str(fb)[:200],
        })
        tools_row.append({"tool": "open_app", "result": str(fb)[:200]})
        await asyncio.sleep(3.0 if app_to_open == "capcut" else 2.0)
        focus_fb = await asyncio.to_thread(
            desktop_control.focus_app_window, app_to_open, retries=4 if app_to_open == "capcut" else 2
        )
        tools_row.append({"tool": "focus_app", "result": focus_fb[:120]})
        await asyncio.sleep(0.8 if app_to_open == "capcut" else 0.5)
    elif app_to_open:
        focus_fb = await asyncio.to_thread(desktop_control.focus_app_window, app_to_open)
        tools_row.append({"tool": "focus_app", "result": focus_fb[:120]})
        await asyncio.sleep(0.4)

    tone = jarvis_memory.detect_tone(user_text)
    debate = jarvis_memory.wants_debate(user_text) or design_review
    if design_review:
        mode = "design_review"
    elif capcut_edit or "capcut" in low or "cap cut" in low:
        mode = "capcut"
    elif "whatsapp" in low:
        mode = "whatsapp"
    else:
        mode = "assist"
    narrations: List[str] = []
    all_images: List[str] = []

    # Design review: 1 screenshot nítido basta; realtime/capcut: vários frames
    if (realtime or capcut_edit) and not design_review:
        tool = "watch_screen"
        await broadcast({
            "type": "tool_call",
            "tool": tool,
            "status": "running",
            "desc": "Assistindo tela ao vivo",
        })
        secs = 10.0 if capcut_edit else 6.0
        frames = 5 if capcut_edit else 4
        look_fb, all_images = await watch_screen(secs, frames)
        await broadcast({
            "type": "tool_call",
            "tool": tool,
            "status": "done",
            "result": str(look_fb)[:200],
        })
        tools_row.append({"tool": tool, "result": str(look_fb)[:200]})
        ocr_ctx = _screen_ocr_context(all_images)
        for img in all_images[:4]:
            c = await _vision_comment(
                user_text, [img], mode=mode, context=ocr_ctx or str(look_fb), tone=tone, debate=debate,
            )
            if c and len(c) > 15:
                narrations.append(c)
                await broadcast({"type": "jarvis_narration", "text": c[:260]})
    else:
        await broadcast({
            "type": "tool_call",
            "tool": "look_at_screen",
            "status": "running",
            "desc": "Analisando design da tela" if design_review else "Olhando sua tela",
        })
        look_fb, all_images = await look_at_screen()
        await broadcast({
            "type": "tool_call",
            "tool": "look_at_screen",
            "status": "done",
            "result": str(look_fb)[:200],
        })
        tools_row.append({"tool": "look_at_screen", "result": str(look_fb)[:200]})
        ocr_ctx = _screen_ocr_context(all_images)
        c = await _vision_comment(
            user_text, all_images, mode=mode, context=ocr_ctx or str(look_fb), tone=tone, debate=debate,
        )
        if c and not _is_technical_screen_comment(c):
            narrations.append(c)
            await broadcast({"type": "jarvis_narration", "text": c[:420 if design_review else 240]})

    ocr_final = _screen_ocr_context(all_images)
    clean_narr = [n for n in narrations if not _is_technical_screen_comment(n)]
    if design_review and clean_narr:
        # Preferir a análise mais rica (maior) quando for crítica de design
        comment = max(clean_narr, key=len)
    elif _ocr_looks_like_wrong_app(mode, ocr_final) or (
        not design_review and not local_vision.ocr_quality_ok(ocr_final) and not clean_narr
    ):
        comment = _spoken_screen_fallback(mode, ocr_final, user_text)
    elif clean_narr and not _ocr_looks_like_wrong_app(mode, clean_narr[-1]):
        comment = clean_narr[-1]
    else:
        if design_review:
            comment = local_vision.narrate_from_visible_text(
                user_text, ocr_final, mode="design_review"
            )
        else:
            comment = _spoken_screen_fallback(mode, ocr_final, user_text)

    send_m = re.search(
        r"(?:mand[ae]|envi[ae])\s+(?:mensagem\s+)?(?:para|pro|pra)\s+(\w+)(?:\s+(.+))?",
        user_text,
        re.I,
    )
    if send_m and send_m.group(2):
        msg = send_m.group(2).strip().rstrip(".,!?")
        if len(msg) > 2:
            await broadcast({
                "type": "tool_call",
                "tool": "desktop_type",
                "status": "running",
                "desc": "Digitando mensagem",
            })
            type_fb = await type_text(msg, press_enter=False)
            await broadcast({
                "type": "tool_call",
                "tool": "desktop_type",
                "status": "done",
                "result": str(type_fb)[:200],
            })
            tools_row.append({"tool": "desktop_type", "result": str(type_fb)[:200]})
            comment += f" Digitei a mensagem para {send_m.group(1)}, senhor — confirme antes de enviar."

    if capcut_edit and narrations:
        comment += (
            " No CapCut posso orientar cortes, transições e exportação — "
            "diga o efeito ou trecho que quer ajustar, senhor."
        )

    # Crítica de design pode ser mais longa (opinião + melhorias + como ficaria)
    limit = 1100 if design_review else 780
    return {"response": comment[:limit], "tools_used": tools_row}


async def calango_studio_session(
    user_text: str,
    broadcast: Broadcast,
    *,
    broadcast_preview_fn,
) -> Dict[str, Any]:
    """Login Calango + Studio; opcionalmente gera imagem pelo prompt no pedido."""
    prompt = ""
    m = re.search(
        r"(?:ger[ae]|cri[ae]|faz|monta)\s+(?:uma\s+)?(?:imagem|arte|post|banner|visual)\s+"
        r"(?:de|com|sobre)?\s*(.+)",
        user_text,
        re.I,
    )
    if m:
        prompt = (m.group(1) or "").strip().rstrip(".,!?")[:220]

    tool = "calango_studio_login"
    await broadcast({
        "type": "tool_call",
        "tool": tool,
        "status": "running",
        "desc": "Calango Studio — login e ferramentas",
    })
    try:
        feedback = await web_browser.calango_login_and_studio(prompt)
    except Exception as e:
        feedback = str(e)
    await broadcast({
        "type": "tool_call",
        "tool": tool,
        "status": "done",
        "result": str(feedback)[:200],
    })
    await broadcast_preview_fn(
        broadcast, "browse_open", {"url": "calango.studio/#/studio"}, str(feedback),
    )
    spoken = (
        f"Calango Studio aberto, senhor. {prompt and 'Enviei o prompt para gerar a imagem. ' or ''}"
        "Diga o formato ou ajuste que quer nas ferramentas de IA."
    )
    if "logado" in str(feedback).lower():
        spoken = (
            "Logado na Calango, senhor. Vejo o modo Studio — "
            + (f"prompt '{prompt[:50]}' aplicado. " if prompt else "")
            + "Posso clicar em Carrossel, Feed, Story ou gerar outra arte."
        )
    return {
        "response": spoken[:680],
        "tools_used": [{"tool": tool, "result": str(feedback)[:200]}],
    }


async def study_and_remember(topic: str, broadcast: Broadcast, study_fn) -> Dict[str, Any]:
    """Estudo profundo + gravação Obsidian."""
    await broadcast({
        "type": "tool_call",
        "tool": "study_topic",
        "status": "running",
        "desc": f"Estudando {topic}",
    })
    try:
        fb = await study_fn({"topic": topic, "focus": "visão geral"})
    except Exception as e:
        fb = f"Estudo parcial salvo com erros de API: {e}"
    await broadcast({
        "type": "tool_call",
        "tool": "study_topic",
        "status": "done",
        "result": str(fb)[:200],
    })
    spoken = f"Estudei {topic} e salvei no Obsidian, senhor."
    try:
        client = get_client()
        resp = await client.chat.completions.create(
            model=get_fast_model(),
            messages=[
                {"role": "system", "content": "JARVIS resume estudo em 3-4 frases pt-BR para voz."},
                {"role": "user", "content": f"Tópico: {topic}\n\n{str(fb)[:3000]}"},
            ],
            max_tokens=200,
            temperature=0.3,
        )
        ans = (resp.choices[0].message.content or "").strip()
        if ans and "403" not in ans:
            spoken = ans
    except Exception:
        pass
    return {
        "response": spoken,
        "tools_used": [{"tool": "study_topic", "result": str(fb)[:200]}],
    }