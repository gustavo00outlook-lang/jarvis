"""
Visão e controle do desktop — os olhos e as mãos do JARVIS.

Screenshot vira imagem para o Grok (multimodal) analisar; cliques e digitação
acontecem de verdade na tela, com movimento de cursor visível.
pyautogui é importado lazy: sem ele instalado, erro amigável.
"""

import asyncio
import base64
import ctypes
import io
import os
import re
import subprocess
from datetime import datetime
from typing import List, Optional, Tuple

APP_WINDOW_TITLES = {
    "whatsapp": ("whatsapp",),
    "capcut": ("capcut", "cap cut"),
    "chrome": ("chrome", "google chrome"),
    "edge": ("edge", "microsoft edge"),
    "notion": ("notion",),
    "obsidian": ("obsidian",),
    "word": ("word",),
    "excel": ("excel",),
    "powerpoint": ("powerpoint",),
    "spotify": ("spotify",),
    "discord": ("discord",),
    "vscode": ("visual studio code", "vscode"),
}

_pyautogui = None


def _gui():
    global _pyautogui
    if _pyautogui is None:
        try:
            import pyautogui
        except ImportError:
            raise RuntimeError(
                "Automação de desktop indisponível. Rode no terminal: pip install pyautogui pillow"
            )
        pyautogui.FAILSAFE = True  # canto sup. esquerdo aborta
        pyautogui.PAUSE = 0.02  # rápido: pausa mínima entre ações
        _pyautogui = pyautogui
    return _pyautogui


def _capture_b64(max_width: int = 1280, quality: int = 72) -> Tuple[str, Tuple[int, int], Tuple[int, int]]:
    """Captura a tela → (base64 JPEG, tamanho_real, tamanho_enviado)."""
    gui = _gui()
    img = gui.screenshot()
    real = img.size
    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, int(img.height * ratio)))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode(), real, img.size


def _scale_note(real: Tuple[int, int], sent: Tuple[int, int]) -> str:
    return (
        f"Tela real: {real[0]}x{real[1]}px; imagem enviada: {sent[0]}x{sent[1]}px. "
        f"Para clicar, converta coordenadas da imagem para a tela real multiplicando por {real[0] / sent[0]:.3f}."
    )


