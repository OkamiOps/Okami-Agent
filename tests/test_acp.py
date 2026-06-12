"""ACP profundo (pesquisa #6 item 28): streaming de progresso (tool-calls ao vivo), session/cancel,
capabilities corretas. Handler testável (req → result + notificações capturadas)."""
from __future__ import annotations

from okami.integrations.acp import AcpServer


class _Task:
    def __init__(self, result="ok", state="COMPLETE"):
        self.result, self.reason = result, None
        self.state = type("S", (), {"value": state, "name": state})()


def _server(run_task):
    return AcpServer(cfg=None, ws=".", run_task=run_task)


def _emitter():
    msgs = []
    return msgs, (lambda method, params: msgs.append((method, params)))


def test_initialize_advertises_capabilities():
    srv = _server(lambda *a, **k: _Task())
    r = srv.handle({"id": 1, "method": "initialize", "params": {}}, lambda m, p: None)
    caps = r["result"]["agentCapabilities"]
    assert "promptCapabilities" in caps


def test_session_new():
    srv = _server(lambda *a, **k: _Task())
    r = srv.handle({"id": 1, "method": "session/new", "params": {}}, lambda m, p: None)
    assert r["result"]["sessionId"]


def test_prompt_streams_tool_calls_and_final():
    def run_task(cfg, ws, goal, *, on_event=None, cancel=None, **kw):
        if on_event:
            on_event({"kind": "step", "tool": "read_file", "ok": True})
            on_event({"kind": "step", "tool": "run_shell", "ok": True})
        return _Task(result="pronto")

    srv = _server(run_task)
    srv.handle({"id": 1, "method": "session/new", "params": {}}, lambda m, p: None)
    msgs, emit = _emitter()
    r = srv.handle({"id": 2, "method": "session/prompt",
                    "params": {"sessionId": "sess-1", "prompt": "faça algo"}}, emit)
    updates = [p for m, p in msgs if m == "session/update"]
    kinds = [u["update"]["sessionUpdate"] for u in updates]
    assert "tool_call" in kinds                        # streamou os tool-calls
    assert any("read_file" in str(u) for u in updates)
    assert "agent_message_chunk" in kinds              # e o texto final
    assert r["result"]["stopReason"] == "end_turn"


def test_session_cancel_flags_and_stops():
    seen = {}

    def run_task(cfg, ws, goal, *, on_event=None, cancel=None, **kw):
        seen["cancelled"] = bool(cancel and cancel())   # lê o flag no início
        return _Task(result="parou", state="BLOCKED")

    srv = _server(run_task)
    srv.handle({"id": 1, "method": "session/new", "params": {}}, lambda m, p: None)
    # cancela ANTES do prompt → o run vê o flag
    srv.handle({"id": 2, "method": "session/cancel", "params": {"sessionId": "sess-1"}}, lambda m, p: None)
    r = srv.handle({"id": 3, "method": "session/prompt",
                    "params": {"sessionId": "sess-1", "prompt": "x"}}, lambda m, p: None)
    assert seen["cancelled"] is True
    assert r["result"]["stopReason"] == "cancelled"


def test_prompt_resets_cancel_each_turn():
    calls = {"n": 0}

    def run_task(cfg, ws, goal, *, on_event=None, cancel=None, **kw):
        calls["n"] += 1
        calls[f"cancel{calls['n']}"] = bool(cancel and cancel())
        return _Task()

    srv = _server(run_task)
    srv.handle({"id": 1, "method": "session/new", "params": {}}, lambda m, p: None)
    srv.handle({"id": 2, "method": "session/cancel", "params": {"sessionId": "sess-1"}}, lambda m, p: None)
    srv.handle({"id": 3, "method": "session/prompt", "params": {"sessionId": "sess-1", "prompt": "a"}},
               lambda m, p: None)
    srv.handle({"id": 4, "method": "session/prompt", "params": {"sessionId": "sess-1", "prompt": "b"}},
               lambda m, p: None)
    assert calls["cancel1"] is True and calls["cancel2"] is False   # 2º turno não herda o cancel


def test_unknown_method_tolerant():
    srv = _server(lambda *a, **k: _Task())
    r = srv.handle({"id": 9, "method": "frob", "params": {}}, lambda m, p: None)
    assert r["result"] == {}
