"""Streaming token-a-token (#16) — generate que emite os tokens AO VIVO conforme o modelo gera, e ainda
devolve o `Completion` inteiro pro harness parsear a ação.

Protocolo de texto (JSON-em-texto, o default do Okami): streama os deltas, chama `on_token(delta)` p/ a
camada de display (TUI ao vivo / Telegram por-edição via StreamEditor), acumula o texto e devolve o
Completion. Se o stream cai ANTES do 1º token (429/5xx/instabilidade), cai no caminho ROBUSTO
(complete_messages_ex: retry+rotação+failover) — o turno nunca fica em branco. Native function-calling
fica fora do streaming (os tool_calls vêm em deltas estruturados; aí usa o caminho não-streaming).

Atrás de flag `harness.streaming` (default OFF — não muda o comportamento de quem não ligou).
"""
from __future__ import annotations

from okami.llm.usage import Completion, normalize_usage


def streaming_enabled(cfg) -> bool:
    """True se `harness.streaming` está ligado no config."""
    try:
        h = getattr(cfg, "harness", None) or {}
        return bool(h.get("streaming")) if isinstance(h, dict) else bool(getattr(h, "streaming", False))
    except Exception:  # noqa: BLE001
        return False


def stream_messages_deltas(cfg, messages, *, provider=None, model=None, **overrides):
    """Itera os deltas de texto a partir de MENSAGENS (espelha providers.stream_complete, mas messages-in)."""
    import litellm
    from okami.llm import errors as _err
    from okami.llm import providers as _p
    pc = cfg.provider(provider)
    via = _p.transports.dispatch(pc, messages, model, overrides)
    if via is not None:                              # transports CLI/OAuth não streamam → entrega de uma vez
        yield getattr(via, "text", "") or ""
        return
    produced = False
    try:
        for chunk in litellm.completion(**_p._kwargs(pc, messages, stream=True, model=model, **overrides)):
            try:
                d = chunk.choices[0].delta
                delta = d.content or getattr(d, "reasoning_content", None) or getattr(d, "reasoning", None)
            except (AttributeError, IndexError):
                delta = None
            if delta:
                produced = True
                yield delta
        if not produced:
            raise _p.EmptyResponse("stream vazio")
    except Exception as e:  # noqa: BLE001
        if produced:
            raise                                    # parte já entregue → propaga (não dá p/ refazer limpo)
        from okami import log
        log.warn(f"stream instável ({_err.classify(e).reason}); caindo no robusto.")
        raise                                        # caller decide o fallback (tem o on_token/usage)


def streaming_generate(cfg, messages, *, provider=None, model=None, on_token=None, response_schema=None,
                       _stream=None, _fallback=None, **overrides) -> Completion:
    """Streama os tokens (on_token cada delta), acumula e devolve o Completion. Stream que morre antes do
    1º token / vazio → `_fallback()` (= complete_messages_ex robusto). `_stream`/`_fallback` injetáveis."""
    chunks: list[str] = []

    def _fb() -> Completion:
        if _fallback is not None:
            return _fallback()
        from okami.llm import providers as _p
        return _p.complete_messages_ex(cfg, messages, provider=provider, model=model,
                                       response_schema=response_schema, **overrides)

    src = _stream if _stream is not None else stream_messages_deltas(
        cfg, messages, provider=provider, model=model, **overrides)
    try:
        for delta in src:
            if delta:
                chunks.append(delta)
                if on_token:
                    on_token(delta)
    except Exception:  # noqa: BLE001 — stream caiu (antes ou no meio)
        if chunks:                                   # já streamou parte → entrega o que veio (não duplica)
            return Completion(text="".join(chunks), provider=getattr(cfg.provider(provider), "name", "") if cfg else "",
                              usage=normalize_usage(None, transport="litellm"))
        return _fb()
    if not chunks:                                   # stream vazio → robusto
        return _fb()
    text = "".join(chunks)
    name = getattr(cfg.provider(provider), "name", "") if cfg else ""
    return Completion(text=text, provider=name, usage=normalize_usage(None, transport="litellm"))


__all__ = ["streaming_enabled", "stream_messages_deltas", "streaming_generate"]
