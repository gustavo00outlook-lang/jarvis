"""
Visão local — OCR Windows + narração a partir de texto visível.

Quando a API multimodal xAI falha (403, créditos), o JARVIS ainda descreve
a tela usando OCR e o texto do DOM do painel Playwright.
"""

from __future__ import annotations

import asyncio
import base64
import io
import os
import re
import subprocess
import tempfile
from typing import List, Optional

from xai_client import get_client, get_fast_model


def _clean_visible(text: str, max_len: int = 900) -> str:
    t = " ".join((text or "").split())
    if len(t) > max_len:
        t = t[:max_len].rsplit(" ", 1)[0] + "…"
    return t


def _sanitize_ocr_text(raw: str, *, max_len: int = 900) -> str:
    """Remove lixo de OCR (URLs, métodos HTTP, terminal) — mantém texto legível."""
    if not raw:
        return ""
    t = " ".join((raw or "").split())
    for pat in (
        r"\b(?:GET|POST|PUT|DELETE|PATCH)\s*/\S*",
        r"https?://\S+",
        r"\b(?:localhost|127\.0\.0\.1):\d+\b",
        r"\bapi/[a-z_/]+\b",
        r"\b(?:uvicorn|Application startup|WatchFiles)\b",
        r"\d{3,5}as\b",
    ):
        t = re.sub(pat, " ", t, flags=re.I)
    words: List[str] = []
    skip = frozenset(
        {"get", "post", "http", "https", "localhost", "api", "jarvis", "health", "uvicorn"}
    )
    for w in t.split():
        if len(w) < 2 or w.lower() in skip:
            continue
        alnum = sum(1 for c in w if c.isalnum() or c in "áéíóúãõâêôàçÁÉÍÓÚÃÕÂÊÔÀÇ")
        if len(w) >= 4 and alnum / max(len(w), 1) < 0.45:
            continue
        words.append(w)
    out = " ".join(words)
    if len(out) < 12:
        return ""
    return out[:max_len]


def ocr_quality_ok(text: str) -> bool:
    """False quando OCR está ilegível — evita falar lixo na voz."""
    t = (text or "").strip()
    if len(t) < 12:
        return False
    letters = sum(1 for c in t if c.isalpha())
    if letters / max(len(t), 1) < 0.38:
        return False
    if "%" in t or re.search(r"\b[a-z]{1,2}ppit\b", t, re.I):
        return False
    low = t.lower()
    if any(tok in low for tok in ("import state", "https:", "localhost:", "webpack", "runtime typeerror")):
        return False
    return True


def is_google_chrome_text(text: str) -> bool:
    low = (text or "").lower()
    return any(
        tok in low
        for tok in (
            "ir para o conteúdo",
            "ir para o conteudo",
            "fazer login",
            "modo ia",
            "ajuda sobre acessibilidade",
        )
    )


def dedupe_spoken_lead(text: str) -> str:
    """Evita 'Sobre X, senhor: Sobre X, senhor: …' duplicado na voz."""
    t = (text or "").strip()
    if not t:
        return t
    m = re.match(r"^(Sobre .+?, senhor:\s*)(.+)$", t, re.I | re.S)
    if not m:
        return t
    lead, rest = m.group(1).strip(), m.group(2).strip()
    rest_low = rest.lower()
    lead_low = lead.lower()
    while rest_low.startswith(lead_low):
        rest = rest[len(lead) :].lstrip(" ,:;-")
        rest_low = rest.lower()
    return f"{lead} {rest}".strip() if rest else lead.rstrip()


