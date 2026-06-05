"""Camada de providers do Okami, sobre LiteLLM.

Fase 0: uma interface única (`complete` / `stream_complete`) que normaliza a chamada
para qualquer backend (Codex/GPT, Claude, MiniMax, MiMo, LMStudio local).
Nas próximas fases isso ganha router por custo/capacidade, fallback/rotação (§5) e
o capability profile adaptativo (§3.5).
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator

import litellm

from okami.llm import errors as _err
from okami.llm import transports
from okami.llm.retry import jittered_backoff
from okami.llm.usage import Completion, as_completion, normalize_usage
from okami.config import OkamiConfig, ProviderConfig


class EmptyResponse(RuntimeError):
    """Provider devolveu resposta vazia — tratado como falha (retry/failover), não como sucesso."""


_SURROGATE = re.compile(r"[\ud800-\udfff]")


def _sanitize_messages(messages: list[dict]) -> list[dict]:
    """Remove surrogates UTF-16 soltos que estouram `json.dumps` (ex.: histórico de modelo
    byte-level). Um char ruim no transcript não pode travar TODO turno até o /new."""
    out = []
    for m in messages:
        c = m.get("content")
        if isinstance(c, str) and _SURROGATE.search(c):
            m = {**m, "content": _SURROGATE.sub("", c)}
        out.append(m)
    return out

# Tolera params não suportados por um provider específico e reduz ruído de log.
litellm.drop_params = True
litellm.suppress_debug_info = True


def _effective_model(pc: ProviderConfig, model: str | None) -> str:
    """Resolve o model efetivo.

    Se o override vier sem prefixo de provider (ex.: '-m qwen3.5-2b-mtp'), herda o
    prefixo de roteamento do model configurado (ex.: 'openai/...') para o LiteLLM
    saber rotear. Override com '/' explícito é respeitado como veio.
    """
    if not model:
        return pc.model
    if "/" in model:
        return model
    if "/" in pc.model:
        prefix = pc.model.split("/", 1)[0]
        return f"{prefix}/{model}"
    return model


# Janela de contexto default por tier (tokens), quando o provider não declara context_window.
_TIER_WINDOW = {"strong": 128000, "weak": 32000, "local": 8192, "unknown": 16000}
# Fração da janela em que disparamos a auto-compaction (§6.4). Ex.: 250K→~180K ≈ 0.72.
COMPACT_RATIO = 0.72


def context_window_tokens(pc: ProviderConfig) -> int:
    return pc.context_window or _TIER_WINDOW.get(pc.tier, 16000)


def compaction_threshold_chars(pc: ProviderConfig, ratio: float = COMPACT_RATIO) -> int:
    """Quando comprimir (em chars), proporcional à janela REAL do modelo (anti-overflow)."""
    return int(context_window_tokens(pc) * pc.chars_per_token * ratio)


def _build_messages(prompt: str, system: str | None) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return messages


def _kwargs(
    pc: ProviderConfig,
    messages: list[dict[str, str]],
    *,
    stream: bool,
    model: str | None,
    **overrides,
) -> dict:
    kw: dict = {
        "model": _effective_model(pc, model),
        "messages": messages,
        "stream": stream,
    }
    if pc.api_base:
        kw["api_base"] = pc.api_base
    key = overrides.pop("_api_key", None) or pc.resolved_key()   # credential pool injeta a chave da vez
    if key:
        kw["api_key"] = key
    kw.update(pc.params)
    if pc.reasoning_effort:                          # esforço de raciocínio (litellm normaliza por provider)
        kw["reasoning_effort"] = pc.reasoning_effort
    kw.update(overrides)                             # override por chamada (/think) vence o default
    kw.setdefault("timeout", 600)                    # NUNCA pendurar p/ sempre numa conexão travada
    return kw


_key_cursor: dict[str, int] = {}      # rotação round-robin do pool de chaves por provider
_key_cooldown: dict[str, float] = {}  # chave -> epoch até quando está parada (tomou 429)


def _available_pool(pc: ProviderConfig, now: float) -> list[str]:
    """Chaves não-parqueadas; se TODAS em cooldown, devolve o pool cheio (não trava)."""
    return [k for k in pc.key_pool() if _key_cooldown.get(k, 0.0) <= now] or pc.key_pool()


def _rotate_key(pc: ProviderConfig, now: float | None = None) -> str | None:
    now = time.time() if now is None else now
    pool = _available_pool(pc, now)
    if len(pool) <= 1:
        return pool[0] if pool else None
    i = _key_cursor.get(pc.name, 0) % len(pool)
    _key_cursor[pc.name] = i + 1                  # avança → distribui carga / sai de uma chave em 429
    return pool[i]


def _park_key(key: str | None, ce, now: float | None = None, ttl: float = 3600.0) -> None:
    """429 numa chave → parqueia por `ttl` (default 1h) p/ não distribuí-la de novo na hora."""
    if key and ce.reason == "rate_limit":
        _key_cooldown[key] = (time.time() if now is None else now) + ttl


def complete(
    cfg: OkamiConfig,
    prompt: str,
    *,
    provider: str | None = None,
    system: str | None = None,
    model: str | None = None,
    **overrides,
) -> str:
    pc = cfg.provider(provider)
    messages = _build_messages(prompt, system)
    via = transports.dispatch(pc, messages, model, overrides)
    if via is not None:
        return as_completion(via).text
    resp = litellm.completion(**_kwargs(pc, messages, stream=False, model=model, **overrides))
    return resp.choices[0].message.content or ""


def _response_format(pc: ProviderConfig, response_schema: dict | None) -> dict | None:
    """Constrained decoding (§3.5): força JSON válido em modelos json_constrained."""
    if response_schema and pc.capability.tool_mode == "json_constrained":
        return {
            "type": "json_schema",
            "json_schema": {"name": "okami_action", "schema": response_schema, "strict": False},
        }
    return None


def _extract_tool_calls(msg) -> list[dict]:
    """tool_calls nativos do litellm → [{"id","name","arguments"}] (vazio = sem function-calling)."""
    out = []
    for tc in (getattr(msg, "tool_calls", None) or []):
        fn = getattr(tc, "function", None)
        out.append({"id": getattr(tc, "id", "") or "",
                    "name": (getattr(fn, "name", "") if fn else "") or "",
                    "arguments": (getattr(fn, "arguments", "") if fn else "") or ""})
    return out


def _complete_one(pc, messages, model, response_schema, overrides) -> Completion:
    via = transports.dispatch(pc, messages, model, overrides)
    if via is not None:
        return as_completion(via)
    rf = _response_format(pc, response_schema)
    if rf is not None:
        overrides.setdefault("response_format", rf)
    if getattr(pc, "native_tools", False) and "tools" not in overrides:   # P0.4: tool-calling nativo (opt-in)
        from okami.core.tools import default_registry, openai_tools
        overrides["tools"] = openai_tools(default_registry())
    resp = litellm.completion(**_kwargs(pc, messages, stream=False, model=model, **overrides))
    choice = resp.choices[0]
    return Completion(text=choice.message.content or "",
                      tool_calls=_extract_tool_calls(choice.message),       # antes JOGADO FORA (P0.4)
                      finish_reason=getattr(choice, "finish_reason", "") or "stop",
                      usage=normalize_usage(getattr(resp, "usage", None), transport="litellm"),
                      provider=pc.name, model=_effective_model(pc, model))


def complete_messages_ex(
    cfg: OkamiConfig,
    messages: list[dict],
    *,
    provider: str | None = None,
    model: str | None = None,
    response_schema: dict | None = None,
    _tried: set | None = None,
    _sleep=time.sleep,
    **overrides,
) -> Completion:
    """Completa a partir de uma lista de mensagens (harness §3) e devolve um `Completion` (texto +
    usage + provider/model que REALMENTE respondeu). Robustez (dor nº1): classifica o erro p/ a
    alavanca (rotacionar chave vs back off vs failover), espera com jitter, parqueia chave em 429,
    e trata RESPOSTA VAZIA como falha (não sucesso) — senão o harness vê turno em branco."""
    messages = _sanitize_messages(messages)          # surrogate solto no histórico não trava o turno
    pc = cfg.provider(provider)
    attempts = max(1, len(pc.key_pool()))
    last_exc: Exception | None = None
    do_fallback = True
    for attempt in range(1, attempts + 1):
        ov = dict(overrides)
        if pc.key_pool():
            ov["_api_key"] = _rotate_key(pc)
        try:
            res = as_completion(_complete_one(pc, messages, model, response_schema, ov))
            if not res.text.strip():                  # vazio = falha de provider, entra no retry/failover
                raise EmptyResponse("resposta vazia do provider")
            if not res.provider:                      # garante served-by mesmo no caminho legado/teste
                res.provider = pc.name
            return res
        except Exception as e:  # noqa: BLE001
            last_exc = e
            ce = _err.classify(e)
            if ce.rotate_key:
                _park_key(ov.get("_api_key"), ce)     # 429 → parqueia a chave
            if not ce.retryable:                      # 400/content-policy/auth-perm → não insiste
                do_fallback = ce.fallback
                break
            do_fallback = do_fallback or ce.fallback
            if attempt < attempts:                    # ainda há chave → espera (jitter) e tenta de novo
                _sleep(jittered_backoff(attempt))
    # esgotou chaves (ou erro não-retriável c/ fallback) → FAILOVER p/ outro provider (estilo Hermes)
    tried = (_tried or set()) | {pc.name}
    if do_fallback:
        for fb in (pc.fallback or []):
            if fb in tried or fb not in cfg.providers:
                continue
            fbc = cfg.provider(fb)
            # pula só quem tem requisito de AUTH não atendido (login/CLI/env key) — tomaria 401 na cara.
            # Provider "bare" (litellm via defaults) segue tentável.
            needs_login = fbc.transport in ("codex_oauth", "minimax_oauth", "claude_cli") and not fbc.ready
            needs_key = bool(fbc.api_key_env) and not fbc.resolved_key()
            if needs_login or needs_key:
                continue
            try:
                return complete_messages_ex(cfg, messages, provider=fb, response_schema=response_schema,
                                            _tried=tried, _sleep=_sleep, **overrides)
            except Exception:  # noqa: BLE001
                continue
    raise last_exc if last_exc else RuntimeError("sem provider disponível")


def complete_messages(cfg: OkamiConfig, messages: list[dict], **kwargs) -> str:
    """Compat: só o texto. Quem quer usage/served-by usa `complete_messages_ex`."""
    return complete_messages_ex(cfg, messages, **kwargs).text


def stream_complete(
    cfg: OkamiConfig,
    prompt: str,
    *,
    provider: str | None = None,
    system: str | None = None,
    model: str | None = None,
    **overrides,
) -> Iterator[str]:
    pc = cfg.provider(provider)
    messages = _build_messages(prompt, system)
    via = transports.dispatch(pc, messages, model, overrides)
    if via is not None:  # transports CLI/OAuth não streamam: devolve de uma vez
        yield via
        return
    # Robustez (dor nº1) também no caminho INTERATIVO: se o stream falha ANTES de qualquer token
    # (429/5xx/timeout/instabilidade), NÃO deixa o turno em branco — cai no caminho robusto
    # (complete_messages_ex: retry + rotação de chave + failover p/ pc.fallback) e entrega de uma vez.
    # Se já streamou parte e quebrar no meio, propaga (não dá p/ refazer limpo sem duplicar).
    produced = False
    try:
        for chunk in litellm.completion(
            **_kwargs(pc, messages, stream=True, model=model, **overrides)
        ):
            try:
                delta = chunk.choices[0].delta.content
            except (AttributeError, IndexError):
                delta = None
            if delta:
                produced = True
                yield delta
        if not produced:                              # stream terminou SEM nada → trata como falha
            raise EmptyResponse("stream vazio")
        return
    except Exception as e:  # noqa: BLE001
        if produced:
            raise                                     # parte já entregue ao chamador → propaga
        from okami import log
        log.warn(f"stream instável ({_err.classify(e).reason}); caindo no caminho robusto (sem streaming).")
        res = complete_messages_ex(cfg, messages, provider=provider, model=model, **overrides)
        if res.text:
            yield res.text
