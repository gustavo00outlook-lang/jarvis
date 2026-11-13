"""
Navegação web real do JARVIS — Playwright headful.

Abre uma janela de Chrome visível e controla de verdade: clica, digita, rola.
O agente enxerga a página via snapshot textual com elementos numerados e
age pelos números. Playwright sync roda em UMA thread dedicada (obrigatório).

Auto-cura: se o pacote playwright não estiver no MESMO Python do backend
(sys.executable), instala sozinho; se faltar navegador, baixa o Chromium.
"""

import asyncio
import base64
import re
import subprocess
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="jarvis-browser")

_pw = None
_browser = None
_page = None
_elements: List = []
_install_tried = False
_panel_active = False

_INTERACTIVE = "a, button, input, textarea, select, [role='button'], [role='link'], [role='tab'], [role='menuitem']"
_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
    "--no-first-run",
    "--no-default-browser-check",
    "--window-size=1366,854",
    "--lang=pt-BR",
]


def _import_sync_playwright():
    from playwright.sync_api import sync_playwright
    return sync_playwright


def _autoinstall_package() -> str:
    """Instala o pacote playwright no MESMO interpretador do backend."""
    global _install_tried
    if _install_tried:
        return "instalação já tentada nesta sessão"
    _install_tried = True
    r = subprocess.run(
        [sys.executable, "-m", "pip", "install", "playwright"],
        capture_output=True, text=True, timeout=300,
    )
    tail = ((r.stdout or "") + (r.stderr or ""))[-300:]
    return f"pip returncode {r.returncode}: {tail}"


def _launch_browser(pw):
    """Chrome do sistema; senão Chromium (baixando-o na primeira vez se preciso)."""
    try:
        return pw.chromium.launch(channel="chrome", headless=True, args=_LAUNCH_ARGS)
    except Exception:
        pass
    try:
        return pw.chromium.launch(headless=True, args=_LAUNCH_ARGS)
    except Exception as e:
        if "executable" not in str(e).lower():
            raise
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True, text=True, timeout=900,
        )
        return pw.chromium.launch(headless=True, args=_LAUNCH_ARGS)


def _ensure_page():
    global _pw, _browser, _page
    if _page is not None:
        try:
            _ = _page.url
            return _page
        except Exception:
            _cleanup()

    try:
        sync_playwright = _import_sync_playwright()
    except ImportError:
        log = _autoinstall_package()
        try:
            sync_playwright = _import_sync_playwright()
        except ImportError:
            raise RuntimeError(
                "Playwright não disponível mesmo após auto-instalação "
                f"({log}). Rode no terminal: {sys.executable} -m pip install playwright"
            )

    _pw = sync_playwright().start()
    _browser = _launch_browser(_pw)
    ctx = _browser.new_context(
        viewport={"width": 1366, "height": 854},
        locale="pt-BR",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
    )
    _page = ctx.new_page()
    return _page


def _cleanup():
    global _pw, _browser, _page, _elements, _panel_active
    for closer in (lambda: _browser.close(), lambda: _pw.stop()):
        try:
            closer()
        except Exception:
            pass
    _pw = _browser = _page = None
    _elements = []
    _panel_active = False


def _snapshot(max_elems: int = 25, max_text: int = 1100) -> str:
    """Título + URL + texto visível + elementos interativos numerados."""
    global _elements
    p = _ensure_page()
    try:
        p.wait_for_load_state("domcontentloaded", timeout=8000)
    except Exception:
        pass

    try:
        title = p.title()
    except Exception:
        title = "?"
    url = p.url

    try:
        body_text = p.evaluate("() => document.body.innerText") or ""
    except Exception:
        body_text = ""
    body_text = " ".join(body_text.split())
    if len(body_text) > max_text:
        body_text = body_text[:max_text] + " [...]"

    _elements = []
    lines = []
    try:
        locs = p.locator(_INTERACTIVE)
        total = min(locs.count(), 90)
        for i in range(total):
            el = locs.nth(i)
            try:
                if not el.is_visible():
                    continue
                tag = el.evaluate("e => e.tagName.toLowerCase()")
                if tag in ("input", "textarea", "select"):
                    hint = (
                        el.get_attribute("placeholder")
                        or el.get_attribute("aria-label")
                        or el.get_attribute("name")
                        or el.get_attribute("type")
                        or ""
                    )
                    label = f"[campo: {hint[:50]}]"
                else:
                    label = (el.inner_text(timeout=400) or "").strip()
                    if not label:
                        label = (el.get_attribute("aria-label") or el.get_attribute("title") or "").strip()
                    label = " ".join(label.split())[:60]
                if not label:
                    continue
                _elements.append(el)
                lines.append(f"  {len(_elements)}. <{tag}> {label}")
                if len(_elements) >= max_elems:
                    break
            except Exception:
                continue
    except Exception as e:
        lines.append(f"  (erro listando elementos: {e})")

    elems = "\n".join(lines) if lines else "  (nenhum elemento visível)"
    return f"Página: {title} — {url}\nTexto visível: {body_text}\nElementos (aja pelo número):\n{elems}"


