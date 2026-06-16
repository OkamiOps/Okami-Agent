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
