"""Wizard de setup (onboarding): atalho não-interativo + criação do okami.yaml do zero."""

from __future__ import annotations

import os

import yaml
from typer.testing import CliRunner

from okami.cli import _build_memory_block, app

runner = CliRunner()


def test_build_memory_block_variants():
    assert _build_memory_block("fts5")["backend"] == "sqlite-fts5"
    assert _build_memory_block("holographic")["backend"] == "holographic"
    combo = _build_memory_block("holographic+honcho", honcho_url="http://h:8000")
    assert combo["backend"] == ["holographic", "honcho"] and combo["honcho"]["base_url"] == "http://h:8000"


def test_setup_memory_flag_noninteractive(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    res = runner.invoke(app, ["setup", "--memory", "fts5"])
    assert res.exit_code == 0
    data = yaml.safe_load((tmp_path / "okami.local.yaml").read_text(encoding="utf-8"))
    assert data["memory"]["backend"] == "sqlite-fts5"


def test_setup_wizard_creates_fresh_yaml(tmp_path, monkeypatch):
    """Sem okami.yaml + sem TTY → menus caem no fallback numerado; wizard cria tudo do zero."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("okami.llm.models.discover_models", lambda **kw: ([], "none"))  # sem rede
    # fluxo: provider=3(lmstudio) · api_base(default) · model-texto(default) · id(default) ·
    #        memória=1(fts5) · nome(default Okami) · telegram? não
    answers = "\n".join(["3", "", "", "", "1", "", "n"]) + "\n"
    res = runner.invoke(app, ["setup"], input=answers)
    assert res.exit_code == 0, res.output
    cfg = yaml.safe_load((tmp_path / "okami.yaml").read_text(encoding="utf-8"))
    assert cfg["default_provider"] == "lmstudio"
    assert cfg["providers"]["lmstudio"]["api_base"] == "http://localhost:1234/v1"
    local = yaml.safe_load((tmp_path / "okami.local.yaml").read_text(encoding="utf-8"))
    assert local["memory"]["backend"] == "sqlite-fts5"
    # o setup cria um AGENTE de verdade (nome vazio → agente default 'okami') + o define como default
    assert local["agents"]["default"] == "okami"
    assert (tmp_path / "agents" / "okami" / "agent.yaml").exists()
    assert (tmp_path / "agents" / "okami" / "SOUL.md").exists()


def test_setup_agent_section_creates_named_agent(tmp_path, monkeypatch):
    """`okami setup agent` com um nome cria agents/<slug>/ e o torna default."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "okami.yaml").write_text(
        "default_provider: lmstudio\nproviders:\n  lmstudio: {model: openai/x, api_key: lm, tier: local}\n",
        encoding="utf-8")
    res = runner.invoke(app, ["setup", "agent"], input="Time UX\n")
    assert res.exit_code == 0, res.output
    assert (tmp_path / "agents" / "time-ux" / "SOUL.md").exists()   # nome vira slug
    local = yaml.safe_load((tmp_path / "okami.local.yaml").read_text(encoding="utf-8"))
    assert local["agents"]["default"] == "time-ux"


def test_provider_add_writes_yaml_and_secret(tmp_path, monkeypatch):
    """`okami provider add` grava o provider no okami.yaml e a chave no .env (não no yaml)."""
    monkeypatch.chdir(tmp_path)
    # evita rede no teste: discover_models devolve um catálogo fixo
    monkeypatch.setattr("okami.llm.models.discover_models",
                        lambda **kw: (["gpt-4o-mini", "gpt-4o"], "catalog"))
    (tmp_path / "okami.yaml").write_text(
        "default_provider: lmstudio\nproviders:\n  lmstudio: {model: openai/x, api_key: lm, tier: local}\n",
        encoding="utf-8")
    # provider=7(openai) · API key='sk-test' (campo vem ANTES do modelo) · modelo(default) · id · default? não
    answers = "\n".join(["7", "sk-test", "", "", "n"]) + "\n"
    res = runner.invoke(app, ["provider", "add"], input=answers)
    assert res.exit_code == 0, res.output
    cfg = yaml.safe_load((tmp_path / "okami.yaml").read_text(encoding="utf-8"))
    assert "openai" in cfg["providers"]
    assert cfg["providers"]["openai"]["api_key_env"] == "OPENAI_API_KEY"
    assert cfg["providers"]["openai"]["model"] == "openai/gpt-4o-mini"   # prefixo + modelo escolhido
    assert "sk-test" not in (tmp_path / "okami.yaml").read_text(encoding="utf-8")   # chave NÃO no yaml
    assert "OPENAI_API_KEY=sk-test" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_discover_models_live_then_catalog(monkeypatch):
    """discover_models: usa /models ao vivo; se falhar, cai pro catálogo; senão vazio."""
    from okami.llm import models as M
    monkeypatch.setattr(M, "_http_models", lambda *a, **k: ["m-b", "m-a", "embedding-x"])
    got, src = M.discover_models(api_base="http://x/v1")
    assert src == "live" and got == ["m-a", "m-b"]          # ordena + filtra não-chat (embedding)

    def boom(*a, **k):
        raise OSError("offline")
    monkeypatch.setattr(M, "_http_models", boom)
    assert M.discover_models(api_base="http://x/v1", catalog=["c1"]) == (["c1"], "catalog")
    assert M.discover_models(api_base=None, catalog=[]) == ([], "none")


def test_provider_add_selects_model_and_merges_without_clobber(tmp_path, monkeypatch):
    """Re-adicionar um provider existente ESCOLHE o modelo e MESCLA (não apaga config nem models)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "okami.yaml").write_text(
        "default_provider: lmstudio\nproviders:\n"
        "  lmstudio: {model: openai/x, api_key: lm, tier: local}\n"
        "  codex: {model: openai-codex/gpt-5.4, transport: codex_oauth, auth: oauth_subscription,"
        " tier: strong, custom_keep: 1}\n", encoding="utf-8")
    # codex=1 · modelo gpt-5.5=1 · id default(codex→merge) · default? n · (login? n se perguntar)
    res = runner.invoke(app, ["provider", "add"], input="1\n1\n\nn\nn\n")
    assert res.exit_code == 0, res.output
    cx = yaml.safe_load((tmp_path / "okami.yaml").read_text(encoding="utf-8"))["providers"]["codex"]
    assert cx["model"] == "openai-codex/gpt-5.5"        # escolheu o modelo (não cravou 5.4)
    assert "gpt-5.5" in cx.get("models", [])            # lista de modelos preservada/adicionada
    assert cx.get("custom_keep") == 1                   # MERGE: não apagou o que já existia
    assert "modelo" in res.output and "gpt-5.5" in res.output   # diz qual modelo ficou


def test_help_command_lists_groups():
    res = runner.invoke(app, ["help"])
    assert res.exit_code == 0
    assert "provider add" in res.output and "Começar" in res.output