def _do_open(url: str) -> str:
    global _panel_active
    p = _ensure_page()
    url = url.strip()
    if "://" not in url:
        url = "https://" + url
    p.goto(url, wait_until="domcontentloaded", timeout=30000)
    p.wait_for_timeout(1500)
    _panel_active = True
    try:
        p.bring_to_front()
    except Exception:
        pass
    return _snapshot()


def _do_read() -> str:
    return _snapshot()


def _do_click(number: int) -> str:
    if not _elements or not (1 <= number <= len(_elements)):
        return f"Elemento {number} não existe no último snapshot ({len(_elements)} disponíveis). Use browse_read primeiro."
    el = _elements[number - 1]
    try:
        el.scroll_into_view_if_needed(timeout=3000)
    except Exception:
        pass
    el.click(timeout=6000)
    _page.wait_for_timeout(1800)
    return f"Cliquei no elemento {number}.\n" + _snapshot()


def _do_type(number: int, text: str, press_enter: bool) -> str:
    if not _elements or not (1 <= number <= len(_elements)):
        return f"Elemento {number} não existe no último snapshot. Use browse_read primeiro."
    el = _elements[number - 1]
    el.fill(text, timeout=6000)
    if press_enter:
        el.press("Enter")
        _page.wait_for_timeout(2200)
        return f"Digitei '{text}' e apertei Enter.\n" + _snapshot()
    return f"Digitei '{text}' no elemento {number}. Campo preenchido."


def _do_scroll(direction: str) -> str:
    p = _ensure_page()
    direction = (direction or "down").lower()
    if direction == "top":
        p.evaluate("window.scrollTo(0, 0)")
    elif direction == "bottom":
        p.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    else:
        delta = -700 if direction == "up" else 700
        p.evaluate(f"window.scrollBy(0, {delta})")
    p.wait_for_timeout(700)
    return f"Rolei para {direction}.\n" + _snapshot()


def _do_click_at(xf: float, yf: float) -> str:
    """Clique direto por fracao do viewport (0..1) — painel interativo."""
    p = _ensure_page()
    try:
        vp = p.viewport_size or {"width": 1366, "height": 854}
        x = max(0.0, min(1.0, float(xf))) * vp["width"]
        y = max(0.0, min(1.0, float(yf))) * vp["height"]
        p.mouse.click(x, y)
        p.wait_for_timeout(1600)
    except Exception as e:
        return f"erro clique: {e}\n" + _snapshot()
    return f"clique ({xf:.2f},{yf:.2f}).\n" + _snapshot()


def _do_scroll_by(dy: int) -> str:
    """Rolagem livre por pixels — roda do mouse no painel."""
    p = _ensure_page()
    try:
        p.evaluate(f"window.scrollBy(0, {int(dy)})")
        p.wait_for_timeout(450)
    except Exception:
        pass
    return _snapshot()


def _do_press_key(keys: str) -> str:
    p = _ensure_page()
    key = (keys or "ArrowRight").strip()
    p.keyboard.press(key)
    p.wait_for_timeout(1200)
    return f"Tecla '{key}' pressionada.\n" + _snapshot()


def _do_carousel_slide(post_url: str, slide: int) -> str:
    """Navega slide de carrossel IG via ?img_index=N ou seta direita."""
    p = _ensure_page()
    url = (post_url or p.url or "").strip()
    slide = max(1, int(slide or 1))
    if "instagram.com" in url and "/p/" in url:
        base = url.split("?")[0].rstrip("/")
        url = f"{base}/?img_index={slide}"
        p.goto(url, wait_until="domcontentloaded", timeout=25000)
    else:
        for _ in range(slide - 1):
            p.keyboard.press("ArrowRight")
            p.wait_for_timeout(900)
    p.wait_for_timeout(1500)
    return f"Carrossel slide {slide}.\n" + _snapshot()


def _do_back() -> str:
    p = _ensure_page()
    p.go_back(wait_until="domcontentloaded", timeout=15000)
    p.wait_for_timeout(1000)
    return "Voltei.\n" + _snapshot()


