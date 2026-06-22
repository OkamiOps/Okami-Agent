"""Item 6 da revisão de harness: progresso "passo N (tool)" DURANTE o subagente em segundo plano
(complementa o item 9, que só avisava no fim). O on_event do subagente vira current_step no registro."""
from __future__ import annotations

import json


def _ctx(tmp_path):
    from okami.core.tools.base import ToolContext
    return ToolContext(workspace=tmp_path)


def test_run_spawn_job_records_progress(tmp_path):
    import okami.core.spawn_jobs as sj

    def spawn_with_events(goal, agent, model, on_event=None):
        on_event({"kind": "step", "n": 1, "tool": "read_file"})
        on_event({"kind": "step", "n": 2, "tool": "search_files"})
        return "pronto"
    sj.run_spawn_job("aa111111", "g", None, None, spawn_with_events, None, tmp_path)
    rec = sj.read_job(tmp_path, "aa111111")
    assert rec["state"] == "done" and rec["step"] == 2 and rec["tool"] == "search_files"


def test_spawn_fn_without_on_event_still_works(tmp_path):
    import okami.core.spawn_jobs as sj
    rec = sj.run_spawn_job("bb222222", "g", None, None, lambda g, a, m: "ok", None, tmp_path)
    assert rec["ok"]                                         # fake sem on_event → roda igual (sem progresso)


def test_spawn_jobs_status_shows_step_when_running(tmp_path):
    import okami.core.spawn_jobs as sj
    from okami.core.tools.agentic import SpawnJobs
    (sj.spawn_dir(tmp_path) / "cc333333.json").write_text(
        json.dumps({"job": "cc333333", "goal": "g", "state": "running", "step": 3, "tool": "run_shell"}),
        encoding="utf-8")
    res = SpawnJobs().run({"action": "status", "job": "cc333333"}, _ctx(tmp_path))
    assert "passo 3" in res.output and "run_shell" in res.output


def test_spawn_jobs_list_shows_step(tmp_path):
    import okami.core.spawn_jobs as sj
    from okami.core.tools.agentic import SpawnJobs
    (sj.spawn_dir(tmp_path) / "dd444444.json").write_text(
        json.dumps({"job": "dd444444", "goal": "tarefa X", "state": "running", "step": 5, "tool": "edit_file"}),
        encoding="utf-8")
    res = SpawnJobs().run({"action": "list"}, _ctx(tmp_path))
    assert "passo 5" in res.output
