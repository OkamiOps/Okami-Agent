"""Descoberta de modelos por provider (§3.5).

Híbrido (igual Hermes + OpenClaw):
  - **ao vivo**: `GET {api_base}/models` (OpenAI-compat) → modelos REAIS do servidor (Hermes #7103).
    É o caso do LMStudio/Ollama/proxy/OpenAI/OpenRouter/etc — pega o que está de fato disponível.
  - **catálogo**: assinaturas/OAuth sem `/models` (Codex, Claude) usam a lista embarcada do preset
    (estilo OpenClaw provider plugin catalog).
Nunca quebra: falhou a busca → cai pro catálogo → vazio → o chamador pede o id no texto.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request

# ids que não são modelos de chat (não oferecer no menu).
_SKIP = ("embedding", "embed", "whisper", "tts", "dall-e", "dalle", "moderation",
         "rerank", "image", "audio", "speech", "guard")


def _http_models(api_base: str, key: str | None = None, timeout: float = 8.0) -> list[str]:
    url = api_base.rstrip("/") + "/models"
    req = urllib.request.Request(url)
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
        data = json.loads(r.read().decode("utf-8"))
    items = data.get("data") if isinstance(data, dict) else data
    ids = []
    for m in (items or []):
        mid = m.get("id") if isinstance(m, dict) else str(m)
        if mid:
            ids.append(str(mid))
    return ids


def discover_models(*, api_base: str | None = None, key: str | None = None,
                    transport: str = "litellm", catalog: list[str] | None = None,
                    timeout: float = 8.0) -> tuple[list[str], str]:
    """Devolve (modelos, fonte) — fonte ∈ {'live','catalog','none'}.

    OpenAI-compat (api_base + transport litellm) → busca ao vivo, filtra não-chat.
    Senão usa o catálogo do preset. Tolerante a falha de rede."""
    catalog = list(catalog or [])
    tried = False
    if api_base and transport in ("litellm", "", None):
        tried = True
        try:
            ids = [i for i in _http_models(api_base, key, timeout)
                   if not any(s in i.lower() for s in _SKIP)]
            if ids:
                return sorted(set(ids)), "live"
        except Exception:  # noqa: BLE001 — offline/401 → cai pro catálogo
            pass
    if catalog:
        return catalog, "catalog"
    if api_base and not tried:                    # só se NÃO tentou (ex.: oauth com /models autenticado)
        try:
            ids = _http_models(api_base, key, timeout)
            if ids:
                return sorted(set(ids)), "live"
        except Exception:  # noqa: BLE001
            pass
    return [], "none"


# ============================================================================
# §3.5b — dispatcher multi-provider com cache em disco por fingerprint de token
# (paridade Hermes `provider_model_ids` + fingerprint cache, hermes_cli/models.py ~2264-2670).
# Nunca levanta: qualquer falha de rede/import cai pro catálogo do provider (`pc.models`), e se
# nem isso existir devolve None — o chamador (menu de modelo) pede o id no texto.
# ============================================================================

_CACHE_TTL = 3600.0   # 1h — modelos mudam raro; evita bater rede a cada abertura do menu.
_FETCH_TIMEOUT = 5.0  # curto: descoberta é best-effort, não pode travar o menu.


def _cache_path():
    from okami.home import okami_home
    return okami_home() / "model_list_cache.json"


def _cache_key(provider_id: str, token: str | None) -> str:
    """provider_id + fingerprint do token (nunca o token cru) — troca de chave/conta = cache miss natural."""
    fp = hashlib.sha256((token or "").encode("utf-8")).hexdigest()[:16]
    return f"{provider_id}:{fp}"


def _cache_load() -> dict:
    p = _cache_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _cache_save(data: dict) -> None:
    try:
        from okami.core.safe_io import write_atomic
        p = _cache_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(p, json.dumps(data, indent=2), mode=0o600)
    except Exception:  # noqa: BLE001 — cache é best-effort, nunca derruba a descoberta
        from okami.log import warn
        warn("falha ao gravar model_list_cache.json", exc_info=True)


def _cache_get(key: str, ttl: float = _CACHE_TTL) -> list[str] | None:
    entry = _cache_load().get(key)
    if not isinstance(entry, dict):
        return None
    ts = entry.get("ts", 0)
    if (time.time() - ts) > ttl:
        return None
    models = entry.get("models")
    return list(models) if isinstance(models, list) else None


def _cache_put(key: str, models: list[str]) -> None:
    data = _cache_load()
    data[key] = {"models": list(models), "ts": time.time()}
    _cache_save(data)


def _resolve_token(cfg, provider_id: str, pc, token: str | None) -> tuple[str | None, str]:
    """Devolve (token, kind) — kind ∈ {'api_key','oauth'}. `token` explícito sempre vence."""
    if token:
        kind = "oauth" if (pc is not None and getattr(pc, "auth", "") == "oauth_subscription") else "api_key"
        return token, kind
    if pc is not None:
        try:
            key = pc.resolved_key()
        except Exception:  # noqa: BLE001 — resolved_key não deve derrubar a descoberta
            key = None
        if key:
            return key, "api_key"
    # sem api_key resolvida → tenta OAuth (assinatura). Import tardio: oauth.py pode falhar/mudar
    # sem que a descoberta de modelos pague o preço em import time.
    try:
        from okami.llm import oauth as _oauth
    except Exception:  # noqa: BLE001
        return None, "api_key"
    if provider_id == "codex":
        try:
            tok = _oauth.codex_access_token()
        except Exception:  # noqa: BLE001
            tok = None
        return tok, "oauth"
    fn = getattr(_oauth, f"{provider_id}_access_token", None)
    if callable(fn):
        try:
            tok = fn()
        except Exception:  # noqa: BLE001
            tok = None
        if tok:
            return tok, "oauth"
    return None, "api_key"


def _fetch_generic(pc, token: str | None) -> list[str]:
    """OpenAI-compat (minimax/mimo/openrouter/deepseek/groq/…) — reusa `_http_models` (GET /models,
    Authorization: Bearer <key>, `data[].id`)."""
    api_base = getattr(pc, "api_base", None)
    if not api_base:
        return []
    ids = _http_models(api_base, token, _FETCH_TIMEOUT)
    return [i for i in ids if not any(s in i.lower() for s in _SKIP)]


def _fetch_anthropic(pc, token: str | None, kind: str) -> list[str]:
    """GET {base}/v1/models — `x-api-key` (chave normal) ou `Authorization: Bearer` + o mesmo
    header `anthropic-beta: oauth-2025-04-20` usado no resto do codebase p/ token OAuth (ver
    okami/llm/oauth_anthropic.py:anthropic_inference_headers)."""
    if not token:
        return []
    base = (getattr(pc, "api_base", None) or "https://api.anthropic.com").rstrip("/")
    url = f"{base}/v1/models"
    req = urllib.request.Request(url)
    if kind == "oauth":
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("anthropic-beta", "oauth-2025-04-20")
    else:
        req.add_header("x-api-key", token)
        req.add_header("anthropic-version", "2023-06-01")
    with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as r:  # noqa: S310
        data = json.loads(r.read().decode("utf-8"))
    items = data.get("data") if isinstance(data, dict) else data
    ids = []
    for m in (items or []):
        mid = m.get("id") if isinstance(m, dict) else str(m)
        if mid:
            ids.append(str(mid))
    return ids


def _fetch_codex(token: str | None) -> list[str]:
    """MELHOR-ESFORÇO: lista de modelos expostos pela assinatura ChatGPT/Codex.

    TODO: endpoint/formato NÃO verificados ao vivo — port de hermes_cli/codex_models.py fica p/
    depois (o Hermes resolve isso com lógica própria, ver hermes_cli/models.py ~2264-2495). Aqui
    tentamos um caminho conservador (`/backend-api/codex/models`, mesmos headers anti-Cloudflare
    do `codex_oauth_complete` em transports.py) e qualquer falha cai pro catálogo do provider —
    nunca propaga.
    """
    if not token:
        return []
    from okami.llm.codex_headers import cloudflare_headers
    from okami.llm.oauth import codex_account_id
    try:
        account = codex_account_id()
    except Exception:  # noqa: BLE001
        account = ""
    url = "https://chatgpt.com/backend-api/codex/models"   # TODO: path não confirmado — best-effort
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    for k, v in cloudflare_headers(token, account).items():
        req.add_header(k, v)
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as r:  # noqa: S310
        data = json.loads(r.read().decode("utf-8"))
    items = data.get("data") if isinstance(data, dict) else data
    ids = []
    for m in (items or []):
        mid = m.get("id") if isinstance(m, dict) else str(m)
        if mid:
            ids.append(str(mid))
    return ids


def _catalog_fallback(pc) -> list[str] | None:
    models = list(getattr(pc, "models", None) or []) if pc is not None else []
    return models or None


def provider_models(cfg, provider_id: str, *, token: str | None = None) -> list[str] | None:
    """Dispatcher §3.5b: cache (fingerprint do token) → fetch ao vivo por provider → catálogo
    (`pc.models`) → None. Nunca levanta — falha de rede/import cai sempre no próximo degrau."""
    from okami.log import warn

    providers = getattr(cfg, "providers", None) or {}
    pc = providers.get(provider_id) if hasattr(providers, "get") else None

    tok, kind = _resolve_token(cfg, provider_id, pc, token)

    cache_key = _cache_key(provider_id, tok)
    if tok:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

    fetched: list[str] | None = None
    try:
        transport = getattr(pc, "transport", "") if pc is not None else ""
        if provider_id == "codex" or transport == "codex_oauth":
            fetched = _fetch_codex(tok)
        elif provider_id in ("anthropic", "claude") or "anthropic" in provider_id:
            fetched = _fetch_anthropic(pc, tok, kind)
        else:
            fetched = _fetch_generic(pc, tok)
    except Exception:  # noqa: BLE001 — descoberta ao vivo é best-effort
        warn(f"provider_models: descoberta ao vivo falhou p/ '{provider_id}'", exc_info=True)
        fetched = None

    if fetched:
        if tok:
            _cache_put(cache_key, fetched)
        return fetched

    return _catalog_fallback(pc)


def provider_models_cached(cfg, provider_id: str) -> list[str] | None:
    """Wrapper fino p/ o menu de modelo (`okami/cli/commands/model.py`): mesma coisa que
    `provider_models(cfg, provider_id)`, resolvendo o token e usando o cache em disco por trás —
    drop-in, sem argumento extra além de cfg/provider_id."""
    return provider_models(cfg, provider_id)