def _do_close() -> str:
    _cleanup()
    return "Navegador do JARVIS fechado."


_SKIP_RESULT = frozenset({
    "patrocinado", "anúncio", "anuncio", "imagens", "vídeos", "videos", "maps",
    "modo ai", "ferramentas", "notícias", "noticias", "shopping", "livros",
    "mais", "google", "pesquisa", "search", "acessibilidade", "filtros",
})


def _element_label(el) -> str:
    try:
        label = (el.inner_text(timeout=500) or "").strip()
        if not label:
            label = (el.get_attribute("aria-label") or el.get_attribute("title") or "").strip()
        return " ".join(label.split())
    except Exception:
        return ""


def _find_clickable_index(kind: str = "google") -> Optional[int]:
    """Índice 1-based do primeiro resultado orgânico (Google ou YouTube)."""
    global _elements
    if not _elements:
        _snapshot()
    p = _ensure_page()
    url = (p.url or "").lower()
    is_yt = "youtube.com" in url or kind == "youtube"

    for i, el in enumerate(_elements):
        try:
            tag = el.evaluate("e => e.tagName.toLowerCase()")
            if tag not in ("a", "button"):
                continue
            label = _element_label(el).lower()
            if len(label) < 6:
                continue
            if any(w in label for w in _SKIP_RESULT):
                continue
            href = (el.get_attribute("href") or "").lower()
            if is_yt:
                if "/watch" in href or "v=" in href:
                    return i + 1
                if len(label) > 12 and "inscrever" not in label and "subscribe" not in label:
                    return i + 1
            else:
                if href and "google." in href and "/search" in href:
                    continue
                if href and href.startswith("/search"):
                    continue
                if len(label) > 10:
                    return i + 1
        except Exception:
            continue
    return None


def _do_click_first_result(kind: str = "google") -> str:
    idx = _find_clickable_index(kind)
    if not idx:
        return (
            "Não achei um link clicável nos resultados — role a página ou diga qual número clicar.\n"
            + _snapshot()
        )
    return _do_click(idx)


def _do_google_search_and_open(query: str) -> str:
    """Pesquisa no Google e abre o primeiro resultado orgânico."""
    q = (query or "").strip()
    if not q:
        return "Consulta vazia."
    url = f"https://www.google.com/search?q={urllib.parse.quote_plus(q)}"
    open_fb = _do_open(url)
    idx = _find_clickable_index("google")
    if not idx:
        return (
            f"Pesquisa '{q}' aberta no painel. Primeiro resultado não identificado automaticamente.\n"
            + open_fb.split("\n", 1)[-1][:600]
        )
    click_fb = _do_click(idx)
    return f"Pesquisa '{q}' → cliquei no resultado {idx}.\n{click_fb}"


async def _run(fn, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_EXECUTOR, fn, *args)


async def open_url(url: str) -> str:
    return await _run(_do_open, url)


async def read_page() -> str:
    return await _run(_do_read)


async def click(number: int) -> str:
    return await _run(_do_click, number)


async def type_text(number: int, text: str, press_enter: bool = False) -> str:
    return await _run(_do_type, number, text, press_enter)


async def scroll(direction: str) -> str:
    return await _run(_do_scroll, direction)


async def click_at(xf: float, yf: float) -> str:
    return await _run(_do_click_at, xf, yf)


async def scroll_by(dy: int) -> str:
    return await _run(_do_scroll_by, dy)


async def go_back() -> str:
    return await _run(_do_back)


async def press_key(keys: str) -> str:
    return await _run(_do_press_key, keys)


async def carousel_slide(post_url: str, slide: int) -> str:
    return await _run(_do_carousel_slide, post_url, slide)


async def close() -> str:
    return await _run(_do_close)


async def click_first_result(kind: str = "google") -> str:
    return await _run(_do_click_first_result, kind)


async def google_search_and_open(query: str) -> str:
    return await _run(_do_google_search_and_open, query)


async def youtube_search_and_play(query: str) -> str:
    url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus((query or '').strip())}"
    await _run(_do_open, url)
    return await _run(_do_click_first_result, "youtube")


