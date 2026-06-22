"""Caça it.8 (find→verify adversarial): superfícies VPS-facing. Remote força UTF-8; resolve_retention
não crasha com config escalar; transcript não permite traversal; MCP não vaza segredo no erro."""
from __future__ import annotations

from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------- #1 remote força UTF-8
def test_remote_run_forces_utf8_encoding():
    from okami.integrations.remote import RemoteTarget
    captured: dict = {}

    def fake(argv, **kw):
        captured.update(kw)
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    RemoteTarget(alias="a", host="h", runner=fake).run("echo oi", stdin="çãéü")
    assert captured.get("encoding") == "utf-8"            # não usa locale C/latin1 da VPS (crash/corrupção)


# ---------------------------------------------------------------- #13 retention ignora escalar
def test_resolve_retention_ignores_non_dict():
    from okami.core.maintenance import resolve_retention
    out = resolve_retention({"sessions": 30})             # config digitada errada (escalar onde é dict)
    assert isinstance(out["sessions"], dict)              # mantém o DEFAULT dict → cron de limpeza não crasha
    assert out["sessions"].get("days") == 30.0           # default preservado


# ---------------------------------------------------------------- #16 transcript anti-traversal
def test_transcript_path_blocks_traversal(tmp_path):
    from okami.gateway.sessions import TranscriptStore
    ts = TranscriptStore(tmp_path)
    for bad in ("../../etc/passwd", "a/b", "x\\y", ".."):
        with pytest.raises(ValueError, match="inválido"):
            ts._tx_path(bad)
    assert str(ts._tx_path("telegram:123")).endswith("telegram:123.jsonl")   # id normal passa


# ---------------------------------------------------------------- #2 MCP não vaza segredo no erro
def test_mcp_error_is_redacted():
    from okami.core.redact import redact
    leaked = "falha: token=sk-" + "ABCDEFGHIJKLMNOP1234567890"          # pragma: allowlist secret
    out = redact(leaked)
    assert "sk-ABCDEFGH" not in out and "«redacted»" in out               # o erro do MCP passa por aqui