def _focus_window_by_title_fragments(fragments: Tuple[str, ...]) -> bool:
    """Traz janela ao primeiro plano no Windows (ctypes, sem deps extras)."""
    if os.name != "nt":
        return False
    user32 = ctypes.windll.user32
    found: List[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def _enum_cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = (buf.value or "").lower()
                if any(f in title for f in fragments):
                    found.append(hwnd)
        return True

    user32.EnumWindows(_enum_cb, 0)
    if not found:
        return False
    hwnd = found[0]
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    return True


def focus_app_window(app_key: str, *, retries: int = 2) -> str:
    """Foca janela de app pelo título — essencial antes de look_at_screen."""
    import time

    key = (app_key or "").strip().lower().replace(" ", "")
    frags = APP_WINDOW_TITLES.get(key)
    if not frags:
        frags = (key,) if key else ()
    if not frags:
        return "Nenhum app para focar."
    attempts = max(1, min(int(retries or 2), 6))
    ok = False
    for i in range(attempts):
        ok = _focus_window_by_title_fragments(frags)
        if ok:
            break
        if i < attempts - 1:
            time.sleep(0.65)
    if ok:
        return f"Janela '{app_key}' em foco."
    return f"Janela '{app_key}' não encontrada — capturando tela atual."


def _do_look() -> Tuple[str, List[str]]:
    b64, real, sent = _capture_b64()
    return f"Screenshot capturado. {_scale_note(real, sent)}", [b64]


def _do_watch(seconds: float, frames: int) -> Tuple[str, List[str]]:
    import time
    seconds = max(2.0, min(20.0, seconds))
    frames = max(2, min(6, int(frames)))
    imgs: List[str] = []
    real = sent = (0, 0)
    for i in range(frames):
        b64, real, sent = _capture_b64(max_width=960, quality=62)
        imgs.append(b64)
        if i < frames - 1:
            time.sleep(seconds / (frames - 1))
    return (
        f"Assisti a tela por {seconds:.0f}s ({frames} quadros em sequência). {_scale_note(real, sent)}",
        imgs,
    )


def _do_click(x: int, y: int, double: bool, button: str) -> str:
    gui = _gui()
    w, h = gui.size()
    x = max(0, min(int(x), w - 1))
    y = max(0, min(int(y), h - 1))
    # movimento rápido mas visível (era 0.45s — 3x mais rápido agora)
    gui.moveTo(x, y, duration=0.15, tween=gui.easeOutQuad)
    if double:
        gui.doubleClick()
    else:
        gui.click(button=button if button in ("left", "right", "middle") else "left")
    return f"Cliquei em ({x}, {y})."


def _do_move(x: int, y: int) -> str:
    gui = _gui()
    gui.moveTo(int(x), int(y), duration=0.12, tween=gui.easeOutQuad)
    return f"Cursor em ({int(x)}, {int(y)})."


def _do_type(text: str, press_enter: bool) -> str:
    gui = _gui()
    # typewrite não cobre acentos: clipboard + ctrl+v é confiável em pt-BR
    try:
        import subprocess
        subprocess.run("clip", input=text.encode("utf-16-le"), check=True, shell=True)
        gui.hotkey("ctrl", "v")
    except Exception:
        gui.typewrite(text, interval=0.02)
    if press_enter:
        gui.press("enter")
    return f"Digitei: '{text[:80]}'" + (" e apertei Enter." if press_enter else ".")


def _do_press(keys: str) -> str:
    gui = _gui()
    parts = [k.strip().lower() for k in keys.replace("+", " ").split() if k.strip()]
    if not parts:
        return "Nenhuma tecla informada."
    if len(parts) == 1:
        gui.press(parts[0])
    else:
        gui.hotkey(*parts)
    return f"Teclas pressionadas: {'+'.join(parts)}."


def _do_scroll(amount: int) -> str:
    gui = _gui()
    gui.scroll(int(amount))
    return f"Scroll de {amount}."


async def look_at_screen():
    return await asyncio.to_thread(_do_look)


async def watch_screen(seconds: float = 8, frames: int = 4):
    return await asyncio.to_thread(_do_watch, seconds, frames)


async def click(x: int, y: int, double: bool = False, button: str = "left") -> str:
    return await asyncio.to_thread(_do_click, x, y, double, button)


async def move(x: int, y: int) -> str:
    return await asyncio.to_thread(_do_move, x, y)


async def type_text(text: str, press_enter: bool = False) -> str:
    return await asyncio.to_thread(_do_type, text, press_enter)


async def press(keys: str) -> str:
    return await asyncio.to_thread(_do_press, keys)


async def scroll(amount: int) -> str:
    return await asyncio.to_thread(_do_scroll, amount)


def _do_list_windows(max_items: int = 18) -> str:
    """Lista janelas visíveis com título no Windows."""
    if os.name != "nt":
        return "Listagem de janelas disponível apenas no Windows."
    user32 = ctypes.windll.user32
    titles: List[str] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def _enum_cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = (buf.value or "").strip()
                if title and title not in titles:
                    titles.append(title)
        return True

    user32.EnumWindows(_enum_cb, 0)
    if not titles:
        return "Nenhuma janela com título encontrada."
    shown = titles[: max(1, min(int(max_items), 30))]
    lines = [f"{i + 1}. {t}" for i, t in enumerate(shown)]
    extra = f" (+{len(titles) - len(shown)} ocultas)" if len(titles) > len(shown) else ""
    return f"Janelas abertas ({len(titles)}{extra}):\n" + "\n".join(lines)


def _do_clipboard_read() -> str:
    if os.name != "nt":
        return "Leitura de área de transferência disponível apenas no Windows."
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-c", "Get-Clipboard -Raw"],
            capture_output=True,
            text=True,
            timeout=8,
            encoding="utf-8",
            errors="replace",
        )
        text = (r.stdout or "").strip()
        if not text:
            return "Área de transferência vazia ou sem texto."
        preview = text[:500] + ("…" if len(text) > 500 else "")
        return f"Clipboard ({len(text)} caracteres): {preview}"
    except Exception as e:
        return f"Erro ao ler clipboard: {e}"


