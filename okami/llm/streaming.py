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

import json
from dataclasses import dataclass, field

from okami.llm.request import RequestCancelled, RequestContext, RequestWatchdogTimeout
from okami.llm.usage import Completion, normalize_usage


@dataclass(frozen=True, slots=True)
class ToolCallDelta:
    index: int
    id: str = ""
    name: str = ""
    arguments: str = ""


@dataclass(frozen=True, slots=True)
class StreamEvent:
    text: str = ""
    reasoning: str = ""
    tool_call: ToolCallDelta | None = None
    finish_reason: str | None = None


@dataclass(slots=True)
class NativeToolCallAccumulator:
    _calls: dict[int, dict[str, str]] = field(default_factory=dict)

    def feed(self, delta: ToolCallDelta) -> None:
        call = self._calls.setdefault(delta.index, {"id": "", "name": "", "arguments": ""})
        if delta.id:
            call["id"] = delta.id
        if delta.name:
            call["name"] = delta.name
        call["arguments"] += delta.arguments

    def completed(self) -> list[dict[str, str]]:
        out = []
        for call in self._calls.values():
            if not call["name"]:
                continue
            try:
                args = json.loads(call["arguments"])
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(args, dict):
                out.append(dict(call))
        return out


def streaming_enabled(cfg, provider: str | None = None, *, has_tools: bool | None = None) -> bool:
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
    Por isso, nativo ativo → NUNCA streama, EXCETO quando o chamador já sabe (e AVISA via `has_tools=False`)
    que ESTA chamada específica não vai levar `tools=` — turno puramente conversacional, sem function-calling
    em jogo. `has_tools=None` (default) preserva o comportamento antigo: bloqueia sempre que nativo, porque
    sem essa informação não dá pra saber se a chamada vai carregar tools.

    FIX 4 (gap Hermes) — POR QUE o parâmetro existe mas fica DORMENTE hoje: o único caller real
    (`okami/runner.py`, fora do escopo deste módulo) decide `_streaming` UMA VEZ por task, ANTES de montar
    `eff2`/`tools` de cada chamada de `generate()` — e naquele fluxo o protocolo de AÇÃO do Okami faz
    `respond`/`task_complete` serem TOOLS de verdade (`_native_tools_for`, runner.py): todo turno nativo
    SEMPRE leva `tools=`, mesmo o "só responder". Não existe hoje, na prática, uma chamada nativa
    verdadeiramente sem tools — então religar streaming exigiria redesenhar o protocolo de ação (fora do
    escopo/arquivos que este fix pode tocar: loop.py/runner.py). Implementamos o parâmetro (testável,
    zero-risco — default None não muda NADA) para o dia em que o caller for ajustado a diferenciar
    "responder puro" de "turno com tools" e puder passar `has_tools=False` nesse caso.
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
            if native_supported(pc) and has_tools is not False:   # has_tools=False: chamador GARANTE sem tools=
                return False
        except Exception:  # noqa: BLE001 — veredito indisponível (fixture de teste, provider incompleto)
            pass           # cai no default tier-aware abaixo (comportamento anterior preservado)
        if (getattr(pc, "tier", "") or "").lower() in ("local", "weak"):
            return True
        return (pc.tool_mode() if hasattr(pc, "tool_mode") else "") == "json_constrained"
    except Exception:  # noqa: BLE001
        return False


def _tool_call_delta(raw, index: int) -> ToolCallDelta:
    if isinstance(raw, dict):
        function = raw.get("function") or {}
        get = raw.get
    else:
        function = getattr(raw, "function", None) or object()
        def get(key, default=None):
            return getattr(raw, key, default)
    if isinstance(function, dict):
        function_get = function.get
    else:
        def function_get(key, default=None):
            return getattr(function, key, default)
    return ToolCallDelta(
        index=int(get("index", index) or index),
        id=get("id", "") or "",
        name=function_get("name", "") or "",
        arguments=function_get("arguments", "") or "",
    )


