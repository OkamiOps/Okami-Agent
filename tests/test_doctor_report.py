"""Relatório estruturado do doctor (P2): coleta testável + --json + health binário."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from okami.cli import app
from okami.config import OkamiConfig, ProviderConfig
from okami.core.doctor import build_report, health_ok

runner = CliRunner()


def _cfg(ready=True):
    pc = ProviderConfig(name="lmstudio", model="openai/x", api_key="lm" if ready else "", tier="local")
    return OkamiConfig(default_provider="lmstudio", providers={"lmstudio": pc})


def test_build_report_structure():
    rep = build_report(_cfg(), ping=lambda b: (True, "ok"))   # ping injetado (sem rede)
    assert rep["default_provider"] == "lmstudio" and rep["providers"][0]["name"] == "lmstudio"
    assert "git" in rep["toolchain"] and "sqlite_fts5" in rep["checks"]
    assert rep["sandbox"]["backend"] == "local" and "version" in rep


def test_health_ok_reflects_default_provider_and_fts5():
    rep = build_report(_cfg(ready=True), ping=None)
    rep["checks"]["sqlite_fts5"] = True
    assert health_ok(rep) is True
    rep["checks"]["sqlite_fts5"] = False
    assert health_ok(rep) is False                            # FTS5 quebrado → não saudável
    bad = build_report(_cfg(ready=False), ping=None)
    bad["checks"]["sqlite_fts5"] = True
    assert health_ok(bad) is False                            # default provider sem auth → não saudável


def test_doctor_json_flag_outputs_valid_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "okami.yaml").write_text(
        "default_provider: lmstudio\nproviders:\n  lmstudio: {model: openai/x, api_key: lm, tier: local}\n",
        encoding="utf-8")
    res = runner.invoke(app, ["doctor", "--json"])
    payload = json.loads(res.output)                          # a saída é JSON válido
    assert payload["default_provider"] == "lmstudio" and "healthy" in payload and "sandbox" in payload
