"""Callback raiz da CLI: `okami --version` / `-V` mostram a versão e saem 0."""

from __future__ import annotations

from typer.testing import CliRunner

from okami import __version__
from okami.cli import app

runner = CliRunner()


def test_version_flag():
    res = runner.invoke(app, ["--version"])
    assert res.exit_code == 0 and __version__ in res.output


def test_version_short_flag():
    res = runner.invoke(app, ["-V"])
    assert res.exit_code == 0 and __version__ in res.output


def test_version_subcommand_still_works():
    res = runner.invoke(app, ["version"])
    assert res.exit_code == 0 and __version__ in res.output
