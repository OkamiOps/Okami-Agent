"""#16: streaming token-a-token — generate que emite tokens ao vivo e devolve o Completion inteiro."""
from __future__ import annotations


def test_streaming_generate_emits_tokens_and_returns_full():
    from okami.llm.streaming import streaming_generate
    got = []
    comp = streaming_generate(None, [{"role": "user", "content": "oi"}],
                              on_token=got.append, _stream=iter(["Hel", "lo", " mundo"]))
    assert comp.text == "Hello mundo" and got == ["Hel", "lo", " mundo"]


def test_streaming_generate_falls_back_when_stream_dies_before_token():
    from okami.llm.streaming import streaming_generate
    from okami.llm.usage import Completion

    def _boom():
        raise RuntimeError("stream caiu antes do 1º token")
        yield  # generator marker after the intentional exception

    def _fallback():
        return Completion(text="resposta robusta")

    comp = streaming_generate(None, [{"role": "user", "content": "x"}],
                              on_token=lambda t: None, _stream=_boom(), _fallback=_fallback)
    assert comp.text == "resposta robusta"           # caiu no caminho robusto, turno não fica em branco


def test_streaming_generate_empty_stream_falls_back():
    from okami.llm.streaming import streaming_generate
    from okami.llm.usage import Completion
    comp = streaming_generate(None, [{"role": "user", "content": "x"}], on_token=lambda t: None,
                              _stream=iter([]), _fallback=lambda: Completion(text="fallback"))
    assert comp.text == "fallback"                   # stream vazio → fallback (não turno em branco)


def test_streaming_enabled_flag():
    from types import SimpleNamespace
    from okami.llm.streaming import streaming_enabled
    assert streaming_enabled(SimpleNamespace(harness={"streaming": True})) is True
    assert streaming_enabled(SimpleNamespace(harness={})) is False
    assert streaming_enabled(None) is False


# ── default tier-aware (latência): liga sozinho p/ modelo lento de protocolo-texto ──
def _cfg(tier="local", streaming=None, tool_mode="json_constrained"):
    from types import SimpleNamespace
    pc = SimpleNamespace(tier=tier, tool_mode=lambda: tool_mode)
    h = {} if streaming is None else {"streaming": streaming}
    return SimpleNamespace(harness=h, provider=lambda name=None: pc)


def test_streaming_default_on_for_local_and_weak():
    from okami.llm.streaming import streaming_enabled
    assert streaming_enabled(_cfg(tier="local")) is True      # local lento → streaming sozinho
    assert streaming_enabled(_cfg(tier="weak")) is True


def test_streaming_default_off_for_strong_native_tools():
    from okami.llm.streaming import streaming_enabled
    # strong com tool_calls NATIVOS → off (os deltas estruturados não passam pelo streaming de texto)
    assert streaming_enabled(_cfg(tier="strong", tool_mode="native")) is False


def test_streaming_default_on_for_json_text_protocol():
    from okami.llm.streaming import streaming_enabled
    # qualquer provider em json_constrained (protocolo-texto) → streaming é seguro e útil
    assert streaming_enabled(_cfg(tier="unknown", tool_mode="json_constrained")) is True


def test_streaming_explicit_config_overrides_tier():
    from okami.llm.streaming import streaming_enabled
    assert streaming_enabled(_cfg(tier="local", streaming=False)) is False   # explícito vence
    assert streaming_enabled(_cfg(tier="strong", tool_mode="native", streaming=True)) is True


def test_streaming_passes_request_positive_timeout_and_observes_events(monkeypatch):
    from okami.llm.request import RequestContext, RequestTimeouts
    from okami.llm.streaming import streaming_generate

    ctx = RequestContext(RequestTimeouts(total_s=3))
    captured = {}

    def fake_deltas(cfg, messages, **kwargs):
        captured.update(kwargs)
        yield "token"

    monkeypatch.setattr("okami.llm.streaming.stream_messages_deltas", fake_deltas)
    comp = streaming_generate(None, [], request=ctx)

    assert comp.text == "token"
    assert captured["request"] is ctx
    assert 0 < captured["timeout"] <= 3
    assert ctx.first_event_at is not None
    assert ctx.last_event_at is not None


def test_streaming_reraises_request_terminal_error_without_fallback():
    import pytest
    from okami.llm.request import RequestCancelled, RequestContext, RequestTimeouts
    from okami.llm.streaming import streaming_generate

    ctx = RequestContext(RequestTimeouts(total_s=3))
    ctx.cancel("user")
    fallback_calls = []

    with pytest.raises(RequestCancelled, match="user"):
        streaming_generate(None, [], request=ctx, _stream=iter(["visible"]),
                           _fallback=lambda: fallback_calls.append("fallback"))
    assert fallback_calls == []


