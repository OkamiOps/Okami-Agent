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


def streaming_enabled(cfg, provider: str | None = None) -> bool:
    """Streaming token-a-token ligado? `harness.streaming` explícito SEMPRE vence. Sem ele, o default é
    TIER-AWARE: liga sozinho p/ modelo de PROTOCOLO-TEXTO (json_constrained — tier local/weak), onde o
    streaming é seguro (a ação JSON vem no próprio texto) E mais NECESSÁRIO (modelo local lento: o usuário
    via "💭 thinking…" congelado por todo o prefill+geração). Strong com tool_calls NATIVOS fica OFF (os
    deltas estruturados não passam pelo streaming de texto).

    INVARIANTE (regressão native_tools+minimax, ago/2026): o rail nativo exige `tools=`/`tool_choice=` no
    payload (quem manda é `_complete_one`, via `native_supported(pc)`). O caminho de streaming
    (`stream_messages_deltas`) NUNCA anexa `tools=` — então, se o veredito nativo está ativo p/ este
    provider/modelo, streamar quer dizer chamar o endpoint SEM tools, o modelo não tem function-calling
    p/ usar, devaneia em <think> e não sobra ação parseável (tarefa cai como "rejeitado, sem ação").
    Por isso, nativo ativo → NUNCA streama (tier vira irrelevante), até existir streaming+tools de verdade.
    Usa o MESMO veredito (cache L1/L2) que `_complete_one` consulta — sem probe duplicado, sem descasamento
    de decisão entre o texto do prompt e o payload real da chamada."""
    try:
        h = getattr(cfg, "harness", None) or {}
        explicit = h.get("streaming") if isinstance(h, dict) else getattr(h, "streaming", None)
    except Exception:  # noqa: BLE001
        explicit = None
    if explicit is not None:
        return bool(explicit)
    try:                                                  # default tier-aware (sem provider → off, fail-open)
        pc = cfg.provider(provider)     # MESMO provider que o call site vai de fato usar (não o default cego)
        try:                                              # nativo ativo → payload precisa de tools= → sem streaming
            from okami.llm.native_capability import native_supported
            if native_supported(pc):
                return False
        except Exception:  # noqa: BLE001 — veredito indisponível (fixture de teste, provider incompleto)
            pass           # cai no default tier-aware abaixo (comportamento anterior preservado)
        if (getattr(pc, "tier", "") or "").lower() in ("local", "weak"):
            return True
        return (pc.tool_mode() if hasattr(pc, "tool_mode") else "") == "json_constrained"
    except Exception:  # noqa: BLE001
        return False


def stream_messages_deltas(cfg, messages, *, provider=None, model=None, **overrides):
    """Itera os deltas de texto a partir de MENSAGENS (espelha providers.stream_complete, mas messages-in)."""
    import litellm
    from okami.llm import errors as _err
    from okami.llm import providers as _p
    pc = cfg.provider(provider)
    messages = _p._sanitize_messages(messages)       # surrogate/control char não estoura o encode (idem complete)
    messages = _p._ensure_reasoning_echo(messages, pc)   # DeepSeek-reasoner/Kimi/MiMo exigem reasoning_content
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
        log.warn(f"stream instável ({_err.classify(e).reason}); caindo no robusto.", exc_info=False)
        raise                                        # caller decide o fallback (tem o on_token/usage)


def _tail_prefix_len(s: str, tag: str) -> int:
    """Comprimento do maior SUFIXO de `s` que é PREFIXO de `tag` — o que precisamos segurar porque pode ser
    o começo de uma tag partida no próximo delta (ex.: s termina em '<thi', tag '<think>' → 4)."""
    m = min(len(s), len(tag) - 1)
    for k in range(m, 0, -1):
        if s[-k:] == tag[:k]:
            return k
    return 0


class _ThinkScrubber:
    """Suprime o conteúdo de <think>...</think> no stream de DISPLAY (on_token), lidando com a tag PARTIDA
    entre deltas (paridade Hermes agent/think_scrubber.py). O texto ACUMULADO (Completion) fica INTACTO —
    o harness já tira <think> onde precisa; isto é só p/ o modelo local/reasoning não VAZAR o raciocínio
    ao vivo no Telegram/TUI. `feed(delta)` devolve só a parte visível (fora de think)."""
    _OPEN, _CLOSE = "<think>", "</think>"

    def __init__(self) -> None:
        self._in = False
        self._buf = ""

    def feed(self, delta: str) -> str:
        self._buf += delta
        out: list[str] = []
        while self._buf:
            if not self._in:
                idx = self._buf.find(self._OPEN)
                if idx == -1:                              # sem <think> completo: emite tudo menos um tail que
                    keep = _tail_prefix_len(self._buf, self._OPEN)   # possa ser começo de '<think>' no próximo
                    out.append(self._buf[:len(self._buf) - keep])
                    self._buf = self._buf[len(self._buf) - keep:]
                    break
                out.append(self._buf[:idx])
                self._buf = self._buf[idx + len(self._OPEN):]
                self._in = True
            else:
                idx = self._buf.find(self._CLOSE)
                if idx == -1:                              # ainda dentro do think: descarta, segura só o tail
                    self._buf = self._buf[-(len(self._CLOSE) - 1):] if len(self._buf) >= len(self._CLOSE) else self._buf
                    if _tail_prefix_len(self._buf, self._CLOSE) == 0:
                        self._buf = ""                     # nada que possa ser </think> parcial → limpa
                    break
                self._buf = self._buf[idx + len(self._CLOSE):]
                self._in = False
        return "".join(out)


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
    scrubber = _ThinkScrubber()                          # não VAZA <think> ao vivo no display (o Completion
    #                                                      acumula o texto CRU; scrub é só p/ o on_token)
    try:
        for delta in src:
            if delta:
                chunks.append(delta)                     # acumula CRU (harness parseia/limpa depois)
                if on_token:
                    visible = scrubber.feed(delta)       # só a parte FORA de <think> vai pro display
                    if visible:
                        try:
                            on_token(visible)
                        except Exception:  # noqa: BLE001 — DISPLAY é best-effort: um erro na TUI/edição NÃO
                            pass            # pode truncar a saída do modelo nem mascarar como falha de provider
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
