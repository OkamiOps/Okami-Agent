"""#11 Onda 2: resiliência de provider/modelo local — edit-format steering, MIME sniff, JSON-repair,
schema-sanitize, stall-vs-truncation."""
from __future__ import annotations


# ── edit-format steering por família (port coding_context._EDIT_FORMAT_GUIDANCE) ──
def test_edit_format_steers_gpt_to_v4a_patch():
    from okami.core.harness.style import model_family_guidance
    g = model_family_guidance("openai/gpt-5.4")
    assert "apply_patch" in g                       # GPT/Codex → V4A mesmo p/ single-file


def test_edit_format_steers_weak_open_to_replace():
    from okami.core.harness.style import model_family_guidance
    g = model_family_guidance("deepseek-chat")
    assert "edit_file" in g                          # família open-weight → str-replace (edit_file)


def test_edit_format_claude_stays_minimal():
    from okami.core.harness.style import model_family_guidance
    assert model_family_guidance("claude-opus-4-8") == ""   # Claude não infla (str-replace já é natural)


# ── MIME magic-byte sniff (port image_routing._sniff_mime_from_bytes) ──
def test_sniff_mime_from_magic_bytes():
    from okami.llm.vision import _sniff_mime_from_bytes
    assert _sniff_mime_from_bytes(b"\x89PNG\r\n\x1a\n....") == "image/png"
    assert _sniff_mime_from_bytes(b"\xff\xd8\xff\xe0") == "image/jpeg"
    assert _sniff_mime_from_bytes(b"GIF89a...") == "image/gif"
    assert _sniff_mime_from_bytes(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert _sniff_mime_from_bytes(b"BM\x00\x00") == "image/bmp"
    assert _sniff_mime_from_bytes(b"not an image") is None


def test_data_uri_uses_sniffed_mime_over_wrong_suffix(tmp_path):
    from okami.llm.vision import _data_uri
    # arquivo com sufixo .png mas bytes JPEG → mime correto vem do sniff (Anthropic dá 400 se mime≠bytes)
    f = tmp_path / "fake.png"
    f.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 20)
    assert _data_uri(f).startswith("data:image/jpeg;base64,")


# ── stall-vs-truncation: distingue truncação (length) de vazio-stall ──
def test_classify_completion_distinguishes_length_from_stall():
    from okami.llm.stream_diag import classify_completion
    from okami.llm.usage import Completion
    assert classify_completion(Completion(text="", finish_reason="length")) == "length_truncation"
    assert classify_completion(Completion(text="oi", finish_reason="stop")) == "complete"
    assert classify_completion(Completion(text="", finish_reason="stop")) == "empty_stall"
    assert classify_completion(Completion(text="", tool_calls=[{"name": "x"}], finish_reason="tool_calls")) == "complete"


def test_empty_but_length_truncated_is_not_treated_as_empty(monkeypatch):
    # completion VAZIA mas finish_reason='length' (modelo gastou tudo em reasoning) NÃO deve virar
    # EmptyResponse → deve retornar p/ o loop fazer length-continuation.
    from okami.llm import providers
    from okami.llm.usage import Completion

    class FakePC:
        name = "p"
        def key_pool(self):
            return []

    class FakeCfg:
        def provider(self, _p=None):
            return FakePC()

    monkeypatch.setattr(providers, "_complete_one",
                        lambda pc, send, model, rs, ov: Completion(text="", finish_reason="length", provider="p"))
    out = providers.complete_messages_ex(FakeCfg(), [{"role": "user", "content": "oi"}], provider="p")
    assert getattr(out, "finish_reason", "") == "length"      # passou, não virou nudge de vazio
