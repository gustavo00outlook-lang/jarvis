"""Executores reais de ações no Windows.

Volume e mídia usam teclas virtuais via ctypes (sem dependências).
open_app resolve nomes comuns em pt-BR/en. system_status lê RAM/disco/bateria reais.
"""

import ctypes
import os
import shutil
import subprocess
import urllib.parse
from pathlib import Path
from typing import Any, Dict

IS_WINDOWS = os.name == "nt"

VK = {
    "volume_mute": 0xAD,
    "volume_down": 0xAE,
    "volume_up": 0xAF,
    "media_next": 0xB0,
    "media_previous": 0xB1,
    "media_stop": 0xB2,
    "media_play_pause": 0xB3,
}

JARVIS_PROJECT = str(Path(__file__).resolve().parent.parent)
OBSIDIAN_VAULT = str(Path.home() / "Documents" / "JARVIS-notes")

FOLDER_ALIASES = {
    "downloads": os.path.join(os.path.expanduser("~"), "Downloads"),
    "download": os.path.join(os.path.expanduser("~"), "Downloads"),
    "desktop": os.path.join(os.path.expanduser("~"), "Desktop"),
    "area de trabalho": os.path.join(os.path.expanduser("~"), "Desktop"),
    "documentos": os.path.join(os.path.expanduser("~"), "Documents"),
    "documents": os.path.join(os.path.expanduser("~"), "Documents"),
    "imagens": os.path.join(os.path.expanduser("~"), "Pictures"),
    "pictures": os.path.join(os.path.expanduser("~"), "Pictures"),
    "videos": os.path.join(os.path.expanduser("~"), "Videos"),
    "musicas": os.path.join(os.path.expanduser("~"), "Music"),
    "jarvis": JARVIS_PROJECT,
    "projeto jarvis": JARVIS_PROJECT,
    "jarvis-pro": JARVIS_PROJECT,
    "obsidian": OBSIDIAN_VAULT,
    "vault": OBSIDIAN_VAULT,
    "calango": OBSIDIAN_VAULT,
    "agencia calango": OBSIDIAN_VAULT,
}

APP_ALIASES = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "edge": "msedge",
    "notepad": "notepad",
    "bloco de notas": "notepad",
    "calculadora": "calc",
    "calc": "calc",
    "calculator": "calc",
    "spotify": "spotify:",
    "vscode": "code",
    "vs code": "code",
    "code": "code",
    "explorer": "explorer",
    "arquivos": "explorer",
    "explorador": "explorer",
    "word": "winword",
    "excel": "excel",
    "powerpoint": "powerpnt",
    "terminal": "wt",
    "cmd": "cmd",
    "prompt": "cmd",
    "paint": "mspaint",
    "discord": "discord",
    "whatsapp": "whatsapp:",
    "capcut": "CapCut",
    "cap cut": "CapCut",
    "configurações": "ms-settings:",
    "configuracoes": "ms-settings:",
    "settings": "ms-settings:",
    "câmera": "microsoft.windows.camera:",
    "camera": "microsoft.windows.camera:",
    "obsidian": "obsidian",
    "notion": "notion",
    "steam": "steam:",
}


def _press_key(vk: int, times: int = 1) -> None:
    user32 = ctypes.windll.user32
    for _ in range(times):
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, 2, 0)  # KEYEVENTF_KEYUP


def execute(action_name: str, params: Dict[str, Any]) -> str:
    action_name = (action_name or "none").strip().lower()
    handler = _HANDLERS.get(action_name)
    if handler is None:
        return f"Ação desconhecida: {action_name}"
    try:
        return handler(params)
    except Exception as e:
        return f"Erro em {action_name}: {e}"


def _run_command(params: Dict[str, Any]) -> str:
    cmd = params.get("command") or params.get("cmd") or ""
    if not cmd:
        return "Erro: comando vazio."
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True,
        timeout=30, encoding="utf-8", errors="replace",
    )
    out = (result.stdout or "").strip()
    err = (result.stderr or "").strip()
    parts = [f"Comando executado (returncode {result.returncode})."]
    if out:
        parts.append(f"stdout: {out[:500]}")
    if err:
        parts.append(f"stderr: {err[:300]}")
    return " ".join(parts)


def _open_app(params: Dict[str, Any]) -> str:
    raw = (params.get("name") or params.get("app_name") or "").strip()
    if not raw:
        return "Erro: nome do app vazio."
    target = APP_ALIASES.get(raw.lower(), raw)
    try:
        if target.endswith(":") or "://" in target or os.path.exists(target):
            os.startfile(target)
        else:
            subprocess.Popen(f'start "" "{target}"', shell=True)
        return f"Aplicativo '{raw}' aberto."
    except Exception as e:
        return f"Erro ao abrir '{raw}': {e}"


def _close_app(params: Dict[str, Any]) -> str:
    raw = (params.get("name") or params.get("app_name") or "").strip()
    if not raw:
        return "Erro: nome do app vazio."
    proc = APP_ALIASES.get(raw.lower(), raw).replace(":", "")
    if not proc.lower().endswith(".exe"):
        proc += ".exe"
    result = subprocess.run(["taskkill", "/F", "/IM", proc], capture_output=True, text=True)
    if result.returncode == 0:
        return f"'{raw}' fechado."
    return f"Não consegui fechar '{raw}' (processo {proc} não encontrado?)."


