"""`okami help` precisa mostrar como CONECTAR um canal (dor: onboarding de Telegram estava ausente
do help). Garante a seção Canais com os comandos fáceis (channel/pair/gateway)."""

from __future__ import annotations

from typer.testing import CliRunner

from okami.cli import app

runner = CliRunner()


def test_help_has_canais_section():
    out = runner.invoke(app, ["help"]).output.lower()
    assert "canais" in out


def test_help_shows_channel_add_telegram():
    out = runner.invoke(app, ["help"]).output
    assert "channel add telegram" in out


def test_help_shows_pair():
    out = runner.invoke(app, ["help"]).output
    assert "pair" in out


def test_help_still_has_comecar_and_chat():
    out = runner.invoke(app, ["help"]).output.lower()
    assert "começar" in out and "chat" in out