def _do_clipboard_copy(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return "Nada para copiar (texto vazio)."
    try:
        subprocess.run(
            "clip",
            input=raw.encode("utf-16-le"),
            check=True,
            shell=True,
            timeout=8,
        )
        preview = raw[:80] + ("…" if len(raw) > 80 else "")
        return f"Copiado para a área de transferência: '{preview}'"
    except Exception as e:
        return f"Erro ao copiar: {e}"


def _do_save_screenshot_obsidian(title: str = "Screenshot") -> str:
    import obsidian_notes

    gui = _gui()
    img = gui.screenshot()
    now = datetime.now()
    safe = re.sub(r"[<>:\"/\\|?*\n\r]", "", (title or "Screenshot")).strip() or "Screenshot"
    safe = re.sub(r"\s+", "-", safe)[:48]
    folder = os.path.join(obsidian_notes.VAULT, "JARVIS", "screenshots")
    os.makedirs(folder, exist_ok=True)
    fname = f"{now:%Y-%m-%d-%H%M%S}-{safe}.png"
    path = os.path.join(folder, fname)
    img.save(path, format="PNG")
    rel_img = os.path.relpath(path, obsidian_notes.VAULT).replace("\\", "/")
    note_title = f"Screenshot {now:%d/%m %H:%M}"
    body = f"![[{fname}]]\n\nCaptura automática do JARVIS — {safe}."
    result = obsidian_notes.save_note_if_new(
        note_title,
        body,
        "screenshot",
        "screenshot,captura",
        subdir=os.path.join("JARVIS", "screenshots"),
    )
    return f"{result} Imagem: {rel_img}"


async def list_open_windows(max_items: int = 18) -> str:
    return await asyncio.to_thread(_do_list_windows, max_items)


async def read_clipboard() -> str:
    return await asyncio.to_thread(_do_clipboard_read)


async def copy_to_clipboard(text: str) -> str:
    return await asyncio.to_thread(_do_clipboard_copy, text)


async def save_screenshot_to_obsidian(title: str = "Screenshot") -> str:
    return await asyncio.to_thread(_do_save_screenshot_obsidian, title)


# ---------- Novas habilidades: drag, focar janela, executar comandos ----------

def _do_drag(x1: int, y1: int, x2: int, y2: int, duration: float = 0.4) -> str:
    gui = _gui()
    w, h = gui.size()
    x1 = max(0, min(int(x1), w - 1)); y1 = max(0, min(int(y1), h - 1))
    x2 = max(0, min(int(x2), w - 1)); y2 = max(0, min(int(y2), h - 1))
    gui.moveTo(x1, y1, duration=0.12, tween=gui.easeOutQuad)
    gui.mouseDown()
    gui.moveTo(x2, y2, duration=max(0.1, float(duration)), tween=gui.easeInOutQuad)
    gui.mouseUp()
    return f"Arrastei de ({x1}, {y1}) para ({x2}, {y2})."


def _do_focus_window(title: str) -> str:
    """Foca qualquer janela cujo título contenha o texto (não só apps conhecidos)."""
    t = (title or "").strip()
    if not t:
        return "Nenhum título informado."
    ok = _focus_window_by_title_fragments((t.lower(),))
    return f"Janela '{t}' em foco." if ok else f"Janela '{t}' não encontrada. Use list_windows para ver as abertas."


def _do_run_command(command: str, timeout: int = 30) -> str:
    """Executa comando PowerShell/cmd e retorna a saída (tarefas no PC)."""
    cmd = (command or "").strip()
    if not cmd:
        return "Nenhum comando informado."
    BLOCKED = ("format ", "del /f /s /q c:\\", "rd /s /q c:\\", "remove-item -recurse c:\\",
               "shutdown", "restart-computer", "diskpart", "cipher /w")
    low = cmd.lower()
    for b in BLOCKED:
        if b in low:
            return f"Comando bloqueado por segurança: contém '{b.strip()}'."
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True, text=True, timeout=max(5, min(int(timeout), 120)),
            encoding="utf-8", errors="replace",
        )
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        result = out if out else (err or f"Comando executado (exit {r.returncode}).")
        if len(result) > 3000:
            result = result[:3000] + "\n... (saída truncada)"
        return f"Saída do comando:\n{result}"
    except subprocess.TimeoutExpired:
        return f"Comando excedeu o tempo limite ({timeout}s)."


def _do_open_path(path: str) -> str:
    """Abre arquivo ou pasta com o aplicativo padrão do Windows."""
    p = (path or "").strip().strip('"')
    if not p:
        return "Nenhum caminho informado."
    expanded = os.path.expandvars(p.replace("~", os.path.expanduser("~")))
    if not os.path.exists(expanded):
        return f"Caminho não encontrado: {expanded}"
    os.startfile(expanded)  # noqa: S606 — comportamento desejado (abre com app padrão)
    kind = "pasta" if os.path.isdir(expanded) else "arquivo"
    return f"Abri o {kind}: {expanded}"


async def drag(x1: int, y1: int, x2: int, y2: int, duration: float = 0.4) -> str:
    return await asyncio.to_thread(_do_drag, x1, y1, x2, y2, duration)


async def focus_window(title: str) -> str:
    return await asyncio.to_thread(_do_focus_window, title)


async def run_command(command: str, timeout: int = 30) -> str:
    return await asyncio.to_thread(_do_run_command, command, timeout)


async def open_path(path: str) -> str:
    return await asyncio.to_thread(_do_open_path, path)