def _find_search_input() -> Optional[int]:
    """Índice 1-based do campo de busca na página atual."""
    global _elements
    if not _elements:
        _snapshot()
    hints = ("search", "busca", "pesquis", "query", "procur", "buscar")
    for i, el in enumerate(_elements):
        try:
            tag = el.evaluate("e => e.tagName.toLowerCase()")
            if tag not in ("input", "textarea"):
                continue
            blob = " ".join(
                [
                    el.get_attribute("placeholder") or "",
                    el.get_attribute("aria-label") or "",
                    el.get_attribute("name") or "",
                    el.get_attribute("id") or "",
                ]
            ).lower()
            itype = (el.get_attribute("type") or "text").lower()
            if itype in ("hidden", "password", "checkbox", "radio", "submit"):
                continue
            if any(h in blob for h in hints) or (tag == "input" and itype in ("text", "search", "")):
                return i + 1
        except Exception:
            continue
    return None


def _do_site_search(query: str, site: str = "google") -> str:
    """Pesquisa dentro de Google, YouTube, Instagram ou site específico (site:domínio)."""
    q = (query or "").strip()
    site = (site or "google").strip().lower()
    if not q:
        return "Consulta vazia."
    if site in ("youtube", "yt"):
        open_fb = _do_open(
            f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(q)}"
        )
        click_fb = _do_click_first_result("youtube")
        return f"YouTube '{q}'.\n{click_fb or open_fb}"
    if site in ("instagram", "ig", "insta"):
        open_fb = _do_open("https://www.instagram.com")
        idx = _find_search_input()
        if idx:
            typed = _do_type(idx, q, True)
            return f"Instagram — busca '{q}'.\n{typed}"
        return (
            f"Instagram aberto para '{q}'. Campo de busca não localizado — "
            f"use browse_read e browse_click.\n{open_fb}"
        )
    if site not in ("google", "web", "geral", ""):
        if "." in site and " " not in site:
            q = f"site:{site} {q}"
    return _do_google_search_and_open(q)


async def site_search(query: str, site: str = "google") -> str:
    return await _run(_do_site_search, query, site)


def has_session() -> bool:
    """True quando o painel Google está ativo na UI (não conta warm-up headless)."""
    return bool(_panel_active)


def has_playwright_page() -> bool:
    """True se o Playwright já tem página (warm-up / navegação anterior)."""
    if _page is None:
        return False
    try:
        _ = _page.url
        return True
    except Exception:
        return False


def mark_panel_active(active: bool = True) -> None:
    """Frontend sinaliza que o painel Google está aberto (persiste entre reloads)."""
    global _panel_active
    _panel_active = bool(active)


async def warm_up() -> None:
    """Pré-aquece o navegador headless no boot p/ a 1a navegação ser instantânea."""
    try:
        await _run(_ensure_page)
    except Exception:
        pass


