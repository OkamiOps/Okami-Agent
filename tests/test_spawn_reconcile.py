"""Item 8 da revisão: paridade de durabilidade com o BackgroundRegistry — reconcile no boot. O spawn em
background roda numa thread daemon (morre com o processo); se o gateway reinicia, um job 'running' fica
órfão pra sempre. reconcile_spawn_jobs (chamado no boot, ANTES de qualquer spawn novo) marca os 'running'
remanescentes como 'interrupted' (são todos de um processo morto). Estados terminais não são tocados."""
from __future__ import annotations

import json


def test_reconcile_marks_running_as_interrupted(tmp_path):
    import okami.core.spawn_jobs as sj
    d = sj.spawn_dir(tmp_path)
    (d / "aa000001.json").write_text(
        json.dumps({"job": "aa000001", "goal": "g", "state": "running", "step": 2, "tool": "x"}), encoding="utf-8")
    (d / "bb000002.json").write_text(
        json.dumps({"job": "bb000002", "goal": "g", "state": "done", "result": "r"}), encoding="utf-8")
    n = sj.reconcile_spawn_jobs(tmp_path)
    assert n == 1
    assert sj.read_job(tmp_path, "aa000001")["state"] == "interrupted"   # órfão → interrompido
    assert sj.read_job(tmp_path, "bb000002")["state"] == "done"          # terminal não mexe


def test_reconcile_empty_dir(tmp_path):
    import okami.core.spawn_jobs as sj
    assert sj.reconcile_spawn_jobs(tmp_path) == 0


def test_interrupted_job_readable_by_tool(tmp_path):
    import okami.core.spawn_jobs as sj
    from okami.core.tools.agentic import SpawnJobs
    from okami.core.tools.base import ToolContext
    (sj.spawn_dir(tmp_path) / "cc000003.json").write_text(
        json.dumps({"job": "cc000003", "goal": "tarefa", "state": "interrupted"}), encoding="utf-8")
    res = SpawnJobs().run({"action": "result", "job": "cc000003"}, ToolContext(workspace=tmp_path))
    assert res.ok and "interrupt" in res.output.lower()                 # estado claro, não trava
