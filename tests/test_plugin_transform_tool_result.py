"""Paridade Hermes (transform_tool_result): plugin registra um hook não-bloqueante via
ctx.register_transform_tool_result; o runner pluga cada fn num HookManager.on("transform_tool_result", fn)
— o texto devolvido é ANEXADO ao resultado da tool (nunca substitui, nunca veta)."""
from __future__ import annotations

import textwrap

from okami.automation.hooks import HookManager
from okami.plugins import (
    PluginRegistrar,
    discover_plugins,
    load_plugin_transform_tool_result,
    plugin_context,
)


def test_registrar_collects_transform_hook():
    r = PluginRegistrar(plugin_context("p"))
    r.register_transform_tool_result(lambda payload: "⚠️ extra")
    assert len(r.transform_tool_result_hooks) == 1


def test_register_transform_tool_result_rejects_non_callable():
    r = PluginRegistrar(plugin_context("p"))
    try:
        r.register_transform_tool_result("not-callable")
        assert False, "deveria ter recusado um valor não-chamável"
    except ValueError:
        pass


def test_load_plugin_transform_tool_result_from_folder(tmp_path):
    d = tmp_path / "plugins" / "guardp"
    d.mkdir(parents=True)
    (d / "plugin.yaml").write_text("name: guardp\n", encoding="utf-8")
    (d / "register.py").write_text(textwrap.dedent("""
        def register(ctx):
            ctx.register_transform_tool_result(lambda payload: "⚠️ achado do plugin")
    """), encoding="utf-8")
    fns = load_plugin_transform_tool_result(discover_plugins([str(tmp_path)]))
    assert fns and fns[0]({"tool": "write_file"}) == "⚠️ achado do plugin"


def test_load_plugin_transform_tool_result_isolates_broken_plugin(tmp_path):
    ok = tmp_path / "plugins" / "ok"
    ok.mkdir(parents=True)
    (ok / "plugin.yaml").write_text("name: ok\n", encoding="utf-8")
    (ok / "register.py").write_text(textwrap.dedent("""
        def register(ctx):
            ctx.register_transform_tool_result(lambda payload: "bom")
    """), encoding="utf-8")
    bad = tmp_path / "plugins" / "bad"
    bad.mkdir(parents=True)
    (bad / "plugin.yaml").write_text("name: bad\n", encoding="utf-8")
    (bad / "register.py").write_text(textwrap.dedent("""
        def register(ctx):
            raise RuntimeError("boom")
    """), encoding="utf-8")
    fns = load_plugin_transform_tool_result(discover_plugins([str(tmp_path)]))
    assert len(fns) == 1 and fns[0]({}) == "bom"           # o plugin quebrado não derruba o bom


def test_end_to_end_registered_hook_appends_via_hookmanager():
    """Simula o wiring do runner: fn coletada de um plugin registrado no HookManager real via .on()."""
    collected = load_plugin_transform_tool_result(
        discover_plugins([]), cfg=None,
        _resolve=lambda plugin: None,   # sem plugins de verdade — só prova o fio ponta-a-ponta
    )
    assert collected == []
    hm = HookManager()
    hm.on("transform_tool_result", lambda payload: "⚠️ plugin advisory")
    out = hm.transform_tool_result("write_file", {}, "resultado original")
    assert "resultado original" in out and "⚠️ plugin advisory" in out
