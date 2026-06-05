"""Testes do scheduler (§11): parse de schedule, vencimento (cron/intervalo/once), tick."""

from __future__ import annotations

from datetime import datetime

from okami.automation.scheduler import Scheduler, is_due, parse_schedule


def _ts(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi).timestamp()


def test_parse_schedule_kinds():
    assert parse_schedule("0 9 * * 1")["kind"] == "cron"
    assert parse_schedule("1h")["kind"] == "interval" and parse_schedule("1h")["seconds"] == 3600
    assert parse_schedule("every 30m")["seconds"] == 1800
    assert parse_schedule("2h30m")["seconds"] == 9000
    assert parse_schedule("2026-06-10T09:00")["kind"] == "once"


def test_interval_due_after_elapsed():
    assert is_due("1h", now_ts=1000.0, last_run=None) is True          # nunca rodou → vence
    assert is_due("1h", now_ts=1000.0, last_run=1000.0 - 1800) is False  # só passou 30min
    assert is_due("1h", now_ts=1000.0, last_run=1000.0 - 3600) is True   # passou 1h


def test_cron_matches_minute_and_weekday():
    seg9 = _ts(2026, 6, 1, 9, 0)        # 2026-06-01 é segunda-feira
    assert is_due("0 9 * * 1", seg9, None) is True
    assert is_due("0 9 * * 1", _ts(2026, 6, 1, 10, 0), None) is False     # hora errada
    assert is_due("0 9 * * 2", seg9, None) is False                       # dia da semana errado
    assert is_due("*/15 * * * *", _ts(2026, 6, 1, 12, 30), None) is True  # */15 bate em :30


def test_cron_not_twice_in_same_minute():
    t = _ts(2026, 6, 1, 9, 0)                                            # 09:00:00 (segunda)
    assert is_due("0 9 * * 1", t + 30, last_run=t + 5) is False           # rodou 09:00:05, agora 09:00:30


def test_once_runs_only_after_target_and_once():
    target = _ts(2026, 6, 10, 9, 0)
    assert is_due("2026-06-10T09:00", target - 60, None) is False         # ainda não chegou
    assert is_due("2026-06-10T09:00", target + 60, None) is True          # passou
    assert is_due("2026-06-10T09:00", target + 60, last_run=target) is False  # já rodou


def test_scheduler_add_list_remove(tmp_path):
    s = Scheduler(str(tmp_path), clock=lambda: 1000.0)
    j = s.add("1h", "resumir o dia", agent="cto", target="-100")
    assert j["id"] == "resumir-dia" and j["kind"] == "interval"   # id de TÓPICO curto (sem o filler 'o')
    assert len(s.load()) == 1
    j2 = s.add("1h", "resumir o dia")                # id colide → sufixo
    assert j2["id"] == "resumir-dia-2"
    assert s.remove("resumir-dia") is True and len(s.load()) == 1


def test_tick_runs_due_and_marks(tmp_path):
    s = Scheduler(str(tmp_path), clock=lambda: 5000.0)
    s.add("1h", "backup diario")
    ran = []
    out = s.tick(lambda job: ran.append(job["id"]) or "ok")
    assert ran == ["backup-diario"] and out == [("backup-diario", "ok")]
    assert s.load()[0]["last_run"] == 5000.0          # marcou o run
    assert s.tick(lambda job: "again") == []          # agora não vence de novo (intervalo 1h)


def test_once_disabled_after_run(tmp_path):
    s = Scheduler(str(tmp_path), clock=lambda: _ts(2026, 6, 10, 9, 5))
    s.add("2026-06-10T09:00", "lembrete único")
    s.tick(lambda job: "feito")
    assert s.load()[0]["enabled"] is False            # one-shot desativa


def test_infer_commitment_relative_daily_weekly():
    from okami.automation.scheduler import infer_commitment, parse_schedule

    now = _ts(2026, 6, 1, 12, 0)
    sched, prompt = infer_commitment("me lembra de revisar o PR daqui a 2h", now)
    assert parse_schedule(sched)["kind"] == "once" and "revisar o PR" in prompt
    sched2, _ = infer_commitment("me lembra de enviar o relatório todo dia às 9", now)
    assert sched2 == "0 9 * * *"                       # cron diário
    sched3, _ = infer_commitment("agenda backup toda segunda às 8", now)
    assert sched3 == "0 8 * * 1"                       # cron semanal (segunda)


def test_infer_commitment_no_trigger():
    assert infer_commitment_safe("todo dia eu uso esse app") is None   # sem 'lembr/agend' → não agenda
    assert infer_commitment_safe("oi, tudo bem?") is None


def infer_commitment_safe(text):
    from okami.automation.scheduler import infer_commitment
    return infer_commitment(text, 1000.0)