def narrate_from_visible_text(user_text: str, visible: str, *, mode: str = "assist") -> str:
    """Narração JARVIS só com texto — funciona sem API."""
    vis = _clean_visible(visible, 720)
    if not vis or len(vis) < 12:
        if mode == "cowatch":
            return "Painel aberto, senhor. Ainda carregando — diga se quer que eu clique em algo."
        if mode == "whatsapp":
            return "WhatsApp em foco, senhor, mas não consegui ler o texto da conversa ainda."
        if mode == "design_review":
            return (
                "Estou olhando a tela, senhor, mas o conteúdo ainda não ficou legível o suficiente "
                "para uma crítica de design. Traga a janela para frente e peça de novo — aí eu opino e mostro como ficaria."
            )
        return "Estou olhando sua tela, senhor, mas o conteúdo ainda não ficou legível."

    if mode == "design_review":
        snippet = vis[:280]
        return (
            f"Senhor, na tela leio: {snippet}. "
            "Na minha avaliação, o que funciona precisa de hierarquia mais clara e respiro visual. "
            "Eu melhoraria contraste, espaçamento e o CTA principal para guiar o olhar. "
            "Como ficaria: um layout mais limpo, com título dominante, um bloco de prova social e um botão único óbvio — "
            "menos ruído, mais intenção. Posso detalhar ponto a ponto se quiser."
        )

    if mode == "cowatch":
        title = vis[:160]
        return (
            f"Estou vendo no painel: {title}. "
            "Acompanho com você, senhor — comento a cada cena; diga se quer relatório no fim."
        )
    if mode == "capcut":
        return (
            f"No CapCut vejo: {vis[:360]}. "
            "Posso orientar cortes, efeitos ou exportar — diga o que quer ajustar, senhor."
        )
    if mode == "whatsapp":
        return (
            f"Na tela do WhatsApp vejo: {vis[:320]}. "
            "Posso digitar uma resposta se você disser o que enviar, senhor."
        )
    if mode == "painel":
        return f"No painel: {vis[:380]}. Posso clicar, rolar ou pesquisar o próximo passo, senhor."
    if mode == "search":
        topic = (user_text or "o assunto").strip()[:80]
        if is_google_chrome_text(vis):
            return f"Abri a pesquisa sobre {topic} no Google, senhor. Veja os resultados no painel."
        snippet = vis[:320].strip()
        topic_low = topic.lower()
        for prefix in (
            "vejo na sua tela:",
            f"pesquisei sobre {topic_low}",
            f"sobre {topic_low}, senhor:",
            f"sobre {topic_low}",
            f"abri a pesquisa sobre {topic_low}",
            "abri a pesquisa sobre",
            "pesquisei sobre",
            "pesquisando agora",
            "vou pesquisar",
        ):
            if snippet.lower().startswith(prefix):
                snippet = snippet.split(":", 1)[-1].strip() if ":" in snippet[:40] else snippet[len(prefix):].strip(" ,.:;")
        if not snippet or len(snippet) < 8:
            return f"Pesquisei sobre {topic}, senhor. A busca está aberta no painel."
        low_snip = snippet.lower()
        if low_snip.startswith(("abri a pesquisa", "pesquisa sobre", "pesquisando ", "no google", "veja os resultados")):
            if "senhor" in low_snip[:100]:
                return dedupe_spoken_lead(snippet if snippet.endswith(".") else f"{snippet}.")
            return (
                f"Abri a pesquisa sobre {topic} no Google, senhor. "
                "Veja os resultados no painel."
            )
        return dedupe_spoken_lead(
            f"Sobre {topic}, senhor: {snippet}. Deixei a pesquisa aberta no painel."
        )
    return f"Vejo na sua tela: {vis[:400]}. Diga o que fazer em seguida, senhor."


def _ocr_windows_png(png_path: str) -> str:
    if os.name != "nt":
        return ""
    ps = rf"""
$path = '{png_path.replace("'", "''")}'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {{ $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' }})[0]
Function Await($WinRtTask, $ResultType) {{
  $asTask = $asTask.MakeGenericMethod($ResultType)
  return $asTask.Invoke($null, @($WinRtTask)).GetAwaiter().GetResult()
}}
[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine,Windows.Media.Ocr,ContentType=WindowsRuntime] | Out-Null
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) {{ exit 1 }}
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
($result.Lines | ForEach-Object {{ $_.Text }}) -join "`n"
"""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=25,
            encoding="utf-8",
            errors="replace",
        )
        text = (r.stdout or "").strip()
        if text and len(text) > 8:
            return text
    except Exception:
        pass
    return ""


def ocr_from_b64_jpeg(b64: str) -> str:
    """OCR de screenshot JPEG base64 — Windows.Media.Ocr."""
    if not b64:
        return ""
    try:
        from PIL import Image
    except ImportError:
        return ""
    try:
        raw = base64.b64decode(b64)
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            img.save(path, format="PNG")
            return _ocr_windows_png(path)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
    except Exception:
        return ""


