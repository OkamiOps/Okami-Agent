"""okami remote add/list/remove — gerencia a allowlist de hosts no okami.yaml."""
from __future__ import annotations

import yaml
from typer.testing import CliRunner

from okami.cli._app import app


def _seed(tmp_path):
    cfg = tmp_path / "okami.yaml"
    cfg.write_text("default_provider: x\nproviders: {}\n", encoding="utf-8")
    return cfg


def test_add_grava_host_tailscale_por_padrao(tmp_path, monkeypatch):
    cfg = _seed(tmp_path)
    monkeypatch.chdir(tmp_path)
    res = CliRunner().invoke(app, ["remote", "add", "prod", "prod-server"])
    assert res.exit_code == 0
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert data["remote"]["hosts"]["prod"] == {"host": "prod-server", "via": "tailscale"}


def test_add_ssh_e_cwd(tmp_path, monkeypatch):
    cfg = _seed(tmp_path)
    monkeypatch.chdir(tmp_path)
    res = CliRunner().invoke(app, ["remote", "add", "nas", "deploy@10.0.0.5", "--ssh", "--cwd", "/srv"])
    assert res.exit_code == 0
    spec = yaml.safe_load(cfg.read_text(encoding="utf-8"))["remote"]["hosts"]["nas"]
    assert spec["via"] == "ssh" and spec["cwd"] == "/srv"


def test_list_mostra_hosts(tmp_path, monkeypatch):
    _seed(tmp_path)
    monkeypatch.chdir(tmp_path)
    CliRunner().invoke(app, ["remote", "add", "prod", "prod-server"])
    res = CliRunner().invoke(app, ["remote", "list"])
    assert res.exit_code == 0 and "prod" in res.output and "prod-server" in res.output


def test_remove_apaga(tmp_path, monkeypatch):
    cfg = _seed(tmp_path)
    monkeypatch.chdir(tmp_path)
    CliRunner().invoke(app, ["remote", "add", "prod", "prod-server"])
    res = CliRunner().invoke(app, ["remote", "remove", "prod"])
    assert res.exit_code == 0
    assert "prod" not in (yaml.safe_load(cfg.read_text(encoding="utf-8"))["remote"]["hosts"])