def test_streaming_close_is_registered_once_and_abort_unblocks_inflight_stream():
    import threading
    from okami.llm.request import RequestCancelled, RequestContext, RequestTimeouts
    from okami.llm.streaming import streaming_generate

    class ClosableStream:
        def __init__(self):
            self.started = threading.Event()
            self.released = threading.Event()
            self.close_calls = 0

        def __iter__(self):
            return self

        def __next__(self):
            self.started.set()
            self.released.wait(1)
            raise StopIteration

        def close(self):
            self.close_calls += 1
            self.released.set()

    ctx = RequestContext(RequestTimeouts(total_s=30), abort_grace_s=0.05)
    stream = ClosableStream()
    result = {}

    def run():
        try:
            streaming_generate(None, [], request=ctx, _stream=stream,
                               _fallback=lambda: (_ for _ in ()).throw(AssertionError("fallback")))
        except BaseException as exc:
            result["error"] = exc

    thread = threading.Thread(target=run)
    thread.start()
    assert stream.started.wait(0.2)
    ctx.cancel("user")
    thread.join(0.3)
    stream.released.set()
    thread.join(0.3)

    assert not thread.is_alive()
    assert isinstance(result["error"], RequestCancelled)
    assert stream.close_calls == 1


def test_streaming_failopen_when_provider_raises():
    from types import SimpleNamespace
    from okami.llm.streaming import streaming_enabled

    def boom(name=None):
        raise KeyError("sem default provider")
    assert streaming_enabled(SimpleNamespace(harness={}, provider=boom)) is False


# ── regressão native_tools+minimax: nativo ativo NUNCA streama (payload real não tem tools=) ──
def _cfg_native(tier="weak", native_tools=None, tool_mode="json_constrained", name="minimax", model="minimax/m3"):
    from types import SimpleNamespace
    pc = SimpleNamespace(tier=tier, tool_mode=lambda: tool_mode, native_tools=native_tools,
                         name=name, model=model, api_base="")
    return SimpleNamespace(harness={}, provider=lambda name=None: pc)


def test_streaming_off_when_native_tools_active_even_on_weak_tier():
    from okami.llm.streaming import streaming_enabled
    # weak tier normalmente liga streaming sozinho — MAS native_tools=True (hint explícito, ex.: minimax)
    # exige tools= no payload, e o caminho de streaming nunca anexa tools → tem que ficar OFF.
    assert streaming_enabled(_cfg_native(tier="weak", native_tools=True)) is False


def test_streaming_on_when_native_tools_explicitly_off():
    from okami.llm.streaming import streaming_enabled
    # native_tools=False (hint explícito) → sem rail nativo → volta pro default tier-aware (weak → True)
    assert streaming_enabled(_cfg_native(tier="weak", native_tools=False)) is True


def test_streaming_on_for_local_tier_without_native():
    from okami.llm.streaming import streaming_enabled
    # local sem native_tools (None) → _is_local(pc) via tier="local" resolve sem probe/rede → False nativo
    assert streaming_enabled(_cfg_native(tier="local", native_tools=None)) is True


# ── FIX 4: has_tools=False permite streaming nativo QUANDO o chamador garante que a chamada não leva tools= ──
def test_streaming_default_none_keeps_old_behavior_when_native():
    from okami.llm.streaming import streaming_enabled
    # has_tools não informado (default None) → comportamento ANTIGO intacto: nativo bloqueia sempre.
    assert streaming_enabled(_cfg_native(tier="weak", native_tools=True)) is False
    assert streaming_enabled(_cfg_native(tier="weak", native_tools=True), has_tools=None) is False


def test_streaming_on_when_native_but_caller_guarantees_no_tools():
    from okami.llm.streaming import streaming_enabled
    # chamador SABE (has_tools=False) que esta chamada específica não vai levar tools= → streaming liberado.
    assert streaming_enabled(_cfg_native(tier="weak", native_tools=True), has_tools=False) is True


def test_streaming_off_when_native_and_caller_confirms_tools():
    from okami.llm.streaming import streaming_enabled
    # has_tools=True é só um reforço explícito do caso de sempre (nativo + tools → off).
    assert streaming_enabled(_cfg_native(tier="weak", native_tools=True), has_tools=True) is False
