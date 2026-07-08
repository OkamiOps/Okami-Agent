"""Testes da camada de arquivos .md (sempre on), merge de config e `okami setup`."""

from __future__ import annotations
import pytest

import yaml

from okami.config import load_config
from okami.memory import files


def test_core_block_includes_all_md_with_caps(tmp_path):
    (tmp_path / "AGENTS.md").write_text("Use ShadCN sempre.", encoding="utf-8")
    (tmp_path / "USER.md").write_text("X" * 9000, encoding="utf-8")   # estoura o cap
    (tmp_path / "MEMORY.md").write_text("Deploy via Vercel.", encoding="utf-8")
    block = files.core_block(tmp_path, {"user": 4000})
    assert "INSTRUÇÕES DO PROJETO" in block and "Use ShadCN" in block
    assert "MEMORY.md" in block and "Vercel" in block
    # USER.md capado em 4000 (checa o run de X, não a contagem total — ANTISLOP builtin pode ter X's)
    assert "X" * 4000 in block and "X" * 4001 not in block


def test_core_block_only_antislop_when_no_files(tmp_path):
    # Sem arquivos no home, o ANTISLOP builtin (guardrail fixo versionado) ainda entra — é sempre-on.
    block = files.core_block(tmp_path)
    assert "ANTISLOP" in block
    # e nada além dele (nenhuma outra camada de identidade/core)
    assert "INSTRUÇÕES DO PROJETO" not in block and "MEMORY.md" not in block


def test_core_block_injects_identity_in_order(tmp_path):
    (tmp_path / "SOUL.md").write_text("valores: confiável", encoding="utf-8")
    (tmp_path / "VOICE.md").write_text("tom: direto", encoding="utf-8")
    (tmp_path / "PROFILE.md").write_text("self: engenheiro", encoding="utf-8")  # fallback de PERSONA
    (tmp_path / "MEMORY.md").write_text("deploy Vercel", encoding="utf-8")
    block = files.core_block(tmp_path)
    # identidade presente, incl. PROFILE.md como fallback de PERSONA
    assert "SOUL.md" in block and "VOICE.md" in block and "PERSONA" in block
    assert "engenheiro" in block
    # ordem: SOUL antes de VOICE antes de PERSONA antes de MEMORY
    assert block.index("SOUL") < block.index("VOICE") < block.index("PERSONA") < block.index("MEMÓRIA")


def test_identity_default_cap_is_6000(tmp_path):
    (tmp_path / "SOUL.md").write_text("S" * 9000, encoding="utf-8")
    block = files.core_block(tmp_path)  # sem limits → default 6000 p/ identidade
    assert ("S" * 6000) in block and ("S" * 6001) not in block


def test_persona_init_creates_stubs(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from okami.cli import app

    monkeypatch.chdir(tmp_path)
    res = CliRunner().invoke(app, ["persona-init", "--name", "Okami", "-w", "ws"])
    assert res.exit_code == 0
    for f in ("SOUL.md", "VOICE.md", "PERSONA.md"):
        assert (tmp_path / "ws" / f).exists()


def test_append_user_dedup(tmp_path):
    files.append_user(tmp_path, "prefere modo escuro")
    files.append_user(tmp_path, "prefere modo escuro")
    content = (tmp_path / "USER.md").read_text(encoding="utf-8")
    assert content.count("prefere modo escuro") == 1


def test_config_local_override(tmp_path):
    (tmp_path / "okami.yaml").write_text(
        "default_provider: lmstudio\n"
        "memory:\n  backend: sqlite-fts5\n"
        "providers:\n  lmstudio:\n    model: openai/x\n    api_key: k\n",
        encoding="utf-8",
    )
    (tmp_path / "okami.local.yaml").write_text(
        "memory:\n  backend: [holographic, honcho]\n", encoding="utf-8")
    cfg = load_config(tmp_path / "okami.yaml")
    assert cfg.memory["backend"] == ["holographic", "honcho"]      # override aplicado
    assert "lmstudio" in cfg.providers                             # base preservada


def test_setup_writes_local_yaml(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from okami.cli import app

    monkeypatch.chdir(tmp_path)
    res = CliRunner().invoke(app, ["setup", "--memory", "holographic"])
    assert res.exit_code == 0
    written = yaml.safe_load((tmp_path / "okami.local.yaml").read_text(encoding="utf-8"))
    assert written["memory"]["backend"] == "holographic"
    assert written["memory"]["files"]["user"] == 4000


@pytest.fixture(autouse=True)
def _okami_home_to_tmp(tmp_path, monkeypatch):
    """config_dir() grava na CASA (~/.okami) quando não há projeto no CWD — aponta OKAMI_HOME pro tmp do
    teste p/ não tocar a casa real e manter as asserções em tmp_path."""
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