def stream_messages_events(cfg, messages, *, provider=None, model=None,
                           request: RequestContext | None = None, **overrides):
    """Stream text/reasoning and native tool-call deltas without repairing partial arguments."""
    from okami.llm import providers as _p
    pc = cfg.provider(provider)
    if request is not None:
        request.check()
    overrides = _p._bounded_request_overrides(request, overrides)
    messages = _p._sanitize_messages(messages)       # surrogate/control char não estoura o encode (idem complete)
    messages = _p._ensure_reasoning_echo(messages, pc)   # DeepSeek-reasoner/Kimi/MiMo exigem reasoning_content
    if not hasattr(cfg, "providers"):
        # Legacy injected configs have no target map; retain the compatibility
        # dispatch hook used by older integrations and tests.
        via = _p.transports.dispatch(pc, messages, model, overrides)
    else:
        from okami.llm.target_resolver import TargetResolver
        from okami.llm.transport_registry import CompletionRequest, default_transport_registry

        target = TargetResolver().resolve(cfg, provider=provider, model=model)
        registry = default_transport_registry()
        via = registry.complete(
            target,
            pc,
            CompletionRequest(messages=messages, overrides=dict(overrides), request=request),
        ) if target.transport != "litellm" else None
    if via is not None:                              # transports CLI/OAuth não streamam → entrega de uma vez
        if request is not None:
            request.check()
            if getattr(via, "text", ""):
                request.observe()
        yield StreamEvent(text=getattr(via, "text", "") or "",
                          finish_reason=getattr(via, "finish_reason", "stop"))
        for index, call in enumerate(getattr(via, "tool_calls", ()) or ()):
            yield StreamEvent(tool_call=ToolCallDelta(
                index, id=call.get("id", ""), name=call.get("name", ""),
                arguments=call.get("arguments", "") or ""))
        return
    from okami.llm.target_resolver import TargetResolver
    from okami.llm.transport_registry import CompletionRequest, default_transport_registry

    target = TargetResolver().resolve(cfg, provider=provider, model=model)
    source = default_transport_registry().stream(
        target, pc, CompletionRequest(messages=messages, overrides=dict(overrides), request=request))
    produced = False
    for chunk in source:
        if request is not None:
            request.check()
        if isinstance(chunk, Completion):
            if chunk.text:
                produced = True
                if request is not None:
                    request.observe()
                yield StreamEvent(text=chunk.text, finish_reason=chunk.finish_reason)
            for index, call in enumerate(chunk.tool_calls or ()):
                produced = True
                yield StreamEvent(tool_call=ToolCallDelta(
                    index, id=call.get("id", ""), name=call.get("name", ""),
                    arguments=call.get("arguments", "") or ""))
            continue
        try:
            choice = chunk.choices[0]
            delta = choice.delta
            content = getattr(delta, "content", None) or ""
            reasoning = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None) or ""
            calls = getattr(delta, "tool_calls", None) or ()
            finish = getattr(choice, "finish_reason", None)
        except (AttributeError, IndexError):
            continue
        if content or reasoning:
            produced = True
            if request is not None:
                request.observe()
            yield StreamEvent(text=content, reasoning=reasoning, finish_reason=finish)
        for index, call in enumerate(calls):
            produced = True
            yield StreamEvent(tool_call=_tool_call_delta(call, index), finish_reason=finish)
        if finish and not (content or reasoning or calls):
            yield StreamEvent(finish_reason=finish)
    if request is not None:
        request.check()
    if not produced:
        raise _p.EmptyResponse("stream vazio")


def stream_messages_deltas(cfg, messages, *, provider=None, model=None,
                           request: RequestContext | None = None, **overrides):
    """Itera os deltas de texto a partir de MENSAGENS (espelha providers.stream_complete, mas messages-in)."""
    reasoning_open = False
    for event in stream_messages_events(cfg, messages, provider=provider, model=model,
                                        request=request, **overrides):
        reasoning = event.reasoning
        content = event.text
        if reasoning:
            if not reasoning_open:
                reasoning_open = True
                yield "<think>"
            yield reasoning
        if content:
            if reasoning_open:
                reasoning_open = False
                yield "</think>"
            yield content
    if reasoning_open:
        yield "</think>"


