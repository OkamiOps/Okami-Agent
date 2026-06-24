"""Paridade Hermes (PluginLlm): plugin chama o modelo via ctx.llm.complete, GATED por confiança. Pedir o
provider default sempre passa; trocar de provider exige trusted + allow_provider_override + estar na
allowlist, senão PermissionError. Faz o trust-gating (antes só def) ENFORÇAR numa chamada LLM real."""
from __future__ import annotations

import pytest

from okami.plugins import PluginRegistrar, plugin_context


def test_default_provider_passes_and_is_used():
    reg = PluginRegistrar(plugin_context("p", cfg={"default_provider": "ollama"}), cfg={})
    calls = []

    def fake(cfg, messages, *, provider, model, **kw):
        calls.append(provider)
        return "ok"
    out = reg.llm.complete([{"role": "user", "content": "oi"}], _complete=fake)
    assert out == "ok" and calls == ["ollama"]


def test_untrusted_override_is_blocked():
    reg = PluginRegistrar(plugin_context("p", trust="untrusted", cfg={"default_provider": "ollama"}), cfg={})
    with pytest.raises(PermissionError):
        reg.llm.complete([{"role": "user", "content": "oi"}], provider="openai",
                         _complete=lambda *a, **k: "x")


def test_trusted_override_in_allowlist_is_allowed():
    cfg = {"default_provider": "ollama",
           "plugins": {"allow_provider_override": True, "allowed_providers": ["openai"]}}
    reg = PluginRegistrar(plugin_context("p", trust="trusted", cfg=cfg), cfg={})
    calls = []
    reg.llm.complete([{"role": "user", "content": "oi"}], provider="openai",
                     _complete=lambda c, m, *, provider, model, **k: calls.append(provider))
    assert calls == ["openai"]
