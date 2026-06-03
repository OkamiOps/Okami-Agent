"""Camada de providers do Okami, sobre LiteLLM.

Fase 0: uma interface única (`complete` / `stream_complete`) que normaliza a chamada
para qualquer backend (Codex/GPT, Claude, MiniMax, MiMo, LMStudio local).
Nas próximas fases isso ganha router por custo/capacidade, fallback/rotação (§5) e
o capability profile adaptativo (§3.5).
"""

from __future__ import annotations

from collections.abc import Iterator

import litellm

from okami.llm import transports
from okami.config import OkamiConfig, ProviderConfig

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
    kw.update(overrides)
    return kw


_key_cursor: dict[str, int] = {}      # rotação round-robin do pool de chaves por provider


def _rotate_key(pc: ProviderConfig) -> str | None:
    pool = pc.key_pool()
    if len(pool) <= 1:
        return pool[0] if pool else None
    i = _key_cursor.get(pc.name, 0) % len(pool)
    _key_cursor[pc.name] = i + 1                  # avança → distribui carga / sai de uma chave em 429
    return pool[i]


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
    via = transports.dispatch(pc, messages, model)
    if via is not None:
        return via
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


def _complete_one(pc, messages, model, response_schema, overrides) -> str:
    via = transports.dispatch(pc, messages, model)
    if via is not None:
        return via
    rf = _response_format(pc, response_schema)
    if rf is not None:
        overrides.setdefault("response_format", rf)
    resp = litellm.completion(**_kwargs(pc, messages, stream=False, model=model, **overrides))
    return resp.choices[0].message.content or ""


def complete_messages(
    cfg: OkamiConfig,
    messages: list[dict],
    *,
    provider: str | None = None,
    model: str | None = None,
    response_schema: dict | None = None,
    _tried: set | None = None,
    **overrides,
) -> str:
    """Completa a partir de uma lista de mensagens (harness §3). FAILOVER (estilo Hermes): se o
    provider falhar, tenta os `fallback:` dele (outro provider) — robustez é a dor nº1 do usuário."""
    pc = cfg.provider(provider)
    pool = pc.key_pool()
    last_exc: Exception | None = None
    for _ in range(max(1, len(pool))):           # credential pool: rotaciona a chave em rate-limit/erro
        ov = dict(overrides)
        if pool:
            ov["_api_key"] = _rotate_key(pc)
        try:
            return _complete_one(pc, messages, model, response_schema, ov)
        except Exception as e:  # noqa: BLE001
            last_exc = e
    # esgotou o pool de chaves → FAILOVER p/ outro provider (estilo Hermes)
    tried = (_tried or set()) | {pc.name}
    for fb in (pc.fallback or []):
        if fb not in tried and fb in cfg.providers:
            try:
                return complete_messages(cfg, messages, provider=fb, response_schema=response_schema,
                                         _tried=tried, **overrides)
            except Exception:  # noqa: BLE001
                continue
    raise last_exc if last_exc else RuntimeError("sem provider disponível")


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
    via = transports.dispatch(pc, messages, model)
    if via is not None:  # transports CLI/OAuth não streamam: devolve de uma vez
        yield via
        return
    for chunk in litellm.completion(
        **_kwargs(pc, messages, stream=True, model=model, **overrides)
    ):
        try:
            delta = chunk.choices[0].delta.content
        except (AttributeError, IndexError):
            delta = None
        if delta:
            yield delta
