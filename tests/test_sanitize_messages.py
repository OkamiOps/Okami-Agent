"""Sanitização de mensagens ANTES de chamar o modelo (port do message_sanitization do Hermes — a única
defesa do Hermes que faltava no Okami e que pega CRASH real). Modelos locais (GLM/Qwen via LMStudio/
Ollama) às vezes emitem SURROGATES solitários (U+D800–DFFF) + control chars que estouram o
`.encode('utf-8')`/json.dumps() do SDK ANTES da requisição → derruba o turno com UnicodeEncodeError."""
from __future__ import annotations


def test_strips_lone_surrogate_and_keeps_text():
    from okami.llm.sanitize import sanitize_text
    out = sanitize_text("preço \ud83d ok")               # surrogate solitário no meio
    assert "\ud83d" not in out and "preço" in out and "ok" in out


def test_keeps_valid_unicode_and_whitespace():
    from okami.llm.sanitize import sanitize_text
    assert sanitize_text("café ☕ 日本語") == "café ☕ 日本語"   # unicode VÁLIDO fica
    assert sanitize_text("a\nb\tc\rd") == "a\nb\tc\rd"          # \n \t \r são legítimos


def test_strips_control_chars():
    from okami.llm.sanitize import sanitize_text
    assert sanitize_text("x\x00y\x07z") == "xyz"               # NUL/bell etc. saem


def test_sanitized_text_is_utf8_encodable():
    from okami.llm.sanitize import sanitize_text
    # ESTE é o crash real: o original estoura o encode; o limpo não.
    sanitize_text("x \ud83d y").encode("utf-8")               # não levanta UnicodeEncodeError


def test_sanitize_messages_str_and_blocks():
    from okami.llm.sanitize import sanitize_messages
    msgs = [{"role": "user", "content": "oi \ud800 mundo"},
            {"role": "assistant", "content": [{"type": "text", "text": "a \udfff b"}]}]
    out = sanitize_messages(msgs)
    assert "\ud800" not in out[0]["content"]
    assert "\udfff" not in out[1]["content"][0]["text"]
    # encode de tudo funciona
    import json
    json.dumps(out).encode("utf-8")


def test_sanitize_messages_failopen_and_passthrough():
    from okami.llm.sanitize import sanitize_messages
    assert sanitize_messages([]) == []
    # item não-dict / sem content passa intacto
    msgs = [{"role": "user"}, "weird"]
    out = sanitize_messages(msgs)
    assert out[0] == {"role": "user"} and out[1] == "weird"


def test_sanitize_messages_does_not_mutate_input():
    from okami.llm.sanitize import sanitize_messages
    original = [{"role": "user", "content": "oi \ud800"}]
    sanitize_messages(original)
    assert original[0]["content"] == "oi \ud800"             # não muta o original (copia)


# ── wiring no provider: complete E streaming sanitizam (streaming virou default p/ local) ──
def test_providers_sanitize_handles_list_blocks():
    from okami.llm.providers import _sanitize_messages
    out = _sanitize_messages([{"role": "user", "content": [{"type": "text", "text": "a \ud800 b"}]}])
    assert "\ud800" not in out[0]["content"][0]["text"]      # agora cobre multimodal (antes só str)


def test_streaming_sanitizes_before_request(monkeypatch):
    from types import SimpleNamespace

    import okami.llm.providers as prov
    from okami.llm.streaming import stream_messages_deltas
    spy = {}
    monkeypatch.setattr(prov, "_sanitize_messages",
                        lambda m: spy.__setitem__("called", True) or [{"role": "user", "content": "limpo"}])
    monkeypatch.setattr(prov.transports, "dispatch", lambda pc, m, model, ov: SimpleNamespace(text="ok"))
    cfg = SimpleNamespace(provider=lambda name=None: SimpleNamespace())
    out = list(stream_messages_deltas(cfg, [{"role": "user", "content": "x \ud800"}]))
    assert spy.get("called") and out == ["ok"]               # sanitiza ANTES de despachar
