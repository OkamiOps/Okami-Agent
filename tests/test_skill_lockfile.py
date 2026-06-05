"""Lockfile/proveniência de skills (P1.5): hash determinístico, record/verify, gate do clawhub."""

from __future__ import annotations

from typer.testing import CliRunner

from okami.cli import app
from okami.skills.lockfile import load_lock, record, skill_hash, verify

runner = CliRunner()


def test_hash_is_deterministic_and_content_sensitive(tmp_path):
    d = tmp_path / "sk"
    d.mkdir()
    (d / "SKILL.md").write_text("procedimento A", encoding="utf-8")
    h1 = skill_hash(d)
    assert h1 == skill_hash(d)                       # determinístico
    (d / "SKILL.md").write_text("procedimento B", encoding="utf-8")
    assert skill_hash(d) != h1                       # muda com o conteúdo


def test_record_and_verify_detects_tampering(tmp_path):
    root = tmp_path
    d = tmp_path / "skills" / "sk"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("x", encoding="utf-8")
    record(root, "sk", source="owner/repo", skill_dir=d, version="1.0")
    lock = load_lock(root)
    assert lock["skills"]["sk"]["source"] == "owner/repo" and lock["skills"]["sk"]["sha256"]
    assert verify(root, "sk", d) is True
    (d / "SKILL.md").write_text("ADULTERADO", encoding="utf-8")
    assert verify(root, "sk", d) is False            # adulteração detectada pelo hash


def test_clawhub_blocked_without_allow_exec(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    res = runner.invoke(app, ["learn", "clawhub:foo"])
    assert res.exit_code == 2 and ("npx" in res.output.lower() or "exec" in res.output.lower())
