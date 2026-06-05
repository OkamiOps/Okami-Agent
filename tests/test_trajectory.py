"""Replay/trajetória por turno (#12): reconstrução a partir do event log + comando okami replay."""

from __future__ import annotations

from okami.observability.events import EventLog
from okami.observability.trajectory import build_trajectory, list_traces, render_line


def _emit_turn(ws, trace, goal, *, steps=2, outcome="complete"):
    log = EventLog(ws, trace_id=trace)
    log.emit("start", goal=goal)
    log.emit("llm_call", provider="codex", model="gpt", tokens_in=100, tokens_out=20, finish_reason="stop")
    for i in range(steps):
        log.emit("step", n=i + 1, tool="write_file", ok=True)
    log.emit(outcome, summary="feito" if outcome == "complete" else "", reason="travou")


def test_list_traces_groups_and_summarizes(tmp_path):
    _emit_turn(tmp_path, "aaa", "objetivo A", steps=2)
    _emit_turn(tmp_path, "bbb", "objetivo B", steps=3, outcome="blocked")
    traces = list_traces(tmp_path)
    assert {t["trace"] for t in traces} == {"aaa", "bbb"}
    a = next(t for t in traces if t["trace"] == "aaa")
    assert a["steps"] == 2 and a["llm_calls"] == 1 and a["tokens_in"] == 100 and "completou" in a["outcome"]
    b = next(t for t in traces if t["trace"] == "bbb")
    assert b["steps"] == 3 and "bloqueou" in b["outcome"]


def test_build_trajectory_ordered(tmp_path):
    _emit_turn(tmp_path, "xyz", "obj", steps=2)
    traj = build_trajectory(tmp_path, "xyz")
    types = [e["type"] for e in traj["events"]]
    assert types == ["start", "llm_call", "step", "step", "complete"]   # ordem por seq
    assert traj["summary"]["goal"] == "obj"


def test_build_trajectory_missing(tmp_path):
    _emit_turn(tmp_path, "xyz", "obj")
    assert build_trajectory(tmp_path, "naoexiste")["events"] == []


def test_render_line():
    assert "start" in render_line({"type": "start", "goal": "fazer X"})
    assert "✓" in render_line({"type": "step", "n": 1, "tool": "write_file", "ok": True})
    assert "✗" in render_line({"type": "step", "n": 2, "tool": "run_shell", "ok": False})
    assert "llm" in render_line({"type": "llm_call", "provider": "codex", "model": "g",
                                 "tokens_in": 1, "tokens_out": 2})


def test_replay_cli_list_and_detail(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from okami.cli import app
    _emit_turn(tmp_path, "trace123", "objetivo do turno", steps=2)
    runner = CliRunner()
    # lista
    res = runner.invoke(app, ["replay", "-w", str(tmp_path)])
    assert res.exit_code == 0 and "trace123" in res.output
    # detalhe
    res2 = runner.invoke(app, ["replay", "trace123", "-w", str(tmp_path)])
    assert res2.exit_code == 0 and "objetivo do turno" in res2.output and "trajetória" in res2.output
    # json
    res3 = runner.invoke(app, ["replay", "trace123", "-w", str(tmp_path), "--json"])
    assert res3.exit_code == 0 and '"trace": "trace123"' in res3.output


def test_replay_cli_unknown_trace(tmp_path):
    from typer.testing import CliRunner

    from okami.cli import app
    _emit_turn(tmp_path, "real", "x")
    res = CliRunner().invoke(app, ["replay", "ghost", "-w", str(tmp_path)])
    assert res.exit_code == 1 and "não encontrado" in res.output
