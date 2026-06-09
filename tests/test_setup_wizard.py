"""Wizard de setup (onboarding): atalho não-interativo + criação do okami.yaml do zero."""

from __future__ import annotations
import pytest


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


def test_setup_posture_production_applies_hardened_strict(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    res = runner.invoke(app, ["setup", "posture"], input="2\n")    # 2 = Gateway público / produção
    assert res.exit_code == 0, res.output
    local = yaml.safe_load((tmp_path / "okami.local.yaml").read_text(encoding="utf-8"))
    assert local["sandbox"]["profile"] == "hardened-strict"
    assert "hardened-strict" in res.output


def test_setup_posture_dev_stays_local(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    res = runner.invoke(app, ["setup", "posture"], input="1\n")    # 1 = Local / dev
    assert res.exit_code == 0, res.output
    p = tmp_path / "okami.local.yaml"
    local = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    assert (local.get("sandbox") or {}).get("profile") != "hardened-strict"


def test_setup_wizard_creates_fresh_yaml(tmp_path, monkeypatch):
    """Sem okami.yaml + sem TTY → menus caem no fallback numerado; modo COMPLETO cria tudo do zero."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("okami.llm.models.discover_models", lambda **kw: ([], "none"))  # sem rede
    # fork=2(completo) · provider=3(lmstudio) · api_base(default) · model-texto(default) · id(default) ·
    #        memória=1(fts5) · nome(default Okami) · telegram? não
    answers = "\n".join(["2", "3", "", "", "", "1", "", "n"]) + "\n"
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
    """`okami provider add` grava o provider no okami.yaml e a chave no .env GLOBAL (não no yaml)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OKAMI_HOME", raising=False)    # este teste gerencia a casa via HOME (~/.okami)
    monkeypatch.setenv("HOME", str(tmp_path))          # ~ → tmp (segredo vai pro .env GLOBAL ~/.okami/.env)
    # evita rede no teste: discover_models devolve um catálogo fixo
    monkeypatch.setattr("okami.llm.models.discover_models",
                        lambda **kw: (["gpt-4o-mini", "gpt-4o"], "catalog"))
    (tmp_path / "okami.yaml").write_text(
        "default_provider: lmstudio\nproviders:\n  lmstudio: {model: openai/x, api_key: lm, tier: local}\n",
        encoding="utf-8")
    # provider=openai (índice do catálogo, robusto a reordenação) · API key='sk-test' (vem ANTES do
    # modelo) · modelo(default) · id · default? não
    from okami.provider_catalog import PRESETS
    idx = [p.key for p in PRESETS].index("openai") + 1
    answers = "\n".join([str(idx), "sk-test", "", "", "n"]) + "\n"
    res = runner.invoke(app, ["provider", "add"], input=answers)
    assert res.exit_code == 0, res.output
    cfg = yaml.safe_load((tmp_path / "okami.yaml").read_text(encoding="utf-8"))
    assert "openai" in cfg["providers"]
    assert cfg["providers"]["openai"]["api_key_env"] == "OPENAI_API_KEY"
    assert cfg["providers"]["openai"]["model"] == "openai/gpt-4o-mini"   # prefixo + modelo escolhido
    assert "sk-test" not in (tmp_path / "okami.yaml").read_text(encoding="utf-8")   # chave NÃO no yaml
    assert "OPENAI_API_KEY=sk-test" in (tmp_path / ".okami" / ".env").read_text(encoding="utf-8")


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


def test_setup_quick_uses_detected_provider(tmp_path, monkeypatch):
    """Modo RÁPIDO: detecta um provider pronto, só pede o modelo, cria o agente padrão."""
    monkeypatch.chdir(tmp_path)
    from okami import cli
    det = cli._Detected("lmstudio", "LM Studio local (no ar)",
                        {"api_base": "http://x/v1", "api_key": "lm", "tier": "local", "auth": "api_key"}, True)
    monkeypatch.setattr(cli, "_detect_environment", lambda existing=None: [det])
    monkeypatch.setattr("okami.llm.models.discover_models", lambda **kw: (["qwen-a", "qwen-b"], "live"))
    # fork=1(rápido) · usar=1(lmstudio detectado) · modelo=1(qwen-a)
    res = runner.invoke(app, ["setup"], input="1\n1\n1\n")
    assert res.exit_code == 0, res.output
    cfg = yaml.safe_load((tmp_path / "okami.yaml").read_text(encoding="utf-8"))
    assert cfg["default_provider"] == "lmstudio"
    assert cfg["providers"]["lmstudio"]["model"] == "openai/qwen-a"   # prefixo + modelo escolhido
    assert (tmp_path / "agents" / "okami" / "SOUL.md").exists()       # agente padrão criado sozinho


def test_detect_environment_finds_env_key(tmp_path, monkeypatch):
    """_detect_environment acha chave no ambiente (sem rede para locais)."""
    from okami import cli
    monkeypatch.setattr("okami.llm.models.discover_models", lambda **kw: ([], "none"))  # locais offline
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-x")
    found = {d.key for d in cli._detect_environment(existing={})}
    assert "openrouter" in found


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


def test_setup_sections_cover_whole_product(tmp_path, monkeypatch):
    """O setup não é só provider: voz, aprovação, aprendizado e persona são seções próprias."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "okami.yaml").write_text(
        "default_provider: lmstudio\nproviders:\n  lmstudio: {model: openai/x, api_key: lm, tier: local}\n",
        encoding="utf-8")

    def local():
        return yaml.safe_load((tmp_path / "okami.local.yaml").read_text(encoding="utf-8"))

    assert runner.invoke(app, ["setup", "voice"], input="2\n").exit_code == 0      # 2=ouvir(STT)
    assert local()["voice"]["stt"]["enabled"] is True
    assert runner.invoke(app, ["setup", "approvals"], input="3\n").exit_code == 0  # 3=yolo
    assert local()["approvals"]["mode"] == "yolo"
    assert runner.invoke(app, ["setup", "learning"], input="y\ny\n").exit_code == 0
    assert local()["learning"]["auto_skill"] is True and local()["learning"]["auto_tune"] is True
    assert runner.invoke(app, ["setup", "persona"], input="n\n").exit_code == 0
    assert local()["persona"]["observe"] is False


def test_help_command_lists_groups():
    res = runner.invoke(app, ["help"])
    assert res.exit_code == 0
    assert "provider add" in res.output and "Começar" in res.output


@pytest.fixture(autouse=True)
def _okami_home_to_tmp(tmp_path, monkeypatch):
    """config_dir() grava na CASA (~/.okami) quando não há projeto no CWD — aponta OKAMI_HOME pro tmp do
    teste p/ não tocar a casa real e manter as asserções em tmp_path."""
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
