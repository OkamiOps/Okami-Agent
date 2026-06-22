"""Camada de leitura/gestão de subagentes em segundo plano (revisão vs Hermes): o agente PAI lê o
resultado de volta (spawn_jobs tool), estado 'running' explícito, cap de concorrência, GC e await."""
from __future__ import annotations

import json
import time


def _ctx(tmp_path, spawn=None, notify=None):
    from okami.core.tools.base import ToolContext
    return ToolContext(workspace=tmp_path, spawn=spawn, notify=notify)


# ── estado 'running' → terminal ──
def test_record_has_running_then_done(tmp_path, monkeypatch):
    import okami.core.spawn_jobs as sj
    seen_states = []

    def slow(goal, a, m):
        # no meio da execução, o registro deve estar 'running'
        rec = sj.read_job(tmp_path, "aaaaaaaa")
        seen_states.append(rec and rec.get("state"))
        return "feito"
    sj.run_spawn_job("aaaaaaaa", "g", None, None, slow, None, tmp_path)
    assert seen_states == ["running"]                         # estava running durante
    final = sj.read_job(tmp_path, "aaaaaaaa")
    assert final["state"] == "done" and final["ok"] is True
    assert "started_at" in final and "finished_at" in final


def test_failed_state(tmp_path):
    import okami.core.spawn_jobs as sj

    def boom(g, a, m):
        raise RuntimeError("x")
    sj.run_spawn_job("bbbbbbbb", "g", None, None, boom, None, tmp_path)
    assert sj.read_job(tmp_path, "bbbbbbbb")["state"] == "failed"


# ── leitura jailed + validação de id ──
def test_read_job_rejects_bad_id(tmp_path):
    import okami.core.spawn_jobs as sj
    assert sj.read_job(tmp_path, "../etc/passwd") is None     # traversal barrado
    assert sj.read_job(tmp_path, "naohex!!") is None          # não-hex barrado
    assert sj.read_job(tmp_path, "deadbeef") is None          # inexistente → None


def test_list_jobs(tmp_path):
    import okami.core.spawn_jobs as sj
    sj.run_spawn_job("11111111", "tarefa A", None, None, lambda g, a, m: "ra", None, tmp_path)
    sj.run_spawn_job("22222222", "tarefa B", None, None, lambda g, a, m: "rb", None, tmp_path)
    jobs = sj.list_jobs(tmp_path)
    ids = {j["job"] for j in jobs}
    assert "11111111" in ids and "22222222" in ids
    assert all("state" in j and "goal" in j for j in jobs)


# ── GC ──
def test_prune_keeps_recent_and_drops_old(tmp_path):
    import okami.core.spawn_jobs as sj
    d = sj.spawn_dir(tmp_path)
    old = d / "old00000.json"
    old.write_text(json.dumps({"job": "old00000", "state": "done"}), encoding="utf-8")
    import os
    old_time = time.time() - 40 * 86400                       # 40 dias atrás
    os.utime(old, (old_time, old_time))
    sj.run_spawn_job("33333333", "novo", None, None, lambda g, a, m: "r", None, tmp_path)
    sj.prune_spawn_jobs(tmp_path, keep=50, max_age_days=7)
    assert not old.exists() and sj.read_job(tmp_path, "33333333") is not None


# ── await ──
def test_await_returns_when_done(tmp_path):
    import okami.core.spawn_jobs as sj
    sj.run_spawn_job("44444444", "g", None, None, lambda g, a, m: "pronto", None, tmp_path)
    rec = sj.await_job(tmp_path, "44444444", timeout=2)
    assert rec and rec["state"] == "done" and "pronto" in rec["result"]


def test_await_times_out_on_running(tmp_path):
    import okami.core.spawn_jobs as sj
    sj.spawn_dir(tmp_path)
    (sj.spawn_dir(tmp_path) / "55555555.json").write_text(
        json.dumps({"job": "55555555", "goal": "g", "state": "running"}), encoding="utf-8")
    rec = sj.await_job(tmp_path, "55555555", timeout=1)
    assert rec is None or rec.get("state") == "running"       # não terminou no prazo


# ── tool spawn_jobs (o agente PAI usa o resultado) ──
def test_spawn_jobs_tool_result_and_list(tmp_path):
    import okami.core.spawn_jobs as sj
    from okami.core.tools.agentic import SpawnJobs
    sj.run_spawn_job("66666666", "analisar repo", None, None, lambda g, a, m: "ACHEI 3 BUGS", None, tmp_path)
    tool = SpawnJobs()
    res = tool.run({"action": "result", "job": "66666666"}, _ctx(tmp_path))
    assert res.ok and "ACHEI 3 BUGS" in res.output and "analisar repo" in res.output  # header autocontido
    lst = tool.run({"action": "list"}, _ctx(tmp_path))
    assert lst.ok and "66666666" in lst.output


def test_spawn_jobs_tool_status_running(tmp_path):
    import okami.core.spawn_jobs as sj
    from okami.core.tools.agentic import SpawnJobs
    (sj.spawn_dir(tmp_path) / "77777777.json").write_text(
        json.dumps({"job": "77777777", "goal": "g", "state": "running"}), encoding="utf-8")
    res = SpawnJobs().run({"action": "status", "job": "77777777"}, _ctx(tmp_path))
    assert res.ok and "running" in res.output.lower()


def test_spawn_jobs_tool_unknown_job(tmp_path):
    from okami.core.tools.agentic import SpawnJobs
    res = SpawnJobs().run({"action": "result", "job": "deadbeef"}, _ctx(tmp_path))
    assert res.ok is False and "não encontrado" in res.output


def test_spawn_jobs_registered():
    from okami.core.tools.registry import default_registry
    assert "spawn_jobs" in default_registry()


# ── cap de concorrência → fallback síncrono inline ──
def test_background_full_falls_back_to_sync(tmp_path, monkeypatch):
    import okami.core.spawn_jobs as sj
    from okami.core.tools.agentic import Spawn
    monkeypatch.setattr(sj, "acquire_slot", lambda: False)    # fila de background cheia
    res = Spawn().run({"goal": "x", "background": True},
                      _ctx(tmp_path, spawn=lambda g, a, m: "RODOU INLINE"))
    assert res.ok and "INLINE" in res.output.upper()          # caiu pro síncrono, não perdeu
