"""Quotas de disco (P2): poda sessões arquivadas e checkpoints por idade+contagem, preserva o journal."""

from __future__ import annotations

import os
import time

from okami.core.maintenance import prune_by_age_and_count, prune_checkpoints, prune_sessions


def _age(path, days):
    t = time.time() - days * 86400
    os.utime(path, (t, t))


def test_prune_by_age_and_count_keeps_recent(tmp_path):
    for i in range(10):
        f = tmp_path / f"f{i}.txt"
        f.write_text("x" * 10, encoding="utf-8")
        _age(f, i * 10)                              # f0=hoje … f9=90 dias
    removed, freed = prune_by_age_and_count(tmp_path, days=30, keep=3)
    # mantém os 3 mais NOVOS (f0/f1/f2) sempre; remove os além disso que forem >30 dias (f4..f9)
    assert (tmp_path / "f0.txt").exists() and (tmp_path / "f2.txt").exists()
    assert any("f9.txt" in r for r in removed) and freed > 0
    assert len(removed) >= 6                          # f4..f9 (>30d, além do keep) podados


def test_prune_sessions_only_archived(tmp_path):
    sdir = tmp_path / ".okami" / "sessions"
    sdir.mkdir(parents=True)
    live = sdir / "c.jsonl"
    live.write_text("live", encoding="utf-8")        # transcript ATIVO (não é *.reset.jsonl)
    arch = sdir / "c.123.reset.jsonl"
    arch.write_text("old", encoding="utf-8")
    _age(arch, 90)
    removed, _ = prune_sessions(tmp_path, days=30, keep=0)
    assert any("reset.jsonl" in r for r in removed) and live.exists()   # ativo intacto


def test_prune_checkpoints_preserves_journal(tmp_path):
    cdir = tmp_path / ".okami" / "checkpoints"
    cdir.mkdir(parents=True)
    journal = cdir / "journal.jsonl"
    journal.write_text("j", encoding="utf-8")
    _age(journal, 90)                                # velho, MAS é o journal → não pode sumir
    snap = cdir / "snap1.bak"
    snap.write_text("x" * 100, encoding="utf-8")
    _age(snap, 90)
    removed, freed = prune_checkpoints(tmp_path, days=14, keep=0)
    assert any("snap1" in r for r in removed) and journal.exists() and freed >= 100


def test_clean_cli_dry_run_json(tmp_path, monkeypatch):
    """`okami clean --deep --dry-run --json` reporta por área e NÃO apaga (gateway long-running)."""
    import json

    from typer.testing import CliRunner

    from okami.cli import app
    monkeypatch.chdir(tmp_path)
    (tmp_path / "okami.yaml").write_text(
        "default_provider: lmstudio\nproviders:\n  lmstudio: {model: openai/x, api_key: lm, tier: local}\n"
        "retention:\n  tool_outputs: {days: 0, keep: 1}\n", encoding="utf-8")
    d = tmp_path / ".okami" / "tool_outputs"
    d.mkdir(parents=True)
    for i in range(5):
        f = d / f"step_{i}.txt"
        f.write_text("z" * 2000, encoding="utf-8")
        _age(f, 10)
    res = CliRunner().invoke(app, ["clean", "--deep", "--dry-run", "--json"])
    assert res.exit_code == 0, res.output
    rep = json.loads(res.output)
    assert rep["dry_run"] and rep["deep"]
    assert rep["areas"]["tool_outputs"]["removed"] == 4   # keep=1 → poda 4
    assert len(list(d.glob("*.txt"))) == 5                # dry-run NÃO apagou
