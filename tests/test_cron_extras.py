"""Cron — lacunas fechadas (pesquisa #6 item 30): next_run_at pré-calculado, histórico de output
persistido, e jobs SCRIPT (rodam um comando e entregam o stdout, sem gastar LLM)."""
from __future__ import annotations

from okami.automation.scheduler import Scheduler, next_run_at, run_script


# ------------------------------------------------------------------ next_run_at
def test_next_run_interval_never_ran():
    assert next_run_at("30m", now=1000.0, last_run=None) == 1000.0   # nunca rodou → agora


def test_next_run_interval_after_last():
    assert next_run_at("1h", now=5000.0, last_run=1000.0) == 1000.0 + 3600


def test_next_run_cron_finds_future_minute():
    # cron "0 9 * * *" (todo dia 9h); de uma base conhecida, o próximo é > now
    import datetime as _dt
    base = _dt.datetime(2026, 6, 12, 10, 0).timestamp()   # 10h → próximo 9h é amanhã
    nxt = next_run_at("0 9 * * *", now=base, last_run=None)
    assert nxt is not None and nxt > base
    assert _dt.datetime.fromtimestamp(nxt).hour == 9


def test_next_run_once_returns_target():
    nxt = next_run_at("2030-01-01T09:00", now=1000.0, last_run=None)
    assert nxt is not None and nxt > 1000.0


def test_next_run_once_already_ran():
    assert next_run_at("2030-01-01T09:00", now=1000.0, last_run=999.0) is None


# ------------------------------------------------------------------ output history
def test_record_and_read_output(tmp_path):
    sch = Scheduler(str(tmp_path))
    sch.record_output("job1", "achei 3 PRs novos", now_ts=1000.0)
    sch.record_output("job1", "nada novo", now_ts=2000.0)
    hist = sch.output_history("job1")
    assert len(hist) == 2
    assert hist[0]["text"] == "nada novo"             # mais novo primeiro
    assert "3 PRs" in hist[1]["text"]


def test_output_history_rotates(tmp_path):
    sch = Scheduler(str(tmp_path))
    for i in range(30):
        sch.record_output("j", f"saída {i}", now_ts=1000.0 + i)
    assert len(sch.output_history("j", limit=100)) <= 20   # mantém os recentes (anti-incha)


def test_output_history_empty(tmp_path):
    assert Scheduler(str(tmp_path)).output_history("nada") == []


# ------------------------------------------------------------------ script jobs
def test_add_script_job(tmp_path):
    sch = Scheduler(str(tmp_path))
    job = sch.add("1h", "backup diário", script="echo feito")
    assert job.get("script") == "echo feito"
    assert sch.load()[0]["script"] == "echo feito"


def test_run_script_returns_stdout(tmp_path):
    out = run_script("echo ola mundo", cwd=str(tmp_path))
    assert "ola mundo" in out


def test_run_script_reports_failure(tmp_path):
    out = run_script("exit 3", cwd=str(tmp_path))
    assert "3" in out or "exit" in out.lower() or "falh" in out.lower()