def _tail_prefix_len(s: str, tag: str) -> int:
    """Comprimento do maior SUFIXO de `s` que é PREFIXO de `tag` — o que precisamos segurar porque pode ser
    o começo de uma tag partida no próximo delta (ex.: s termina em '<thi', tag '<think>' → 4). Case-insensitive."""
    m = min(len(s), len(tag) - 1)
    sl = s.lower()
    for k in range(m, 0, -1):
        if sl[-k:] == tag[:k]:
            return k
    return 0


def _find_any(hay_lower: str, tags: tuple[str, ...]) -> tuple[int, int]:
    """Menor índice onde QUALQUER `tag` aparece em `hay_lower` (já minúsculo). Retorna (idx, len(tag)) ou (-1, 0)."""
    best_i, best_l = -1, 0
    for t in tags:
        i = hay_lower.find(t)
        if i != -1 and (best_i == -1 or i < best_i):
            best_i, best_l = i, len(t)
    return best_i, best_l


class _ThinkScrubber:
    """Suprime o conteúdo de <think>/<thinking>/<reasoning>/<thought>…</…> no stream de DISPLAY (on_token),
    lidando com a tag PARTIDA entre deltas (paridade Hermes agent/think_scrubber.py, 5 variantes, case-insensitive).
    O texto ACUMULADO (Completion) fica INTACTO — o harness já tira <think> onde precisa; isto é só p/ o modelo
    local/reasoning não VAZAR o raciocínio ao vivo no Telegram/TUI. `feed(delta)` devolve só a parte visível;
    `flush()` no fim do stream devolve o tail retido (senão os últimos chars da resposta somem se parecerem
    começo de tag) — mas DESCARTA se ainda estava dentro de um think aberto (fail-safe anti-vazamento)."""
    _OPENS = ("<think>", "<thinking>", "<reasoning>", "<thought>")
    _CLOSES = ("</think>", "</thinking>", "</reasoning>", "</thought>")
    _MAXTAG = max(len(t) for t in _OPENS + _CLOSES)

    def __init__(self) -> None:
        self._in = False
        self._buf = ""

    def _tail_keep(self, tags: tuple[str, ...]) -> int:
        return max((_tail_prefix_len(self._buf, t) for t in tags), default=0)

    def feed(self, delta: str) -> str:
        self._buf += delta
        out: list[str] = []
        while self._buf:
            low = self._buf.lower()
            if not self._in:
                idx, tlen = _find_any(low, self._OPENS)
                if idx == -1:                              # sem tag de abertura completa: emite tudo menos um tail
                    keep = self._tail_keep(self._OPENS)    # que possa ser começo de uma tag partida no próximo
                    out.append(self._buf[:len(self._buf) - keep])
                    self._buf = self._buf[len(self._buf) - keep:]
                    break
                out.append(self._buf[:idx])
                self._buf = self._buf[idx + tlen:]
                self._in = True
            else:
                idx, tlen = _find_any(low, self._CLOSES)
                if idx == -1:                              # ainda dentro do think: descarta, segura só o tail
                    keep = self._tail_keep(self._CLOSES)
                    self._buf = self._buf[len(self._buf) - keep:] if keep else ""
                    break
                self._buf = self._buf[idx + tlen:]
                self._in = False
        return "".join(out)

    def flush(self) -> str:
        """Fim do stream: emite o tail retido (fora de think). Se ainda dentro de um think aberto (nunca
        fechou), DESCARTA — melhor perder um think truncado do que vazá-lo."""
        tail = "" if self._in else self._buf
        self._buf = ""
        return tail


