"""Manutenção/disco (P2): limpa lock órfão, conserta perms do .env, poda temp/áudio, trace_id."""

from __future__ import annotations

import os
import stat
import time

from okami.core.maintenance import (
    clean_stale_locks, clean_workspace, fix_env_perms, prune_audio, prune_temp,
)


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


def test_event_trace_id_ties_a_turn(tmp_path):
    from okami.observability.events import EventLog, read_events
    log = EventLog(tmp_path, trace_id="abc123")
    log.emit("start", goal="x")
    log.emit("complete", summary="ok")
    evs = read_events(tmp_path)
    assert all(e["trace"] == "abc123" for e in evs)     # todos os eventos do turno têm o mesmo trace