def _extract_google_query(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
        if "google." in parsed.netloc:
            qs = urllib.parse.parse_qs(parsed.query)
            if "q" in qs and qs["q"]:
                return qs["q"][0]
    except Exception:
        pass
    return ""


def _thumb_screenshot() -> Optional[str]:
    if _page is None:
        return None
    try:
        raw = _page.screenshot(type="jpeg", quality=72, scale="css", full_page=False)
        return base64.b64encode(raw).decode("ascii")
    except Exception:
        return None


_BLANK_URLS = {"", "about:blank", "about:newtab", "chrome://newtab/", "edge://newtab/"}


def has_visible_page(url: str) -> bool:
    """Página de conteúdo real. about:blank vira retângulo branco no painel HUD."""
    u = (url or "").strip().lower()
    if not u or u in _BLANK_URLS:
        return False
    return u.startswith(("http://", "https://", "file://"))


def _get_preview_sync() -> Dict[str, Any]:
    if _page is None:
        return {}
    try:
        url = _page.url or ""
        title = _page.title() or ""
    except Exception:
        return {}
    if not has_visible_page(url):
        return {}
    query = _extract_google_query(url)
    # YouTube: título + legendas na tela + descrição curta (melhor para co-assistir)
    body = ""
    try:
        if "youtube.com" in (url or "").lower() or "youtu.be" in (url or "").lower():
            body = _page.evaluate(
                """() => {
                  const t = document.querySelector('h1.ytd-watch-metadata yt-formatted-string, h1 yt-formatted-string, h1.title')?.innerText
                    || document.title || '';
                  const caps = Array.from(document.querySelectorAll('.ytp-caption-segment'))
                    .map(e => e.innerText).filter(Boolean).join(' ').slice(0, 280);
                  const desc = document.querySelector('#description-inline-expander, ytd-expander #content, #description')?.innerText || '';
                  const ch = document.querySelector('#channel-name, ytd-channel-name a, #owner #text')?.innerText || '';
                  return [t, ch && ('Canal: ' + ch), caps && ('Legenda: ' + caps), desc.slice(0, 320)]
                    .filter(Boolean).join(' | ');
                }"""
            ) or ""
        if not body:
            body = _page.evaluate("() => document.body.innerText") or ""
    except Exception:
        try:
            body = _page.evaluate("() => document.body.innerText") or ""
        except Exception:
            body = ""
    body = " ".join(str(body).split())
    if len(body) > 900:
        body = body[:900] + " [...]"
    return {
        "url": url,
        "title": title,
        "query": query,
        "text": body,
        "image": _thumb_screenshot(),
    }


async def get_preview() -> Dict[str, Any]:
    return await _run(_get_preview_sync)


def _do_calango_login_and_studio(image_prompt: str = "") -> str:
    """Login automático Calango (credenciais locais) e abre modo Studio."""
    try:
        from jarvis_credentials import get_calango_login
    except ImportError:
        get_calango_login = lambda: None  # type: ignore

    creds = get_calango_login()
    if not creds:
        return _do_open("https://www.calango.studio/#/studio")

    p = _ensure_page()
    p.goto("https://www.calango.studio/#/login", wait_until="domcontentloaded", timeout=30000)
    p.wait_for_timeout(2000)

    inputs = p.locator("input")
    try:
        if inputs.count() >= 2:
            inputs.nth(0).fill(creds["email"])
            inputs.nth(1).fill(creds["password"])
            inputs.nth(1).press("Enter")
            p.wait_for_timeout(5000)
    except Exception:
        pass

    p.goto("https://www.calango.studio/#/studio", wait_until="domcontentloaded", timeout=30000)
    p.wait_for_timeout(3000)
    global _panel_active
    _panel_active = True
    try:
        p.bring_to_front()
    except Exception:
        pass

    prompt = (image_prompt or "").strip()
    if prompt:
        typed = False
        for sel in ("textarea", "input[type='text']", "[contenteditable='true']"):
            loc = p.locator(sel)
            try:
                if loc.count() > 0 and loc.first.is_visible(timeout=600):
                    loc.first.fill(prompt)
                    typed = True
                    p.wait_for_timeout(900)
                    break
            except Exception:
                continue
        if typed:
            for label in ("Gerar", "Criar", "Generate", "Criar design", "IA"):
                btn = p.get_by_text(label, exact=False)
                try:
                    if btn.count() and btn.first.is_visible(timeout=500):
                        btn.first.click(timeout=4000)
                        p.wait_for_timeout(2800)
                        return (
                            f"Calango Studio logado. Prompt '{prompt[:70]}' enviado — cliquei em {label}.\n"
                            + _snapshot()
                        )
                except Exception:
                    continue
            return (
                f"Calango Studio logado. Prompt '{prompt[:70]}' digitado — confirme o botão Gerar.\n"
                + _snapshot()
            )

    return "Calango Studio aberto e logado, senhor.\n" + _snapshot()


async def calango_login_and_studio(image_prompt: str = "") -> str:
    return await _run(_do_calango_login_and_studio, image_prompt)


def build_nav_url(query_or_url: str = "") -> str:
    """Monta URL para navegação embutida (Google, domínio, link direto)."""
    q = (query_or_url or "").strip()
    if q.startswith(("http://", "https://")):
        return q
    if not q or q.lower() in ("google", "google.com", "www.google.com"):
        return "https://www.google.com"
    if "." in q and " " not in q and not q.lower().startswith(("youtube ", "yt ")):
        return f"https://{q}"
    if q.lower().startswith(("youtube ", "yt ")):
        term = q.split(" ", 1)[1]
        return f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(term)}"
    return f"https://www.google.com/search?q={urllib.parse.quote_plus(q)}"


def preview_from_url(url: str, query: str = "", text: str = "") -> Dict[str, Any]:
    url = (url or "").strip()
    if not query and url:
        query = _extract_google_query(url)
    return {
        "url": url,
        "title": query or url or "Google",
        "query": query,
        "text": (text or "")[:900],
        "image": None,
    }


def preview_from_feedback(tool: str, args: Dict[str, Any], feedback: str) -> Dict[str, Any]:
    url = (args.get("url") or args.get("query") or "").strip()
    m = re.search(r"(https?://\S+)", feedback or "")
    if m:
        url = m.group(1).rstrip(").,")
    query = (args.get("query") or "").strip()
    if not query and url:
        query = _extract_google_query(url)
    if tool == "web_search" and query:
        url = url or f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}"
    if not url and query:
        url = f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}"
    text = feedback or ""
    if "Texto visível:" in text:
        text = text.split("Texto visível:", 1)[-1].strip()
    return preview_from_url(url, query, text)
