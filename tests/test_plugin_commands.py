"""Paridade Hermes (ctx.register_command): plugins contribuem slash-commands /nome; o gateway despacha quando
o token não é built-in, chamando handler(args)→str. Isolado (handler que explode não derruba o turno)."""
from __future__ import annotations

import tempfile
import textwrap

from okami.gateway import AgentEndpoint
from okami.plugins import PluginRegistrar, discover_plugins, load_plugin_commands, plugin_context


def test_registrar_collects_commands():
    r = PluginRegistrar(plugin_context("p"))
    r.register_command("greet", lambda args: f"oi {args}", help="cumprimenta")
    assert "greet" in r.commands and r.commands["greet"]["help"] == "cumprimenta"


def test_load_plugin_commands_from_folder(tmp_path):
    d = tmp_path / "plugins" / "hello"
    d.mkdir(parents=True)
    (d / "plugin.yaml").write_text("name: hello\n", encoding="utf-8")
    (d / "register.py").write_text(textwrap.dedent("""
        def register(ctx):
            ctx.register_command("ping", lambda args: "pong " + args)
    """), encoding="utf-8")
    cmds = load_plugin_commands(discover_plugins([str(tmp_path)]))
    assert "ping" in cmds and cmds["ping"]["plugin"] == "hello"


class _Ch:
    def __init__(self): self.sent = []
    def poll(self): return []
    def send(self, cid, text): self.sent.append(str(text))
    def allowed(self, cid): return True


def _ep():
    return AgentEndpoint("dev", cfg=None, ws=tempfile.mkdtemp(), channel=_Ch(),
                         run_task=lambda *a, **k: None, spawn=lambda fn: fn())


def test_gateway_dispatches_plugin_command():
    ep = _ep()
    ep._plugin_commands = {"greet": {"handler": lambda args: f"olá {args}", "help": ""}}
    ep.handle("7", "/greet mundo")
    assert any("olá mundo" in t for t in ep.channel.sent)


def test_gateway_plugin_command_handler_error_is_contained():
    ep = _ep()
    def boom(args): raise RuntimeError("x")
    ep._plugin_commands = {"boom": {"handler": boom, "help": ""}}
    ep.handle("7", "/boom")                              # não pode propagar/derrubar
    assert any("/boom" in t for t in ep.channel.sent)
