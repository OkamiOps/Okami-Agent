"""`_resolve_agent`/`_load` sem okami.yaml: erro imprime 1x só + convite pra `okami setup` (paridade
Hermes main.py:2279-2306 "Run setup now? [Y/n]"). Interativo pergunta; não-interativo (CI/pipe) nunca
trava — só orienta e sai 1."""
from __future__ import annotations

import io

import pytest
import typer

import okami.menu as menu_mod
from okami.cli import _shared


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    """Sem okami.yaml no CWD nem na 'casa' — find_config() tem que falhar de verdade (FileNotFoundError)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path / "home"))


def _capture(monkeypatch) -> io.StringIO:
    """Redireciona `_shared.console` p/ um buffer — via `_file` (privado), NÃO a property `.file`:
    ler `.file` resolve `sys.stdout` NA HORA e monkeypatch restauraria esse valor CONGELADO no
    teardown, quebrando a resolução dinâmica que o CliRunner (click) de outros testes depende
    (capturou 2 testes de test_terminal_repl.py até isto ser corrigido)."""
    buf = io.StringIO()
    monkeypatch.setattr(_shared.console, "_file", buf)
    return buf


def test_missing_config_error_prints_exactly_once(monkeypatch):
    monkeypatch.setattr(menu_mod, "_interactive", lambda: False)
    buf = _capture(monkeypatch)
    with pytest.raises(typer.Exit):
        _shared._resolve_agent(None, "workspaces/default")
    out = buf.getvalue()
    assert out.count("Falha ao carregar config") == 1, out


def test_missing_config_noninteractive_guidance_no_prompt(monkeypatch):
    monkeypatch.setattr(menu_mod, "_interactive", lambda: False)
    confirmed = {"asked": False}

    def _confirm(*a, **k):
        confirmed["asked"] = True
        return True
    monkeypatch.setattr(menu_mod, "confirm", _confirm)
    buf = _capture(monkeypatch)

    with pytest.raises(typer.Exit) as ei:
        _shared._resolve_agent(None, "workspaces/default")

    assert ei.value.exit_code == 1
    assert confirmed["asked"] is False, "não-interativo não pode perguntar nada (travaria em CI/pipe)"
    out = buf.getvalue()
    assert "okami setup" in out


def test_missing_config_interactive_offers_setup_and_runs_on_yes(monkeypatch, tmp_path):
    monkeypatch.setattr(menu_mod, "_interactive", lambda: True)
    monkeypatch.setattr(menu_mod, "confirm", lambda *a, **k: True)

    calls = {"n": 0}

    def _fake_setup(**kwargs):
        calls["n"] += 1
        (tmp_path / "home").mkdir(parents=True, exist_ok=True)
        (tmp_path / "home" / "okami.yaml").write_text(
            "default_provider: p\nproviders:\n  p:\n    model: m\n    transport: litellm\n",
            encoding="utf-8",
        )
    monkeypatch.setattr("okami.cli.commands.setup.setup", _fake_setup)
    _capture(monkeypatch)

    cfg, ws, name, home = _shared._resolve_agent(None, "workspaces/default")

    assert calls["n"] == 1, "sim → deveria ter rodado o wizard"
    assert cfg.default_provider == "p"


def test_missing_config_interactive_declines_setup_on_no(monkeypatch):
    monkeypatch.setattr(menu_mod, "_interactive", lambda: True)
    monkeypatch.setattr(menu_mod, "confirm", lambda *a, **k: False)

    calls = {"n": 0}

    def _fake_setup(**kwargs):
        calls["n"] += 1
    monkeypatch.setattr("okami.cli.commands.setup.setup", _fake_setup)
    _capture(monkeypatch)

    with pytest.raises(typer.Exit):
        _shared._resolve_agent(None, "workspaces/default")

    assert calls["n"] == 0, "não → não deveria rodar o wizard"