def streaming_generate(cfg, messages, *, provider=None, model=None, on_token=None, response_schema=None,
                       _stream=None, _events=None, _fallback=None, request: RequestContext | None = None,
                       **overrides) -> Completion:
    """Streama os tokens (on_token cada delta), acumula e devolve o Completion. Stream que morre antes do
    1º token / vazio → `_fallback()` (= complete_messages_ex robusto). `_stream`/`_fallback` injetáveis."""
    chunks: list[str] = []

    if request is not None:
        request.check()

    def _fb() -> Completion:
        if request is not None:
            request.check()
        if _fallback is not None:
            return _fallback()
        from okami.llm import providers as _p
        return _p._invoke_with_optional_request(
            _p.complete_messages_ex, cfg, messages, provider=provider, model=model,
            response_schema=response_schema, request=request, **overrides)

    stream_overrides = dict(overrides)
    if request is not None:
        from okami.llm import providers as _p
        stream_overrides = _p._bounded_request_overrides(request, stream_overrides)
    stream_overrides["request"] = request
    structured = _events is not None or "tools" in stream_overrides or "tool_choice" in stream_overrides
    src = (_events if _events is not None else
           (stream_messages_events if structured else stream_messages_deltas)(
               cfg, messages, provider=provider, model=model, **stream_overrides)) if _stream is None else _stream
    close = getattr(src, "close", None)
    if request is not None and _stream is not None and callable(close):
        request.register_abort(lambda reason: close())
    scrubber = _ThinkScrubber()                          # não VAZA <think> ao vivo no display (o Completion
    #                                                      acumula o texto CRU; scrub é só p/ o on_token)
    accumulator = NativeToolCallAccumulator()
    finish_reason = "stop"
    saw_structured = False
    try:
        for item in src:
            if request is not None:
                request.check()
            if structured and isinstance(item, StreamEvent):
                if item.tool_call is not None:
                    accumulator.feed(item.tool_call)
                    saw_structured = True
                if item.finish_reason:
                    finish_reason = item.finish_reason
                delta = (f"<think>{item.reasoning}</think>" if item.reasoning else "") + item.text
            else:
                delta = item
            if delta:
                if request is not None:
                    request.observe()
                chunks.append(delta)                     # acumula CRU (harness parseia/limpa depois)
                if on_token:
                    visible = scrubber.feed(delta)       # só a parte FORA de <think> vai pro display
                    if visible:
                        try:
                            on_token(visible)
                        except (RequestCancelled, RequestWatchdogTimeout):
                            raise
                        except Exception:  # noqa: BLE001 — DISPLAY é best-effort: um erro na TUI/edição NÃO
                            pass            # pode truncar a saída do modelo nem mascarar como falha de provider
        if on_token:                                     # fim do stream: emite o tail retido (senão o fim da
            tail = scrubber.flush()                      # resposta some se parecer começo de tag)
            if tail:
                    try:
                        on_token(tail)
                    except (RequestCancelled, RequestWatchdogTimeout):
                        raise
                    except Exception:  # noqa: BLE001
                        pass
    except (RequestCancelled, RequestWatchdogTimeout):
        raise
    except Exception:  # noqa: BLE001 — stream caiu (antes ou no meio)
        if request is not None:
            request.check()
        if chunks or saw_structured:                 # saída parcial não pode ser repetida/fallback
            return Completion(text="".join(chunks), tool_calls=accumulator.completed(),
                              finish_reason=finish_reason,
                              provider=getattr(cfg.provider(provider), "name", "") if cfg else "",
                              usage=normalize_usage(None, transport="litellm"))
        return _fb()
    if request is not None:
        request.check()
    tool_calls = accumulator.completed()
    if not chunks and not tool_calls and not saw_structured:  # stream vazio → robusto
        return _fb()
    text = "".join(chunks)
    name = getattr(cfg.provider(provider), "name", "") if cfg else ""
    return Completion(text=text, tool_calls=tool_calls, finish_reason=finish_reason,
                      provider=name, usage=normalize_usage(None, transport="litellm"))


__all__ = ["StreamEvent", "ToolCallDelta", "NativeToolCallAccumulator", "streaming_enabled",
           "stream_messages_events", "stream_messages_deltas", "streaming_generate"]
