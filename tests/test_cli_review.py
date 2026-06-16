"""Revisão TUI/terminal/CLI: bugs achados pela auditoria (3 subagentes) + comandos faltantes."""
from __future__ import annotations

import tempfile

from okami.channels.base import Channel
from okami.gateway import AgentEndpoint


class FakeChannel(Channel):
    name = "fake"

    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def poll(self):
        return []

    def send(self, chat_id, text):
        self.sent.append((str(chat_id), text))

    def allowed(self, chat_id):
        return True


def _ep():
    called = {"run": 0}

    def _runner(*a, **k):
        called["run"] += 1
        return None

    ch = FakeChannel()
    ep = AgentEndpoint("dev", cfg=None, ws=tempfile.mkdtemp(), channel=ch,
                       run_task=_runner, approval_mode="manual", spawn=lambda fn: fn())
    return ep, ch, called


# ── BUG: comando chat-only digitado num canal remoto (Telegram/REST) caía como MENSAGEM pro agente ──
def test_gateway_chat_only_command_gives_terminal_hint_not_llm():
    ep, ch, called = _ep()
    ep.handle("42", "/skin dracula")                      # /skin é scope="chat"
    assert called["run"] == 0                             # NÃO virou turno do agente
    assert ch.sent and ("terminal" in ch.sent[-1][1].lower() or "tui" in ch.sent[-1][1].lower())


def test_gateway_chat_only_mouse_also_hinted():
    ep, ch, called = _ep()
    ep.handle("42", "/mouse off")                         # outro chat-only
    assert called["run"] == 0
    assert ch.sent and ("terminal" in ch.sent[-1][1].lower() or "tui" in ch.sent[-1][1].lower())


def test_gateway_both_scope_command_still_works():
    # comando scope="both" (ex.: /status) NÃO deve cair no hint de terminal-only
    ep, ch, _ = _ep()
    ep.handle("42", "/status")
    assert ch.sent and "terminal" not in ch.sent[-1][1].lower()


# ── TUI: 3 bugs (replay sumia, _cmdmenu None no submit, _tokbuf vazava entre turnos) ──
def _fake_runner(cfg, ws, goal, **kw):
    from okami.core import Task, TaskState
    t = Task(goal=goal)
    t.state, t.result = TaskState.COMPLETE, f"eco: {goal}"
    return t


def test_tui_replay_renders_and_cmdmenu_guard_and_tokbuf_reset(tmp_path):
    import asyncio

    from textual.widgets import Input, RichLog

    from okami.tui_app import OkamiChatApp
    out = {}

    async def scenario():
        app = OkamiChatApp(cfg=None, ws=str(tmp_path), name="okami", cid="terminal",
                           run_task=_fake_runner, spawn=lambda fn: fn())
        async with app.run_test() as pilot:
            await pilot.pause()
            log = app.query_one("#log", RichLog)

            # (1) /replay: agora TEM handler na TUI e ESCREVE a view (antes caía como mensagem pro agente)
            app.ep._step_log = [{"tool": "read_file", "args": {"path": "x"}, "output": "ok"}]
            writes = []
            _orig = log.write
            log.write = lambda r, *a, **k: (writes.append(r), _orig(r, *a, **k))[1]
            app._cmd_replay("/replay 5")
            out["replay_wrote"] = bool(writes)
            log.write = _orig

            # (2) on_input_submitted NÃO crasha se o menu não existe (teardown) — guard do _cmdmenu()
            app._cmdmenu = lambda: None
            ev = type("E", (), {"value": "/skin x", "input": app.query_one("#input", Input)})()
            try:
                app.on_input_submitted(ev)
                out["submit_ok"] = True
            except AttributeError:
                out["submit_ok"] = False

            # (3) _tokbuf NÃO vaza entre turnos: token parcial (sem \n) é zerado quando a resposta chega
            app.sink_event({"kind": "token", "text": "parcial sem newline"})
            out["buf_mid"] = app._tokbuf
            app.sink_message("terminal", "✅ pronto")
            out["buf_after"] = app._tokbuf

    asyncio.run(scenario())
    assert out["replay_wrote"] is True
    assert out["submit_ok"] is True
    assert out["buf_mid"] == "parcial sem newline"
    assert out["buf_after"] == ""


# ── COMANDO FALTANTE: `okami sessions` (CLI) — paridade com o /sessions do chat, scriptável ──
def test_session_summaries_lists_chats(tmp_path):
    from okami.gateway.sessions import TranscriptStore, session_summaries
    st = TranscriptStore(str(tmp_path))
    st.append("c1", "USER", "oi")
    st.append("c1", "AGENTE", "olá de volta")
    st.append("c2", "USER", "outra conversa")
    rows = session_summaries(st)
    by = {r["chat_id"]: r for r in rows}
    assert by["c1"]["turns"] == 2 and by["c2"]["turns"] == 1
    assert by["c1"]["last_role"] == "AGENTE"
    assert "olá de volta" in by["c1"]["last_text"]
    assert set(by) == {"c1", "c2"}


def test_session_summaries_empty_store(tmp_path):
    from okami.gateway.sessions import TranscriptStore, session_summaries
    assert session_summaries(TranscriptStore(str(tmp_path))) == []
