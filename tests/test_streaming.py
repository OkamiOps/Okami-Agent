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
        yield  # noqa: unreachable — generator

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
