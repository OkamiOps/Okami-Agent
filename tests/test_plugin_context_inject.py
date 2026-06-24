"""Paridade Hermes (pre_llm_call / context-injection): plugin registra um provider de contexto por-turno via
ctx.register_context; o gateway chama fn() a cada turno e prependa o texto ao extra_context. Best-effort:
provider que explode é ignorado (não derruba o turno)."""
from __future__ import annotations

import textwrap

from okami.gateway.endpoint import _inject_plugin_context
from okami.plugins import PluginRegistrar, discover_plugins, load_plugin_context, plugin_context


def test_registrar_collects_context_provider():
    r = PluginRegistrar(plugin_context("p"))
    r.register_context(lambda: "status: ok", name="status")
    assert len(r.context_providers) == 1


def test_load_plugin_context_from_folder(tmp_path):
    d = tmp_path / "plugins" / "ctxp"
    d.mkdir(parents=True)
    (d / "plugin.yaml").write_text("name: ctxp\n", encoding="utf-8")
    (d / "register.py").write_text(textwrap.dedent("""
        def register(ctx):
            ctx.register_context(lambda: "hora: meio-dia", name="clock")
    """), encoding="utf-8")
    provs = load_plugin_context(discover_plugins([str(tmp_path)]))
    assert provs and provs[0]["plugin"] == "ctxp" and provs[0]["fn"]() == "hora: meio-dia"


def test_inject_prepends_nonempty_and_keeps_ctx():
    provs = [{"fn": lambda: "PLUGIN-CTX", "name": "x", "plugin": "p"}]
    out = _inject_plugin_context("histórico aqui", provs)
    assert out.startswith("PLUGIN-CTX") and "histórico aqui" in out


def test_inject_skips_broken_provider():
    def boom(): raise RuntimeError("x")
    out = _inject_plugin_context("base", [{"fn": boom}, {"fn": lambda: "OK"}])
    assert out.startswith("OK") and "base" in out          # o que explode é pulado, o bom entra


def test_inject_no_providers_returns_ctx_unchanged():
    assert _inject_plugin_context("base", None) == "base"
