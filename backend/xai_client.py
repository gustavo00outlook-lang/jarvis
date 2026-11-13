"""
Cliente LLM unificado — Google Gemini, xAI Grok ou Ollama local (hermes3).

Modo híbrido (padrão auto): tenta Gemini → xAI → Ollama ao esgotar cota/erro.

Configure em jarvis-pro/.env.local ou C:\\Users\\Micro\\.hermes\\.env:
  GOOGLE_API_KEY=...              # Gemini
  XAI_API_KEY=...                 # Grok
  JARVIS_LLM_PROVIDER=auto        # auto | google | xai | ollama | local
  JARVIS_OLLAMA_MODEL=hermes3     # modelo Ollama (default hermes3)
  JARVIS_OLLAMA_BASE=http://127.0.0.1:11434/v1
  JARVIS_OLLAMA_FALLBACK=1        # 0 = desliga fallback para Ollama
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, List, Optional

try:
    from openai import AsyncOpenAI
except ImportError:
    AsyncOpenAI = None  # type: ignore

GROK_MODEL = "grok-4-fast"
_GEMINI_DEFAULT_FAST = "gemini-2.5-flash"
_GEMINI_DEFAULT_SMART = "gemini-2.5-flash"


def _gemini_fast_model() -> str:
    _load_env_files()
    return (os.getenv("JARVIS_GEMINI_FAST_MODEL") or _GEMINI_DEFAULT_FAST).strip()


def _gemini_smart_model() -> str:
    _load_env_files()
    return (os.getenv("JARVIS_GEMINI_SMART_MODEL") or _GEMINI_DEFAULT_SMART).strip()


def gemini_fast_model() -> str:
    """Modelo Gemini rapido (le .env.local apos boot)."""
    return _gemini_fast_model()


def gemini_smart_model() -> str:
    return _gemini_smart_model()


# Compat imports legados
GEMINI_FAST = _GEMINI_DEFAULT_FAST
GEMINI_SMART = _GEMINI_DEFAULT_SMART
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"
XAI_BASE = "https://api.x.ai/v1"
OLLAMA_MODEL_DEFAULT = "hermes3"
OLLAMA_BASE_DEFAULT = "http://127.0.0.1:11434/v1"

_PREFERRED_MODELS = ["grok-4.6", "grok-4-fast", "grok-4.3", "grok-4", "grok-3-fast", "grok-3", "grok-beta"]
_PREFERRED_FAST = ["grok-4-fast", "grok-4.6", "grok-3-fast"]
_PREFERRED_SMART = ["grok-4.6", "grok-4.3", "grok-4", "grok-3"]

_ENV_PATHS = [
    Path(__file__).resolve().parent.parent / ".env.local",
    (Path.home() / '.hermes' / '.env'),
    (Path.home() / '.hermes' / 'grok.txt'),
]

_active_provider: Optional[str] = None
_resolved_model: Optional[str] = None
_resolved_fast: Optional[str] = None
_resolved_smart: Optional[str] = None
_last_used_provider: Optional[str] = None
_ollama_available_cache: Optional[bool] = None
_clients: dict[str, object] = {}
_provider_exhausted_at: dict[str, float] = {}
_QUOTA_COOLDOWN_SEC = float(os.getenv("JARVIS_QUOTA_COOLDOWN_SEC") or str(6 * 3600))
_QUOTA_STORE = (Path.home() / '.hermes' / 'jarvis_llm_quota.json')


def _load_quota_store() -> None:
    """Recarrega providers esgotados do disco (sobrevive a restart do backend)."""
    import time

    try:
        if not _QUOTA_STORE.is_file():
            return
        data = json.loads(_QUOTA_STORE.read_text(encoding="utf-8"))
        now = time.time()
        for prov, ts in (data.get("exhausted_at") or {}).items():
            try:
                t = float(ts)
            except (TypeError, ValueError):
                continue
            if (now - t) < _QUOTA_COOLDOWN_SEC:
                _provider_exhausted_at[str(prov)] = t
    except Exception:
        pass


def _save_quota_store() -> None:
    try:
        _QUOTA_STORE.parent.mkdir(parents=True, exist_ok=True)
        _QUOTA_STORE.write_text(
            json.dumps({"exhausted_at": _provider_exhausted_at}, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


# Carrega skip de cota assim que o módulo sobe (antes do 1º chat)
_load_quota_store()


def _load_env_files() -> None:
    for path in _ENV_PATHS:
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip("'\"")
            if key and val and not os.getenv(key):
                os.environ[key] = val


_load_env_files()


def _google_key() -> str:
    return (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()


def _xai_key() -> str:
    return (os.getenv("XAI_API_KEY") or "").strip()


def _ollama_base() -> str:
    return (os.getenv("JARVIS_OLLAMA_BASE") or OLLAMA_BASE_DEFAULT).strip().rstrip("/")


def _ollama_model() -> str:
    raw = (os.getenv("JARVIS_OLLAMA_MODEL") or OLLAMA_MODEL_DEFAULT).strip()
    return raw.split(":")[0] if ":" not in raw else raw


def _ollama_smart_model() -> str:
    return (os.getenv("JARVIS_OLLAMA_SMART_MODEL") or _ollama_model()).strip()


def _ollama_runtime_options() -> dict:
    """Contexto e tokens limitados = inferência muito mais rápida no hermes3."""
    ctx = int(os.getenv("JARVIS_OLLAMA_NUM_CTX") or "4096")
    predict = int(os.getenv("JARVIS_OLLAMA_NUM_PREDICT") or "384")
    opts: dict = {"num_ctx": ctx, "num_predict": predict}
    threads = (os.getenv("JARVIS_OLLAMA_NUM_THREAD") or "").strip()
    if threads.isdigit():
        opts["num_thread"] = int(threads)
    return opts


def is_ollama_only() -> bool:
    _load_env_files()
    return _provider_pref() in ("ollama", "local")


def fast_mode_enabled() -> bool:
    """Modo rápido só com Ollama primário — com Gemini, prioriza coerência."""
    raw = (os.getenv("JARVIS_FAST_MODE") or "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        if get_provider() == "google":
            return False
        return True
    return is_ollama_only()


def _ollama_fallback_enabled() -> bool:
    return (os.getenv("JARVIS_OLLAMA_FALLBACK") or "1").strip().lower() not in ("0", "false", "no", "off")


def _provider_pref() -> str:
    return (os.getenv("JARVIS_LLM_PROVIDER") or "auto").strip().lower()


def is_fallbackable_error(err: BaseException) -> bool:
    msg = str(err).lower()
    return any(
        token in msg
        for token in (
            "403",
            "429",
            "quota",
            "resource_exhausted",
            "permission-denied",
            "credits",
            "spending limit",
            "resource has been exhausted",
            "rate limit",
            "too many requests",
        )
    )


def is_provider_skipped(provider: str) -> bool:
    """Pula provider com cota esgotada (cache 6h) ou JARVIS_SKIP_XAI=1."""
    import time

    if provider == "xai" and (os.getenv("JARVIS_SKIP_XAI") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return True
    ts = _provider_exhausted_at.get(provider)
    if not ts:
        return False
    return (time.time() - ts) < _QUOTA_COOLDOWN_SEC


def mark_provider_exhausted(provider: str, err: Optional[BaseException] = None) -> None:
    """Marca cota esgotada e promove fallback (Ollama/Gemini) como primário."""
    import time

    global _active_provider
    _provider_exhausted_at[provider] = time.time()
    _save_quota_store()
    # Promove primário longe do provider morto
    if provider in ("google", "xai"):
        if provider == "xai" and _active_provider in (None, "xai"):
            gk = _google_key()
            if gk and google_key_looks_valid() and not is_provider_skipped("google"):
                _active_provider = "google"
            elif _ollama_fallback_enabled():
                _active_provider = "ollama"
        if provider == "google" and _active_provider in (None, "google"):
            if _ollama_fallback_enabled():
                _active_provider = "ollama"
            elif _xai_key() and not is_provider_skipped("xai"):
                _active_provider = "xai"
    reason = str(err)[:100] if err else "quota"
    print(f"[llm] {provider} sem cota ({reason}) -- pulando por {int(_QUOTA_COOLDOWN_SEC / 3600)}h")


def apply_probe_exhaustion(probe: Optional[dict]) -> None:
    """Após probe no boot, evita retentar xAI/Gemini sem crédito a cada turno."""
    if not probe:
        return
    for name in ("google", "xai"):
        entry = probe.get(name) or {}
        err = entry.get("error") or ""
        if entry.get("configured") and not entry.get("ok") and is_fallbackable_error(
            RuntimeError(err)
        ):
            mark_provider_exhausted(name, RuntimeError(err))


async def check_ollama_available(force: bool = False) -> bool:
    global _ollama_available_cache
    # Só confia no cache positivo. False antigo (boot antes do Ollama) não pode
    # marcar o HUD como OLLAMA_OFFLINE para sempre.
    if not force and _ollama_available_cache is True:
        return True
    try:
        import httpx

        base = _ollama_base().replace("/v1", "")
        async with httpx.AsyncClient(timeout=4) as client:
            r = await client.get(f"{base}/api/tags")
            if r.status_code != 200:
                _ollama_available_cache = False
                return False
            models = [m.get("name", "") for m in r.json().get("models", [])]
            want = _ollama_model()
            want_base = want.split(":")[0]
            ok = any(
                m == want
                or m.startswith(f"{want}:")
                or m == want_base
                or m.startswith(f"{want_base}:")
                for m in models
            )
            _ollama_available_cache = ok
            return ok
    except Exception:
        _ollama_available_cache = False
        return False


def provider_chain() -> List[str]:
    """Ordem de tentativa para chat (auto = Gemini → xAI → Ollama)."""
    _load_env_files()
    pref = _provider_pref()
    gk, xk = _google_key(), _xai_key()
    fb = _ollama_fallback_enabled()

    if pref in ("ollama", "local"):
        return ["ollama"]
    if pref == "google":
        chain: List[str] = []
        if gk:
            chain.append("google")
        if fb:
            chain.append("ollama")
        return chain or ["ollama"]
    if pref == "xai":
        chain = []
        if xk and not is_provider_skipped("xai"):
            chain.append("xai")
        if fb:
            chain.append("ollama")
        return chain or ["ollama"]

    chain = []
    if gk and google_key_looks_valid() and not is_provider_skipped("google"):
        chain.append("google")
    if xk and not is_provider_skipped("xai"):
        chain.append("xai")
    if fb:
        chain.append("ollama")
    return chain or ["ollama"]


def get_provider() -> str:
    """Provider primário configurado (pode fazer fallback em runtime)."""
    global _active_provider
    _load_env_files()
    if _active_provider:
        return _active_provider

    pref = _provider_pref()
    gk, xk = _google_key(), _xai_key()

    if pref in ("ollama", "local"):
        _active_provider = "ollama"
    elif pref == "google":
        _active_provider = "google" if gk else ("ollama" if _ollama_fallback_enabled() else "google")
    elif pref == "xai":
        _active_provider = "xai" if xk else ("ollama" if _ollama_fallback_enabled() else "xai")
    else:
        if gk and google_key_looks_valid() and not is_provider_skipped("google"):
            _active_provider = "google"
        elif xk and not is_provider_skipped("xai"):
            _active_provider = "xai"
        else:
            _active_provider = "ollama"
    return _active_provider


def get_last_used_provider() -> Optional[str]:
    return _last_used_provider


def is_google() -> bool:
    """Primário configurado é Google e há chave — independente do último chat."""
    return get_provider() == "google" and bool(_google_key())


def is_ollama() -> bool:
    return get_provider() == "ollama"


def _primary_model() -> str:
    primary = get_provider()
    if primary == "ollama":
        return _ollama_model()
    if primary == "google":
        return _resolved_model or _gemini_fast_model()
    return _resolved_model or GROK_MODEL


def _primary_fast_model() -> str:
    primary = get_provider()
    if primary == "ollama":
        return _ollama_model()
    if primary == "google":
        return _resolved_fast or _gemini_fast_model()
    return _resolved_fast or _resolved_model or GROK_MODEL


def _primary_smart_model() -> str:
    primary = get_provider()
    if primary == "ollama":
        return _ollama_model()
    if primary == "google":
        return _resolved_smart or _gemini_smart_model()
    return _resolved_smart or _resolved_model or GROK_MODEL


def get_model() -> str:
    """Modelo do provider primário (health, search, APIs auxiliares)."""
    return _primary_model()


def get_fast_model() -> str:
    return _primary_fast_model()


def get_smart_model() -> str:
    if get_provider() == "ollama":
        return _ollama_smart_model()
    return _primary_smart_model()


def get_last_chat_model() -> Optional[str]:
    """Modelo usado na última resposta de chat (após fallback)."""
    if not _last_used_provider:
        return None
    return _model_for_provider(_last_used_provider, None)


def google_key_looks_valid() -> bool:
    key = _google_key()
    if not key:
        return False
    # AI Studio: legado AIzaSy... ou novo prefixo AQ. (2026+)
    return key.startswith("AIza") or key.startswith("AQ.")


def google_uses_native_api() -> bool:
    """Chaves AQ. falham no endpoint OpenAI-compat — usa generateContent nativo."""
    return _google_key().startswith("AQ.")


class _GeminiNativeMessage:
    def __init__(self, content: str) -> None:
        self.content = content
        self.tool_calls = None


class _GeminiNativeChoice:
    def __init__(self, content: str) -> None:
        self.message = _GeminiNativeMessage(content)


class _GeminiNativeCompletion:
    def __init__(self, content: str) -> None:
        self.choices = [_GeminiNativeChoice(content)]


def _messages_to_gemini_contents(messages: List[dict]) -> List[dict]:
    contents: List[dict] = []
    for msg in messages or []:
        role = (msg.get("role") or "user").lower()
        text = msg.get("content")
        if text is None:
            continue
        if isinstance(text, list):
            parts = []
            for block in text:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append({"text": str(block.get("text") or "")})
            if not parts:
                continue
            contents.append(
                {"role": "model" if role == "assistant" else "user", "parts": parts}
            )
            continue
        gem_role = "model" if role == "assistant" else "user"
        if role == "system" and contents:
            prev = contents[-1]
            if prev.get("role") == "user" and prev.get("parts"):
                prev["parts"][0]["text"] = f"{text}\n\n{prev['parts'][0].get('text', '')}"
            else:
                contents.append({"role": "user", "parts": [{"text": str(text)}]})
        else:
            contents.append({"role": gem_role, "parts": [{"text": str(text)}]})
    if not contents:
        contents = [{"role": "user", "parts": [{"text": "ping"}]}]
    return contents


async def _google_native_chat_completions_create(**kwargs: Any) -> _GeminiNativeCompletion:
    import httpx

    key = _google_key()
    if not key:
        raise RuntimeError("GOOGLE_API_KEY ausente.")
    model = _model_for_provider("google", kwargs.get("model"))
    if model.startswith("models/"):
        model = model.split("/", 1)[1]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
    payload: dict = {
        "contents": _messages_to_gemini_contents(kwargs.get("messages") or []),
    }
    gen_cfg: dict = {}
    max_tok = kwargs.get("max_tokens") or kwargs.get("max_completion_tokens")
    if max_tok:
        gen_cfg["maxOutputTokens"] = int(max_tok)
    if kwargs.get("temperature") is not None:
        gen_cfg["temperature"] = float(kwargs["temperature"])
    if gen_cfg:
        payload["generationConfig"] = gen_cfg

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code != 200:
            detail = resp.text[:300]
            raise RuntimeError(f"Gemini native {resp.status_code}: {detail}")
        data = resp.json()
    try:
        parts = data["candidates"][0]["content"].get("parts") or []
        text = ""
        for part in parts:
            if isinstance(part, dict) and part.get("text"):
                text = str(part["text"])
                break
        if not text:
            text = ""
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"Gemini native resposta inesperada: {str(data)[:200]}") from e
    return _GeminiNativeCompletion((text or "").strip())


def warn_google_key_format() -> None:
    key = _google_key()
    if not key:
        return
    if not google_key_looks_valid():
        print(
            "[config] AVISO: GOOGLE_API_KEY não parece chave AI Studio (esperado AIzaSy... ou AQ....). "
            "Gere em https://aistudio.google.com/apikey"
        )


def _model_for_provider(provider: str, requested: Optional[str]) -> str:
    if provider == "ollama":
        return _ollama_model()
    if provider == "google":
        req = (requested or "").lower()
        if "grok" in req or "gemini" not in req:
            return _gemini_fast_model()
        return requested or _gemini_fast_model()
    req = (requested or "").lower()
    if "gemini" in req:
        return GROK_MODEL
    return requested or _resolved_model or GROK_MODEL


def _raw_client_for_provider(provider: str, *, quick: bool = False) -> "AsyncOpenAI":
    if AsyncOpenAI is None:
        raise RuntimeError("openai>=1.30.0 required: pip install openai>=1.30.0")

    cache_key = f"{provider}:{'q' if quick else 'n'}"
    if cache_key in _clients:
        return _clients[cache_key]  # type: ignore

    if provider == "google":
        key = _google_key()
        if not key:
            raise RuntimeError("GOOGLE_API_KEY ausente.")
        client = AsyncOpenAI(api_key=key, base_url=GEMINI_BASE, timeout=120.0)
    elif provider == "xai":
        key = _xai_key()
        if not key:
            raise RuntimeError("XAI_API_KEY ausente.")
        timeout = 12.0 if quick else 3600.0
        client = AsyncOpenAI(api_key=key, base_url=XAI_BASE, timeout=timeout)
    elif provider == "ollama":
        client = AsyncOpenAI(
            api_key="ollama",
            base_url=_ollama_base(),
            timeout=float(os.getenv("JARVIS_OLLAMA_TIMEOUT") or "180"),
        )
    else:
        raise RuntimeError(f"Provider desconhecido: {provider}")

    _clients[cache_key] = client
    return client  # type: ignore


async def chat_completions_create(**kwargs: Any) -> Any:
    """Chat com fallback automático entre providers da chain."""
    global _last_used_provider

    chain = provider_chain()
    errors: List[str] = []
    requested_model = kwargs.get("model")

    for idx, provider in enumerate(chain):
        if provider == "ollama":
            if not await check_ollama_available():
                errors.append("ollama: servidor offline ou modelo ausente")
                continue
        elif provider == "google" and (not _google_key() or not google_key_looks_valid()):
            continue
        elif provider == "xai" and (not _xai_key() or is_provider_skipped("xai")):
            continue

        payload = dict(kwargs)
        payload["model"] = _model_for_provider(provider, requested_model)
        if provider == "ollama":
            extra = dict(payload.get("extra_body") or {})
            opts = dict(extra.get("options") or {})
            opts.update(_ollama_runtime_options())
            extra["options"] = opts
            payload["extra_body"] = extra

        try:
            if provider == "google" and google_uses_native_api():
                resp = await _google_native_chat_completions_create(**payload)
            else:
                quick = idx < len(chain) - 1 and provider == "xai"
                client = _raw_client_for_provider(provider, quick=quick)
                resp = await client.chat.completions.create(**payload)
            if provider != (_last_used_provider or ""):
                print(f"[llm] fallback ativo -> {provider} (model={payload['model']})")
            _last_used_provider = provider
            if provider != get_provider():
                global _active_provider
                _active_provider = provider
            return resp
        except Exception as e:
            errors.append(f"{provider}: {e}")
            if is_fallbackable_error(e):
                mark_provider_exhausted(provider, e)
            can_fallback = is_fallbackable_error(e) or provider == "ollama"
            if idx < len(chain) - 1 and can_fallback:
                print(f"[llm] {provider} falhou ({str(e)[:120]}) -- tentando proximo...")
                continue
            if idx < len(chain) - 1:
                print(f"[llm] {provider} erro nao-recuperavel -- tentando proximo...")
                continue
            raise RuntimeError(
                "Nenhum LLM disponível. " + " | ".join(errors[-3:])
            ) from e

    raise RuntimeError("Nenhum LLM configurado na chain: " + ", ".join(chain))


class _ChatCompletions:
    async def create(self, **kwargs: Any) -> Any:
        return await chat_completions_create(**kwargs)


class _Chat:
    def __init__(self) -> None:
        self.completions = _ChatCompletions()


class HybridLLMClient:
    """Proxy OpenAI-compat — chat com fallback; responses = xAI direto (legado)."""

    def __init__(self) -> None:
        self.chat = _Chat()

    @property
    def responses(self):
        if not _xai_key():
            raise RuntimeError("Responses API (xAI) requer XAI_API_KEY.")
        return _raw_client_for_provider("xai").responses


def get_client() -> HybridLLMClient:
    ensure_key()
    return HybridLLMClient()


async def resolve_model() -> str:
    global _resolved_model, _resolved_fast, _resolved_smart, _ollama_available_cache

    ensure_key()
    primary = get_provider()

    if primary == "ollama":
        _resolved_model = _ollama_model()
        _resolved_fast = _ollama_model()
        _resolved_smart = _ollama_smart_model()
        ollama_ok = await check_ollama_available(force=True)
        print(
            f"[model] JARVIS Ollama local — model={_ollama_model()} "
            f"({'online' if ollama_ok else 'offline'})"
        )
        return _resolved_model

    if primary == "google":
        _resolved_fast = _gemini_fast_model()
        _resolved_smart = _gemini_smart_model()
        _resolved_model = _gemini_fast_model()
        ollama_ok = await check_ollama_available(force=True)
        print(
            f"[model] JARVIS híbrido — primário=Gemini {_gemini_fast_model()}"
            + (f" | fallback=Ollama {_ollama_model()}" if ollama_ok and _ollama_fallback_enabled() else "")
        )
        return _resolved_model

    if _resolved_model:
        return _resolved_model

    key = _xai_key()
    if not key:
        _resolved_model = GROK_MODEL
        return GROK_MODEL

    try:
        import httpx

        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get("https://api.x.ai/v1/models", headers={"Authorization": f"Bearer {key}"})
            r.raise_for_status()
            ids = [m.get("id", "") for m in r.json().get("data", [])]
        for pref in _PREFERRED_FAST:
            if pref in ids:
                _resolved_fast = pref
                break
        for pref in _PREFERRED_SMART:
            if pref in ids:
                _resolved_smart = pref
                break
        for pref in _PREFERRED_MODELS:
            if pref in ids:
                _resolved_model = pref
                break
        if not _resolved_model:
            groks = sorted((i for i in ids if i.startswith("grok")), reverse=True)
            if groks:
                _resolved_model = groks[0]
        if _resolved_model:
            ollama_ok = await check_ollama_available(force=True)
            print(
                f"[model] JARVIS híbrido — primário=xAI {_resolved_model}"
                + (f" | fallback=Ollama {_ollama_model()}" if ollama_ok and _ollama_fallback_enabled() else "")
            )
            return _resolved_model
        print(f"[model] nenhum grok listado; mantendo '{GROK_MODEL}'")
    except Exception as e:
        print(f"[model] xAI falhou ({e}); mantendo '{GROK_MODEL}'")

    _resolved_model = GROK_MODEL
    return GROK_MODEL


def ensure_key() -> None:
    _load_env_files()
    pref = _provider_pref()
    if pref in ("ollama", "local"):
        return
    gk, xk = _google_key(), _xai_key()
    if pref == "google" and not gk and not _ollama_fallback_enabled():
        raise RuntimeError(
            "GOOGLE_API_KEY ausente. Crie em https://aistudio.google.com/apikey "
            "ou use JARVIS_LLM_PROVIDER=ollama"
        )
    if pref == "xai" and not xk and not _ollama_fallback_enabled():
        raise RuntimeError("XAI_API_KEY ausente.")
    if pref == "auto" and not gk and not xk and not _ollama_fallback_enabled():
        raise RuntimeError(
            "Nenhuma chave LLM. Adicione GOOGLE_API_KEY ou use Ollama local."
        )
    get_provider()


_probe_cache_at: float = 0.0
_probe_cache_data: dict = {}


async def probe_ollama_only() -> dict:
    """Probe rápido — só Ollama (modo local, sem pingar nuvem)."""
    _load_env_files()
    gk, xk = _google_key(), _xai_key()
    ok = await check_ollama_available()
    return {
        "google": {
            "configured": bool(gk),
            "valid_format": google_key_looks_valid(),
            "ok": False,
            "error": "skipped — JARVIS_LLM_PROVIDER=ollama",
        },
        "xai": {
            "configured": bool(xk),
            "ok": False,
            "error": "skipped — JARVIS_LLM_PROVIDER=ollama",
        },
        "ollama": {"ok": ok, "error": None if ok else "servidor offline ou modelo ausente"},
    }


async def probe_llm_providers(force: bool = False) -> dict:
    """Testa cada provider com ping mínimo — use após recarregar crédito/chave."""
    import time

    _load_env_files()
    if _provider_pref() in ("ollama", "local") and not force:
        return await probe_ollama_only()

    global _probe_cache_at, _probe_cache_data
    if not force and _probe_cache_data and (time.time() - _probe_cache_at) < 90:
        return _probe_cache_data

    _load_env_files()
    gk, xk = _google_key(), _xai_key()
    result: dict = {
        "google": {
            "configured": bool(gk),
            "valid_format": google_key_looks_valid(),
            "ok": False,
            "error": None,
        },
        "xai": {"configured": bool(xk), "ok": False, "error": None},
        "ollama": {"ok": False, "error": None},
    }

    if gk and not google_key_looks_valid():
        result["google"]["error"] = (
            "formato_invalido — use AIzaSy... ou AQ.... de https://aistudio.google.com/apikey"
        )
    elif gk:
        try:
            if google_uses_native_api():
                await _google_native_chat_completions_create(
                    model=_gemini_fast_model(),
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=32,
                )
            else:
                client = _raw_client_for_provider("google")
                await client.chat.completions.create(
                    model=_gemini_fast_model(),
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=4,
                )
            result["google"]["ok"] = True
        except Exception as e:
            result["google"]["error"] = str(e)[:220]

    if xk:
        try:
            client = _raw_client_for_provider("xai")
            await client.chat.completions.create(
                model=GROK_MODEL,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=4,
            )
            result["xai"]["ok"] = True
        except Exception as e:
            result["xai"]["error"] = str(e)[:220]

    if await check_ollama_available(force=force):
        try:
            client = _raw_client_for_provider("ollama")
            await client.chat.completions.create(
                model=_ollama_model(),
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=4,
            )
            result["ollama"]["ok"] = True
        except Exception as e:
            result["ollama"]["error"] = str(e)[:220]
    else:
        result["ollama"]["error"] = "servidor offline ou modelo ausente"

    apply_probe_exhaustion(result)
    _probe_cache_at = time.time()
    _probe_cache_data = result
    return result


def readiness_label(probe: Optional[dict] = None) -> str:
    """Rótulo curto para /health — sem probe usa só formato de chave."""
    if probe:
        if probe.get("google", {}).get("ok"):
            return "FULL_GEMINI"
        if probe.get("xai", {}).get("ok"):
            return "FULL_XAI"
        if probe.get("ollama", {}).get("ok"):
            return "PARTIAL_OLLAMA"
        return "WAITING_API_CREDIT"
    if google_key_looks_valid():
        return "KEY_OK_PROBE_PENDING"
    if _google_key() or _xai_key():
        return "CONFIGURE_GOOGLE_KEY"
    return "NO_LLM_KEY"


def _read_key(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        m = re.search(r"XAI_API_KEY=['\"]?([^'\"\n]+)", content)
        if m:
            return m.group(1).strip()
    except Exception:
        pass
    return None