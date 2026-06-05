"""Manutenção/disco (P2): limpa lock órfão, conserta perms do .env, poda temp/áudio, trace_id."""

from __future__ import annotations

import os
import stat
import time

from okami.core.maintenance import (
    clean_stale_locks, clean_workspace, disk_report, fix_env_perms, fmt_bytes,
    prune_audio, prune_temp, prune_tool_outputs, resolve_retention, run_clean,
)


def _age(path, days):
    t = time.time() - days * 86400
    os.utime(path, (t, t))


def test_clean_stale_locks_keeps_fresh(tmp_path):
    fresh = tmp_path / "a.lock"
    fresh.write_text("", encoding="utf-8")
    old = tmp_path / "b.lock"
    old.write_text("", encoding="utf-8")
    old_t = time.time() - 1000
    os.utime(old, (old_t, old_t))
    removed = clean_stale_locks(tmp_path, stale=300)
    assert str(old) in removed and not old.exists() and fresh.exists()


def test_fix_env_perms(tmp_path):
    p = tmp_path / ".env"
    p.write_text("K=v", encoding="utf-8")
    os.chmod(p, 0o644)
    assert fix_env_perms(p) is True and stat.S_IMODE(p.stat().st_mode) == 0o600
    assert fix_env_perms(p) is False                    # já está 0600 → nada a fazer
    assert fix_env_perms(tmp_path / "none") is False    # inexistente


def test_prune_temp_and_audio(tmp_path):
    (tmp_path / "x.tmp").write_text("aaaa", encoding="utf-8")
    voice = tmp_path / ".okami" / "voice"
    voice.mkdir(parents=True)
    (voice / "in.wav").write_text("bb", encoding="utf-8")
    (tmp_path / "okami_say.mp3").write_text("cc", encoding="utf-8")
    rm_t, freed_t = prune_temp(tmp_path)
    rm_a, freed_a = prune_audio(tmp_path)
    assert any("x.tmp" in r for r in rm_t) and freed_t >= 4
    assert len(rm_a) == 2 and freed_a >= 4


def test_clean_workspace_report(tmp_path):
    (tmp_path / "x.tmp").write_text("a", encoding="utf-8")
    rep = clean_workspace(tmp_path)
    assert rep["temp_removed"] == 1 and "bytes_freed" in rep


def test_dry_run_lists_but_does_not_delete(tmp_path):
    # #P1: --dry-run conta o que SERIA removido sem apagar nada (lock + temp).
    old = tmp_path / "b.lock"
    old.write_text("", encoding="utf-8")
    _age(old, 1)                                        # 1 dia → órfão
    (tmp_path / "x.tmp").write_text("aaaa", encoding="utf-8")
    removed = clean_stale_locks(tmp_path, stale=300, dry_run=True)
    rm_t, freed = prune_temp(tmp_path, dry_run=True)
    assert str(old) in removed and old.exists()         # listou MAS não apagou
    assert any("x.tmp" in r for r in rm_t) and (tmp_path / "x.tmp").exists() and freed >= 4


def test_prune_tool_outputs_quota(tmp_path):
    d = tmp_path / ".okami" / "tool_outputs"
    d.mkdir(parents=True)
    for i in range(6):
        f = d / f"step_{i}.txt"
        f.write_text("x" * 100, encoding="utf-8")
        _age(f, i * 5)                                   # step_0=hoje … step_5=25 dias
    removed, freed = prune_tool_outputs(tmp_path, days=7, keep=2)
    assert len(removed) >= 1 and freed > 0 and (d / "step_0.txt").exists()   # mantém os 2 novos


def test_resolve_retention_merges_over_defaults():
    r = resolve_retention({"sessions": {"days": 5}, "tool_outputs": {"keep": 9}})
    assert r["sessions"]["days"] == 5 and r["sessions"]["keep"] == 10   # merge (mantém keep default)
    assert r["tool_outputs"]["keep"] == 9
    assert r["checkpoints"]["days"] == 14.0                             # área intocada = default


def test_disk_report_areas_and_quota(tmp_path):
    d = tmp_path / ".okami" / "tool_outputs"
    d.mkdir(parents=True)
    (d / "step_1.txt").write_text("x" * 50_000, encoding="utf-8")
    rep = disk_report(tmp_path, retention={"quota_mb": {"tool_outputs": 0.01}})  # 10KB → estoura
    assert "tool_outputs" in rep["areas"] and rep["bytes_total"] >= 50_000
    assert rep["areas"]["tool_outputs"]["over_quota"] and "tool_outputs" in rep["over_quota"]
    assert rep["areas"]["tool_outputs"]["files"] == 1


def test_run_clean_deep_structured_report(tmp_path):
    d = tmp_path / ".okami" / "tool_outputs"
    d.mkdir(parents=True)
    for i in range(5):
        f = d / f"step_{i}.txt"
        f.write_text("y" * 1000, encoding="utf-8")
        _age(f, 0 if i == 0 else 30)                     # step_0 recente (mais novo); resto bem velho
    rep = run_clean(tmp_path, deep=True, retention={"tool_outputs": {"days": 7, "keep": 1}})
    assert rep["deep"] and not rep["dry_run"]
    assert rep["areas"]["tool_outputs"]["removed"] == 4  # mantém o 1 mais novo, poda os 4 velhos
    assert rep["items_removed"] >= 4 and rep["bytes_freed"] > 0
    assert (d / "step_0.txt").exists()                   # o mais novo fica


def test_fmt_bytes():
    assert fmt_bytes(0) == "0 B" and fmt_bytes(512) == "512 B"
    assert fmt_bytes(1536).endswith("KB") and fmt_bytes(5 * 1024 * 1024).endswith("MB")


def test_event_trace_id_ties_a_turn(tmp_path):
    from okami.observability.events import EventLog, read_events
    log = EventLog(tmp_path, trace_id="abc123")
    log.emit("start", goal="x")
    log.emit("complete", summary="ok")
    evs = read_events(tmp_path)
    assert all(e["trace"] == "abc123" for e in evs)     # todos os eventos do turno têm o mesmo trace
