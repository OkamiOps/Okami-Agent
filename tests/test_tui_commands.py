"""Comandos puro-TUI/cliente: /details (verbosidade) e /agents (atividade) + roteamento."""

from __future__ import annotations

from okami.tui import _DETAIL_LEVELS, _route_repl_line, activity_panel, event_line


def test_event_line_detail_levels():
    step = {"kind": "step", "tool": "run_shell", "ok": True,
            "args": {"cmd": "pytest -q", "extra": "x"}}
    assert event_line(step, "hidden") is None                # hidden: não mostra tool-call
    col = event_line(step, "collapsed").plain
    exp = event_line(step, "expanded").plain
    assert "run_shell" in col and "run_shell" in exp
    assert "cmd=" in exp and "extra=" in exp                 # expanded: k=v de todos os args
    assert "cmd=" not in col                                 # collapsed: só o preview do valor
    # eventos que NÃO são step (loop/compact) aparecem em qualquer nível
    assert event_line({"kind": "loop", "repeats": 3}, "hidden") is not None


def test_detail_levels_order():
    assert _DETAIL_LEVELS == ("hidden", "collapsed", "expanded")


def test_activity_panel_content():
    p = activity_panel(bg={1: "analisa o repo"}, busy=True, queued=2).plain
    assert "ocupado" in p and "#1 analisa o repo" in p and "2 aguardando" in p
    empty = activity_panel().plain
    assert "background: nenhum" in empty and "livre" in empty


def test_route_repl_line_client_commands():
    def r(line, **kw):
        return _route_repl_line(line, busy=kw.get("busy", False),
                                pending_approval=kw.get("pending", False))
    assert r("/details expanded") == "details"
    assert r("/details") == "details"
    assert r("/agents") == "agents" and r("/tasks") == "agents"
    assert r("/help") == "help" and r("/exit") == "exit"
    assert r("oi tudo bem") == "handle"
    # display commands são CLIENTE: interceptados ANTES de virar resposta de aprovação (não poluem o /yes)
    assert r("/details", pending=True) == "details"
    assert r("qualquer coisa", pending=True) == "approval"