def _set_volume(params: Dict[str, Any]) -> str:
    if not IS_WINDOWS:
        return "Controle de volume disponível apenas no Windows."
    level = params.get("level")
    change = params.get("change")
    if params.get("mute"):
        _press_key(VK["volume_mute"])
        return "Volume silenciado."
    if params.get("unmute"):
        _press_key(VK["volume_mute"])
        return "Volume reativado."
    if level is not None:
        level = max(0, min(100, int(level)))
        _press_key(VK["volume_down"], 50)  # zera (cada tecla = 2 unidades)
        _press_key(VK["volume_up"], round(level / 2))
        return f"Volume definido para {level}%."
    if change:
        steps = max(1, abs(int(change)) // 2)
        _press_key(VK["volume_up"] if int(change) > 0 else VK["volume_down"], steps)
        return f"Volume {'aumentado' if int(change) > 0 else 'reduzido'} em {abs(int(change))}%."
    return "Nenhum parâmetro de volume informado."


def _media_control(params: Dict[str, Any]) -> str:
    if not IS_WINDOWS:
        return "Controle de mídia disponível apenas no Windows."
    command = (params.get("command") or "play_pause").lower()
    key = VK.get(f"media_{command}")
    if key is None:
        return f"Comando de mídia desconhecido: {command}"
    _press_key(key)
    labels = {"play_pause": "play/pause", "next": "próxima faixa", "previous": "faixa anterior", "stop": "parar"}
    return f"Mídia: {labels.get(command, command)} enviado."


def _system_status(params: Dict[str, Any]) -> str:
    parts = []
    if IS_WINDOWS:
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        mem = MEMORYSTATUSEX()
        mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):
            total_gb = mem.ullTotalPhys / (1024 ** 3)
            parts.append(f"RAM: {mem.dwMemoryLoad}% de {total_gb:.0f}GB em uso")

        class SYSTEM_POWER_STATUS(ctypes.Structure):
            _fields_ = [
                ("ACLineStatus", ctypes.c_byte), ("BatteryFlag", ctypes.c_byte),
                ("BatteryLifePercent", ctypes.c_byte), ("Reserved1", ctypes.c_byte),
                ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong),
            ]
        power = SYSTEM_POWER_STATUS()
        if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(power)):
            pct = power.BatteryLifePercent
            if 0 <= pct <= 100:
                fonte = "na tomada" if power.ACLineStatus == 1 else "na bateria"
                parts.append(f"Bateria: {pct}% ({fonte})")

    usage = shutil.disk_usage(os.path.expanduser("~"))
    parts.append(f"Disco: {usage.free / (1024**3):.0f}GB livres de {usage.total / (1024**3):.0f}GB")

    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-c", "(Get-CimInstance Win32_Processor).LoadPercentage"],
            capture_output=True, text=True, timeout=8,
        )
        cpu = (r.stdout or "").strip()
        if cpu.isdigit():
            parts.insert(0, f"CPU: {cpu}%")
    except Exception:
        pass

    return ". ".join(parts) + "."


def _write_note(params: Dict[str, Any]) -> str:
    title = (params.get("title") or "nota").strip().replace("/", "-").replace("\\", "-")
    content = params.get("content") or ""
    path = os.path.join(os.path.expanduser("~"), "Desktop", f"{title}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Nota '{title}' criada na área de trabalho."


def _remember(params: Dict[str, Any]) -> str:
    from conversation_state import update_user_pref
    key = params.get("key") or "nota"
    value = params.get("value") or params.get("content") or ""
    update_user_pref(key, value)
    return f"Memorizado: {key} = {value}."


def _forget(params: Dict[str, Any]) -> str:
    from conversation_state import forget_user_pref
    key = params.get("key") or ""
    forget_user_pref(key)
    return f"Esquecido: {key}."


def _build_nav_url(q: str) -> str:
    query = (q or "").strip()
    if query.startswith(("http://", "https://")):
        return query
    if not query or query.lower() in ("google", "google.com", "www.google.com"):
        return "https://www.google.com"
    if "." in query and " " not in query:
        return f"https://{query}"
    if query.lower().startswith(("youtube ", "yt ")):
        term = query.split(" ", 1)[1]
        return f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(term)}"
    return f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}"


def _open_folder(params: Dict[str, Any]) -> str:
    raw = (params.get("folder") or params.get("name") or params.get("path") or "").strip()
    if not raw:
        return "Erro: pasta não informada."
    key = raw.lower()
    target = FOLDER_ALIASES.get(key)
    if not target and os.path.isdir(raw):
        target = raw
    if not target:
        return f"Pasta '{raw}' não reconhecida. Use: downloads, desktop, documentos, jarvis, obsidian."
    if not os.path.isdir(target):
        return f"Caminho não encontrado: {target}"
    try:
        os.startfile(target)
        label = os.path.basename(target) or target
        return f"Pasta '{label}' aberta no Explorer."
    except Exception as e:
        return f"Erro ao abrir pasta '{raw}': {e}"


def _open_browser_search(params: Dict[str, Any]) -> str:
    """Navegação via Playwright headless — painel JARVIS, nunca Chrome externo."""
    q = (params.get("query") or params.get("q") or params.get("url") or "").strip()
    url = _build_nav_url(q)
    try:
        import asyncio
        import web_browser

        return asyncio.run(web_browser.open_url(url))
    except Exception as e:
        return f"Erro ao abrir no painel JARVIS: {e}"


def _none(params: Dict[str, Any]) -> str:
    return "Nenhuma ação executada."


_HANDLERS = {
    "none": _none,
    "run_command": _run_command,
    "open_folder": _open_folder,
    "open_app": _open_app,
    "close_app": _close_app,
    "set_volume": _set_volume,
    "volume": _set_volume,
    "media_control": _media_control,
    "system_status": _system_status,
    "show_status": _system_status,
    "write_note": _write_note,
    "remember": _remember,
    "forget": _forget,
    "open_browser_search": _open_browser_search,
    "open_url": _open_browser_search,
    "search_web": _open_browser_search,
}
