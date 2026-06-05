"""redact: mascara segredos conhecidos sem mutilar texto comum."""

from __future__ import annotations

from okami.core.redact import redact


def test_masks_named_secrets():
    assert "sk-livekey1234567890abcd" not in redact("OPENAI_API_KEY=sk-livekey1234567890abcd")
    assert "OPENAI_API_KEY=" in redact("OPENAI_API_KEY=sk-livekey1234567890abcd")  # nome fica
    assert "hunter2" not in redact('{"password": "hunter2"}')
    assert "topsecrettoken" not in redact("MY_TOKEN: topsecrettoken")


def test_masks_provider_tokens():
    assert "redacted" in redact("Authorization: Bearer abcdef1234567890")
    assert "sk-ABCDEFGHIJKLMNOP1234" not in redact("key sk-ABCDEFGHIJKLMNOP1234 done")
    assert "ghp_" in redact("ghp_" + "A" * 36) and "A" * 36 not in redact("ghp_" + "A" * 36)
    assert "AKIA" in redact("AKIAIOSFODNN7EXAMPLE") and "IOSFODNN7EXAMPLE" not in redact("AKIAIOSFODNN7EXAMPLE")


def test_does_not_mangle_normal_text():
    plain = "li o arquivo path=src/main.py e rodei pytest -q (3 passaram)"
    assert redact(plain) == plain
    assert redact("") == "" and redact(None) is None
