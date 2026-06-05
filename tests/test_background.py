"""Registro PERSISTIDO de /background (durável: sobrevive a restart, reconcilia órfão, poda TTL)."""

from __future__ import annotations

from okami.gateway.background import BackgroundRegistry


def test_add_finish_and_reconcile(tmp_path):
    reg = BackgroundRegistry(tmp_path)
    jid = reg.add("analisa o repo", now=1000.0)
    assert jid == 1 and reg.running()[0]["prompt"] == "analisa o repo"
    reg.finish(jid, state="done", result="ok", now=1001.0)
    j = reg.list()[0]
    assert j["state"] == "done" and j["finished_at"] == 1001.0 and j["result"] == "ok"
    reg.add("job2", now=1002.0)                                   # fica 'running'
    assert reg.reconcile(now=2000.0) == 1                         # crash simulado → interrupted
    assert reg.list()[0]["state"] == "interrupted" and not reg.running()


def test_persists_across_instances(tmp_path):
    BackgroundRegistry(tmp_path).add("durável", now=1.0)
    assert BackgroundRegistry(tmp_path).list()[0]["prompt"] == "durável"   # outro processo lê o mesmo arquivo


def test_prune_old_keeps_recent_and_running(tmp_path):
    reg = BackgroundRegistry(tmp_path)
    a = reg.add("antigo", now=0.0)
    reg.finish(a, state="done", now=0.0)
    b = reg.add("novo", now=1_000_000_000.0)
    reg.finish(b, state="done", now=1_000_000_000.0)
    reg.add("rodando", now=1_000_000_000.0)                       # running NÃO é podado
    removed = reg.prune(max_age_days=7.0, now=1_000_000_010.0)
    texts = {j["prompt"] for j in reg.list()}
    assert removed == 1 and "antigo" not in texts and {"novo", "rodando"} <= texts
