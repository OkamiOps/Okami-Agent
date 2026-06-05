"""Segurança de checkpoints (#5): jail de workspace, não captura segredo, rollback valida o journal."""

from __future__ import annotations

import json

from okami.gateway.checkpoints import Checkpoints


def test_snapshot_blocks_absolute_path(tmp_path):
    secret = tmp_path / "fora.txt"
    secret.write_text("SEGREDO", encoding="utf-8")
    cp = Checkpoints(tmp_path / "ws")
    cp.snapshot(str(secret))                          # caminho ABSOLUTO → fora do ws → não captura
    assert cp.entries() == []
    if cp.journal.exists():
        assert "SEGREDO" not in cp.journal.read_text(encoding="utf-8")


def test_snapshot_skips_sensitive_files(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / ".env").write_text("OPENAI_API_KEY=sk-abc", encoding="utf-8")
    cp = Checkpoints(ws)
    cp.snapshot(".env")
    assert cp.entries() == []                         # não captura .env em plaintext


def test_snapshot_and_rollback_normal_file(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    f = ws / "a.txt"
    f.write_text("v1", encoding="utf-8")
    cp = Checkpoints(ws)
    cp.snapshot("a.txt")
    f.write_text("v2", encoding="utf-8")
    assert cp.rollback(1) == ["a.txt"] and f.read_text(encoding="utf-8") == "v1"


def test_rollback_ignores_tampered_absolute_entry(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    cp = Checkpoints(ws)
    cp.dir.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "pwned.txt"
    cp.journal.write_text(
        json.dumps({"path": str(outside), "before": "HACK", "existed": True}) + "\n", encoding="utf-8")
    cp.rollback(1)
    assert not outside.exists()                       # entrada adulterada (absoluta) NÃO escreve fora do ws