async def _try_multimodal(
    user_text: str,
    images_b64: List[str],
    *,
    mode: str,
    context: str,
    tone: str = "neutro",
    debate: bool = False,
) -> str:
    if not images_b64:
        return ""
    client = get_client()
    sys = (
        "Você é J.A.R.V.I.S. assistindo AO VIVO com o Gustavo (pt-BR, tom Thomas). "
        "Comente o que vê de forma natural. Sem markdown, sem listas numeradas, sem emojis."
    )
    max_tok = 180
    if mode == "cowatch":
        max_tok = 200
        sys += (
            " Modo CO-ASSISTIR AO VIVO (YouTube/Instagram/Reels) com o Gustavo. "
            "Você assiste JUNTO e comenta AUTOMATICAMENTE o que está acontecendo agora. "
            "Regras: (1) diga o que entendeu da cena/legenda/título no frame, "
            "(2) argumente com opinião própria (concorda/discorda/ponto fraco/forte), "
            "(3) se for engraçado, RI com elegância Thomas ('Ha — …') sem virar palhaço, "
            "(4) 2-3 frases fluidas, sem markdown, sem listas. "
            "Nunca diga só 'vídeo tocando'. Mostre que entendeu o conteúdo."
        )
    if mode == "capcut":
        sys += (
            " Modo CapCut: descreva timeline, clipes, efeitos visíveis e sugira "
            "cortes, transições ou exportação — passo concreto."
        )
    if mode == "whatsapp":
        sys += " Leia conversas visíveis e diga quem mandou mensagem."
    if mode == "design_review":
        max_tok = 320
        sys += (
            " Modo CRÍTICA DE DESIGN / TELA (Calango Studio + JARVIS senior). "
            "Estrutura OBRIGATÓRIA em 5-7 frases orais contínuas: "
            "(1) o que está na tela agora (layout, hierarquia, cores, tipografia, CTA se houver), "
            "(2) SUA opinião honesta — o que funciona e o que trava, "
            "(3) 2 a 4 melhorias concretas e acionáveis (espaçamento, contraste, hierarquia, copy, CTA, grid), "
            "(4) pinte COMO FICARIA depois das mudanças — visualize o resultado final para o Gustavo. "
            "Fale como designer experiente, calmo e preciso. Nunca diga só 'está bom'. "
            "Se for site/landing/Figma/Canva/UI, use vocabulário de design; se for app genérico, adapte."
        )
    if mode == "assist":
        sys += (
            " Descreva a tela com clareza. Se o pedido pedir opinião, melhoria ou 'como ficaria', "
            "inclua análise + sugestões concretas + visão do resultado — 4-6 frases."
        )
        if re.search(
            r"\b(?:melhor|opini[aã]o|como\s+ficar|analis|design|layout|ideias?)\b",
            user_text or "",
            re.I,
        ):
            max_tok = 280
    if tone in ("humor", "pegadinha"):
        sys += " Tom leve: pode rir de leve ou ironia elegante se algo for engraçado."
    if debate:
        sys += (
            " O Gustavo quer DEBATE: dê opinião forte mas elegante, contra-argumente se discordar, "
            "cite o que viu no frame. Pergunte o que ele acha se fizer sentido. Sem prolixidade."
        )
    ctx = _clean_visible(context, 500)
    extra = f"\nContexto DOM/OCR: {ctx}" if ctx else ""
    user_ask = (
        "Analise a tela: o que vê, o que pensa, melhorias e como ficaria."
        if mode == "design_review"
        else "O que você vê?"
    )
    resp = await client.chat.completions.create(
        model=get_fast_model(),
        messages=[
            {"role": "system", "content": sys},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"Pedido: {user_text[:280]}{extra}\n{user_ask}",
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{images_b64[0]}",
                            "detail": "high",
                        },
                    },
                ],
            },
        ],
        max_tokens=max_tok,
        temperature=0.42 if mode == "design_review" else 0.4,
    )
    return (resp.choices[0].message.content or "").strip()


async def comment_live(
    user_text: str,
    images_b64: List[str],
    *,
    mode: str = "assist",
    context: str = "",
    tone: str = "neutro",
    debate: bool = False,
) -> str:
    """
    Comentário ao vivo: multimodal se possível; senão OCR + texto do painel.
    Nunca retorna mensagem de erro crua ao Gustavo.
    """
    ctx = (context or "").strip()
    if not ctx and images_b64:
        ocr = await asyncio.to_thread(ocr_from_b64_jpeg, images_b64[0])
        if ocr:
            ctx = ocr

    try:
        ans = await _try_multimodal(
            user_text, images_b64, mode=mode, context=ctx, tone=tone, debate=debate,
        )
        if ans and len(ans) > 15 and "403" not in ans and "Error code" not in ans:
            if tone == "pegadinha" and "ha" not in ans.lower()[:30]:
                return f"Ha — bem tentado, senhor. {ans}"
            return ans
    except Exception:
        pass

    if ctx:
        base = narrate_from_visible_text(user_text, ctx, mode=mode)
        if tone in ("humor", "pegadinha"):
            return f"Ha — {base}"
        return base

    if images_b64:
        return narrate_from_visible_text(
            user_text,
            "Captura recebida, mas o texto ainda não foi extraído.",
            mode=mode,
        )
    return narrate_from_visible_text(user_text, "", mode=mode)