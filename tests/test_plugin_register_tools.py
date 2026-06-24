"""Paridade Hermes (foundation do sistema de plugins): plugins rodam register(ctx) no boot e CONTRIBUEM
tools (ctx.register_tool), em vez de só hooks. Antes: discover_plugins só LISTAVA; o register/PluginContext
era código MORTO (ninguém chamava em runtime). Trust: folder=untrusted, entry_point=trusted."""
from __future__ import annotations

import textwrap

from okami.plugins import (PluginRegistrar, discover_plugins, load_plugin_tools, plugin_context)


class _FakeTool:
    def __init__(self, name):
        self.name = name


def _make_folder_plugin(root, name, register_body):
    d = root / "plugins" / name
    d.mkdir(parents=True)
    (d / "plugin.yaml").write_text(f"name: {name}\n", encoding="utf-8")
    (d / "register.py").write_text(textwrap.dedent(register_body), encoding="utf-8")


def test_folder_plugin_contributes_tool(tmp_path):
    _make_folder_plugin(tmp_path, "greeter", """
        def register(ctx):
            class Greet:
                name = "greet"
            ctx.register_tool(Greet())
    """)
    tools = load_plugin_tools(discover_plugins([str(tmp_path)]))
    assert "greet" in tools                      # register(ctx) rodou e a tool entrou


def test_broken_plugin_does_not_kill_others(tmp_path):
    _make_folder_plugin(tmp_path, "bad", """
        def register(ctx):
            raise RuntimeError("boom")
    """)
    _make_folder_plugin(tmp_path, "good", """
        def register(ctx):
            class Ok:
                name = "ok_tool"
            ctx.register_tool(Ok())
    """)
    tools = load_plugin_tools(discover_plugins([str(tmp_path)]))
    assert "ok_tool" in tools                     # plugin que explode no register não derruba os outros
    assert "boom" not in tools


def test_registrar_collects_by_name():
    r = PluginRegistrar(plugin_context("p"))
    r.register_tool(_FakeTool("a"))
    r.register_tool(_FakeTool("b"))
    assert set(r.tools) == {"a", "b"}


def test_plugin_context_accepts_okamiconfig_object():
    # antes: plugin_context só lia dict → com OkamiConfig dava AttributeError (cfg.get) e a config de
    # plugins era DROPADA (config-drop trap). Agora lê o objeto via getattr.
    from okami.config import build_config
    cfg = build_config({"default_provider": "ollama",
                        "providers": {"ollama": {"model": "x"}, "openai": {"model": "y"}},
                        "plugins": {"allowed_providers": ["ollama", "openai"], "allow_provider_override": True}})
    ctx = plugin_context("p", trust="trusted", cfg=cfg)
    assert ctx.default_provider == "ollama"
    assert ctx.allowed_providers == ("ollama", "openai")
    assert ctx.can_override() is True
