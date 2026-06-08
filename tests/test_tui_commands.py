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


def test_event_line_escapes_markup_in_content():
    # REGRESSÃO: cmd/razão com colchetes tipo markup ('[/]', '[x]') NÃO pode quebrar o render
    # (era MarkupError "closing tag '[/]' … has nothing to close" → derrubava o turno inteiro).
    for e in ({"kind": "step", "tool": "run_shell", "ok": True, "args": {"cmd": "grep 'a[/]b' && echo [done]"}},
              {"kind": "step", "tool": "run_shell", "ok": False, "args": {"cmd": "x [/] y"}},
              {"kind": "approval_request", "reason": "rm -rf [/] perigoso"},
              {"kind": "escalate", "why": "loop [/]"},
              {"kind": "complete_rejected", "missing": ["falta [x]"]}):
        line = event_line(e, "collapsed")                    # não levanta MarkupError
        assert line is not None
    # o conteúdo (com colchetes) aparece LITERAL, não é interpretado como tag
    txt = event_line({"kind": "step", "tool": "run_shell", "ok": True,
                      "args": {"cmd": "echo [done]"}}, "expanded").plain
    assert "[done]" in txt


def test_detail_levels_order():
    assert _DETAIL_LEVELS == ("hidden", "collapsed", "expanded")


def test_activity_panel_content():
    p = activity_panel(bg={1: "analisa o repo"}, busy=True, queued=2).plain
    assert "ocupado" in p and "#1 analisa o repo" in p and "2 aguardando" in p
    empty = activity_panel().plain
    assert "background: nenhum" in empty and "livre" in empty


def test_route_skin_and_mouse():
    def r(line):
        return _route_repl_line(line, busy=False, pending_approval=False)
    assert r("/skin nord") == "skin" and r("/skin") == "skin"
    assert r("/mouse off") == "mouse" and r("/mouse") == "mouse"


def test_skins_list_and_theme_defined():
    from okami.tui import SKINS
    assert "okami" in SKINS and "nord" in SKINS
    import okami.tui_app as ta
    if getattr(ta, "_HAS_TEXTUAL", False):
        assert ta.OKAMI_THEME.name == "okami" and ta.OKAMI_THEME.primary == "#ff7527"


def test_skin_changes_theme_via_pilot(tmp_path):
    import okami.tui_app as ta
    if not getattr(ta, "_HAS_TEXTUAL", False):
        return
    import asyncio

    from okami.core import Task, TaskState

    def _runner(cfg, ws, goal, **kw):
        t = Task(goal=goal)
        t.state, t.result = TaskState.COMPLETE, "ok"
        return t

    async def _run():
        app = ta.OkamiChatApp(cfg=None, ws=str(tmp_path), name="dev", cid="t", run_task=_runner)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.theme == "okami"                    # default = marca
            app._cmd_skin("/skin nord")
            assert app.theme == "nord"                     # /skin troca de verdade
            app._cmd_skin("/skin inexistente")
            assert app.theme == "nord"                     # nome inválido não muda

    asyncio.run(_run())


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
