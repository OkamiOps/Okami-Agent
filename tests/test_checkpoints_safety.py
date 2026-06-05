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


def test_tampered_content_is_rejected_by_hmac(tmp_path):
    """#10: adulterar o `before` de uma entrada legítima quebra o HMAC → rollback NÃO restaura o forjado."""
    ws = tmp_path / "ws"
    ws.mkdir()
    f = ws / "a.txt"
    f.write_text("legit", encoding="utf-8")
    cp = Checkpoints(ws)
    cp.snapshot("a.txt")                              # entrada válida (com mac)
    ents = cp.entries()                               # atacante troca o conteúdo a restaurar...
    ents[0]["before"] = "PWNED"                       # ...mas não sabe a chave p/ recomputar o mac
    cp.journal.write_text(json.dumps(ents[0]) + "\n", encoding="utf-8")
    f.write_text("v2", encoding="utf-8")
    reverted = cp.rollback(1)
    assert reverted == [] and f.read_text(encoding="utf-8") == "v2"   # mac não bate → ignorado


def test_hmac_key_is_private(tmp_path):
    import os as _os
    import stat as _stat
    ws = tmp_path / "ws"
    ws.mkdir()
    cp = Checkpoints(ws)
    cp.snapshot("a.txt")                              # cria a chave
    if cp.keyfile.exists():
        assert _stat.S_IMODE(_os.stat(cp.keyfile).st_mode) & 0o077 == 0   # sem leitura p/ grupo/outros


def test_total_journal_cap_compacts(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    cp = Checkpoints(ws)
    cp._MAX_JOURNAL = 2000                            # cap baixo p/ forçar compactação
    for i in range(60):
        (ws / "a.txt").write_text(f"conteudo-{i}" * 5, encoding="utf-8")
        cp.snapshot("a.txt")
    assert cp.journal.stat().st_size <= cp._MAX_JOURNAL * 2   # podou o mais antigo
    assert all(cp._verify(cp.entries()))             # e o que sobrou continua com cadeia íntegra
