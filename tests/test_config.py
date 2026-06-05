"""`okami config` e `okami status` (estilo hermes/openclaw): get/set/path + auto-roteamento de segredo."""

from __future__ import annotations

import yaml
from typer.testing import CliRunner

from okami.cli import _coerce, _is_secret_key, app

runner = CliRunner()
_YAML = ("default_provider: lmstudio\nproviders:\n"
         "  lmstudio: {model: openai/x, api_key: lm, tier: local}\n")


def test_config_check_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "okami.yaml").write_text(_YAML, encoding="utf-8")
    res = runner.invoke(app, ["config", "check", "--json"])
    assert '"config_loads": true' in res.output and '"default_provider": "lmstudio"' in res.output
    assert '"model"' in res.output                          # consistente com doctor/policy --json


def test_login_api_key_provider_saves_key(tmp_path, monkeypatch):
    # BUG do usuário: `okami login minimax` dizia "não tem fluxo de login". Agora provider api_key
    # PEDE a chave e grava no .env (autenticar = ter a chave).
    monkeypatch.chdir(tmp_path)
    (tmp_path / "okami.yaml").write_text(
        "default_provider: lmstudio\nproviders:\n"
        "  lmstudio: {model: openai/x, api_key: lm, tier: local}\n"
        "  mimo: {model: openai/m, api_key_env: MIMO_API_KEY, tier: weak}\n", encoding="utf-8")
    import okami.menu as _menu
    monkeypatch.setattr(_menu, "text", lambda *a, **k: "tp-secret123")    # usuário cola a chave
    saved: dict = {}
    import okami.cli._shared as _sh
    monkeypatch.setattr(_sh, "_set_env_var", lambda k, v, **kw: saved.update({k: v}))
    res = runner.invoke(app, ["login", "mimo"])
    assert res.exit_code == 0
    assert saved.get("MIMO_API_KEY") == "tp-secret123"   # gravou no .env
    assert "autenticado" in res.output


def test_experimental_provider_marked_not_broken(tmp_path, monkeypatch):
    # provider experimental: aparece como 'experimental' (opt-in), NÃO como 'falta auth'/quebrado.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "okami.yaml").write_text(
        "default_provider: lmstudio\nproviders:\n"
        "  lmstudio: {model: openai/x, api_key: lm, tier: local}\n"
        "  mimo: {model: openai/m, api_key_env: MIMO_API_KEY, experimental: true, tier: weak}\n",
        encoding="utf-8")
    out = runner.invoke(app, ["providers"]).output
    assert "experimental" in out
    j = runner.invoke(app, ["providers", "--json"]).output
    assert '"experimental": true' in j


def test_is_secret_key_and_coerce():
    assert _is_secret_key("OPENAI_API_KEY") and _is_secret_key("MIMO_API_KEY")
    assert not _is_secret_key("memory.backend") and not _is_secret_key("approvals.mode")
    assert _coerce("true") is True and _coerce("false") is False and _coerce("null") is None
    assert _coerce("42") == 42 and _coerce("1.5") == 1.5
    assert _coerce("a,b,c") == ["a", "b", "c"] and _coerce("texto") == "texto"


def test_config_set_routes_secret_to_env_value_to_local(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))          # ~ → tmp (segredo vai pro .env GLOBAL ~/.okami/.env)
    (tmp_path / "okami.yaml").write_text(_YAML, encoding="utf-8")
    runner.invoke(app, ["config", "set", "memory.backend", "holographic"])
    runner.invoke(app, ["config", "set", "approvals.mode", "yolo"])
    runner.invoke(app, ["config", "set", "persona.observe", "false"])   # coerção p/ bool
    runner.invoke(app, ["config", "set", "OPENAI_API_KEY", "sk-secret"])  # segredo → .env

    local = yaml.safe_load((tmp_path / "okami.local.yaml").read_text(encoding="utf-8"))
    assert local["memory"]["backend"] == "holographic"
    assert local["approvals"]["mode"] == "yolo"
    assert local["persona"]["observe"] is False
    assert "sk-secret" not in (tmp_path / "okami.local.yaml").read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=sk-secret" in (tmp_path / ".okami" / ".env").read_text(encoding="utf-8")


def test_config_get_reads_merged_and_unset(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "okami.yaml").write_text(_YAML, encoding="utf-8")
    runner.invoke(app, ["config", "set", "memory.backend", "holographic"])
    assert "holographic" in runner.invoke(app, ["config", "get", "memory.backend"]).output
    assert "openai/x" in runner.invoke(app, ["config", "get", "providers.lmstudio.model"]).output  # do base
    runner.invoke(app, ["config", "unset", "memory.backend"])
    local = yaml.safe_load((tmp_path / "okami.local.yaml").read_text(encoding="utf-8"))
    assert "backend" not in (local.get("memory") or {})


def test_config_show_redacts_secret(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "okami.yaml").write_text(
        "default_provider: x\nproviders:\n  x: {model: m, api_key: super-secret-literal, tier: local}\n",
        encoding="utf-8")
    out = runner.invoke(app, ["config", "show"]).output
    assert "super-secret-literal" not in out and "***" in out


def test_status_shows_resolved_view(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "okami.yaml").write_text(_YAML, encoding="utf-8")
    out = runner.invoke(app, ["status"]).output
    assert "OKAMI" in out and "Session" in out and "Providers" in out   # multi-section report (EN default)
    assert "lmstudio" in out and "openai/x" in out                      # tabela de providers


def test_status_localizes_to_portuguese(tmp_path, monkeypatch):
    from okami import i18n
    monkeypatch.chdir(tmp_path)
    (tmp_path / "okami.yaml").write_text(_YAML, encoding="utf-8")
    i18n.set_lang("pt")                                  # PT continua disponível (i18n bilíngue)
    try:
        out = runner.invoke(app, ["status"]).output
        assert "Sessão" in out and "Próximos passos" in out and "Canais" in out
    finally:
        i18n.set_lang(None)
