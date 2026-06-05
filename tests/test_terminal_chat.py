"""Chat de terminal (§13): TerminalChannel + AgentEndpoint reusam toda a lógica do gateway."""

from __future__ import annotations

import tempfile

from okami.channels.terminal import TerminalChannel
from okami.core import Task, TaskState
from okami.gateway import AgentEndpoint


def _runner(cfg, ws, goal, *, approve=None, extra_context="", cancel=None, **kw):
    t = Task(goal=goal)
    t.state, t.result = TaskState.COMPLETE, f"eco: {goal}"
    return t


def _ep(ws):
    ch = TerminalChannel("okami")           # console=None → cai no print (sem rich)
    return ch, AgentEndpoint("okami", None, ws, ch, run_task=_runner, spawn=lambda fn: fn())


def test_terminal_send_records_and_renders_prefix():
    ch = TerminalChannel("okami")
    ch.send("terminal", "✅ feito")
    assert ch.sent == [("terminal", "✅ feito")]
    assert ch._render("✅ ok") == "[green]✅ ok[/green]"
    assert ch._render("texto normal") == "texto normal"     # sem prefixo → sem cor


def test_terminal_reply_gets_turn_rule_but_system_note_does_not():
    import io

    from rich.console import Console
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True, width=80, legacy_windows=False)
    ch = TerminalChannel("okami", console=console)
    ch.send("t", "✅ pronto, gato")             # resposta do agente → régua de turno 🐺
    out = buf.getvalue()
    assert "🐺" in out and "okami" in out and "─" in out
    buf.truncate(0)
    buf.seek(0)
    ch.send("t", "🧠 okami está pensando…")     # nota de sistema → SEM régua (não polui)
    assert "🐺" not in buf.getvalue()


def test_terminal_chat_roundtrip_persists_session():
    ws = tempfile.mkdtemp()
    ch, ep = _ep(ws)
    ep.handle("terminal", "oi")
    replies = [t for _, t in ch.sent]
    assert any("eco: oi" in t for t in replies)       # papo: resposta limpa, sem selo ✅ robótico
    # reabrir (novo endpoint, mesmo ws) → o transcript append-only retoma a conversa
    _, ep2 = _ep(ws)
    hist = ep2.session("terminal").history
    assert hist[-2] == ("USER", "oi") and hist[-1] == ("AGENTE", "eco: oi")


def test_terminal_slash_commands_work():
    ws = tempfile.mkdtemp()
    ch, ep = _ep(ws)
    ep.handle("terminal", "/help")
    assert any("Essenciais" in t and "/commands" in t for _, t in ch.sent)   # _help vem do registro
    ep.handle("terminal", "/status")
    assert any("livre" in t for _, t in ch.sent)


def test_terminal_not_allowed_blocks():
    ch = TerminalChannel("okami", allow_chats=["7"])
    assert ch.allowed("7") and not ch.allowed("999")
