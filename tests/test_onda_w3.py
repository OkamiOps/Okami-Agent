"""#16 Onda 3: PluginContext trust-gated + telemetria de custo por-vendor + live-validation de providers."""
from __future__ import annotations

import pytest


# ── telemetria de custo agregada POR VENDOR ──
def test_summarize_by_vendor_groups_by_provider():
    from okami.llm.usage import summarize_by_vendor
    store = {
        "s1": {"usage": {"input": 100, "output": 10, "requests": 1}, "served_by": "claude/opus-4-8"},
        "s2": {"usage": {"input": 200, "output": 20, "requests": 1}, "served_by": "claude/sonnet"},
        "s3": {"usage": {"input": 50, "output": 5, "requests": 1}, "served_by": "minimax/M3"},
        "s4": {"usage": {"input": 7, "output": 1, "requests": 1}},  # sem served_by → bucket "—"
    }
    by = summarize_by_vendor(store)
    assert by["claude"].input_tokens == 300 and by["claude"].output_tokens == 30   # 2 sessões somadas
    assert by["claude"].requests == 2
    assert by["minimax"].input_tokens == 50
    assert by["—"].input_tokens == 7                                                # não-atribuído


def test_summarize_by_vendor_empty():
    from okami.llm.usage import summarize_by_vendor
    assert summarize_by_vendor({}) == {}


def test_vendor_cost_rows_marks_subscription_included():
    from okami.llm.usage import CanonicalUsage, vendor_cost_rows
    by = {"claude": CanonicalUsage(input_tokens=1000, output_tokens=100, requests=2),
          "minimax": CanonicalUsage(input_tokens=1_000_000, output_tokens=500_000, requests=1)}
    rows = vendor_cost_rows(by, models={"minimax": "MiniMax-M3"})
    rmap = {r["vendor"]: r for r in rows}
    assert rmap["claude"]["cost_status"] == "included"        # assinatura → incluído, sem inventar $
    assert rmap["claude"]["requests"] == 2
    assert rmap["minimax"]["cost_status"] == "estimated"      # pay-per-token c/ pricing → estima $
    assert "1M in" in rmap["minimax"]["tokens"]


# ── PluginContext trust-gated (port do Hermes plugin_llm) ──
def test_plugin_context_blocks_provider_override_when_untrusted():
    from okami.plugins import PluginContext
    ctx = PluginContext(plugin="x", trust="untrusted", default_provider="claude",
                        allowed_providers=("claude", "minimax"), allow_provider_override=False)
    assert ctx.resolve_provider(None) == "claude"             # sem pedido → default
    assert ctx.resolve_provider("claude") == "claude"         # pedir o default → ok
    with pytest.raises(PermissionError):
        ctx.resolve_provider("minimax")                       # override proibido p/ untrusted


def test_plugin_context_allows_override_within_allowlist():
    from okami.plugins import PluginContext
    ctx = PluginContext(plugin="x", trust="trusted", default_provider="claude",
                        allowed_providers=("claude", "minimax"), allow_provider_override=True)
    assert ctx.resolve_provider("minimax") == "minimax"       # trusted + na allowlist → ok
    with pytest.raises(PermissionError):
        ctx.resolve_provider("gemini")                        # fora da allowlist → bloqueia


def test_plugin_context_from_config_defaults_untrusted():
    from okami.plugins import plugin_context
    # plugin de pasta (untrusted por padrão): NÃO pode trocar provider mesmo com allowlist
    ctx = plugin_context("meu-plugin", trust="untrusted",
                         cfg={"default_provider": "claude",
                              "plugins": {"allowed_providers": ["claude", "gemini"],
                                          "allow_provider_override": True}})
    assert ctx.default_provider == "claude"
    with pytest.raises(PermissionError):
        ctx.resolve_provider("gemini")                        # untrusted ignora allow_provider_override


# ── live-validation: pula sem credencial, chama de verdade com credencial ──
def test_live_check_skips_without_credentials(monkeypatch):
    from okami.llm import provider_check
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    rep = provider_check.live_check_transport("gemini_native", pc=None)
    assert rep["skipped"] is True and rep["ok"] is False      # sem chave → pula com graça (não falha)


def test_live_check_calls_when_credentials_present():
    from types import SimpleNamespace

    from okami.llm import provider_check
    from okami.llm.usage import Completion
    pc = SimpleNamespace(name="g", api_key="AIza-FAKE", model="gemini-2.5-flash")
    called = {}

    def _caller(msgs):
        called["msgs"] = msgs
        return Completion(text="pong", provider="g", model="gemini-2.5-flash")

    rep = provider_check.live_check_transport("gemini_native", pc=pc, _caller=_caller)
    assert rep["ok"] is True and rep["live"] is True and "pong" in rep["text"]
    assert called["msgs"]                                       # chamou o caller real


def test_live_check_reports_error_gracefully():
    from types import SimpleNamespace

    from okami.llm import provider_check
    pc = SimpleNamespace(name="g", api_key="AIza-FAKE", model="m")

    def _boom(msgs):
        raise RuntimeError("403 PERMISSION_DENIED")

    rep = provider_check.live_check_transport("gemini_native", pc=pc, _caller=_boom)
    assert rep["ok"] is False and "403" in rep["error"]        # erro real → reportado, não crash
