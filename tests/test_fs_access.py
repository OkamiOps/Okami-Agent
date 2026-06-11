"""Acesso a arquivos por PERFIL (padrão de mercado: OpenClaw workspaceOnly / Hermes denylist).

Em vez de listar pasta por pasta, um knob único `tools.fs`:
  - workspace (default): só o workspace (jail seguro — deny-by-default p/ Telegram)
  - home: TUDO embaixo de ~/ (Documents, Pictures, Desktop, Downloads… sem listar)
  - full: o filesystem inteiro (= open_fs)
Segredo (.env/.ssh/.aws) segue bloqueado nos três. `allow_paths` continua p/ extras fora da home."""

from __future__ import annotations

from pathlib import Path

from okami.gateway.builders import fs_access_from_tools


def test_default_is_workspace_jail():
    acc = fs_access_from_tools({})
    assert acc["open_fs"] is False and acc["allow_paths"] == []


def test_fs_workspace_explicit():
    assert fs_access_from_tools({"fs": "workspace"}) == {"open_fs": False, "allow_paths": []}


def test_fs_home_grants_whole_home():
    acc = fs_access_from_tools({"fs": "home"})
    assert acc["open_fs"] is False
    assert str(Path.home()) in acc["allow_paths"]          # ~/ inteiro liberado, sem listar subpastas


def test_fs_full_is_open():
    assert fs_access_from_tools({"fs": "full"})["open_fs"] is True


def test_open_fs_true_backcompat():
    assert fs_access_from_tools({"open_fs": True})["open_fs"] is True


def test_home_plus_extra_paths():
    acc = fs_access_from_tools({"fs": "home", "allow_paths": ["/Volumes/x"]})
    assert str(Path.home()) in acc["allow_paths"] and "/Volumes/x" in acc["allow_paths"]


def test_allow_paths_alone_still_works():
    acc = fs_access_from_tools({"allow_paths": ["~/Downloads"]})
    assert acc["open_fs"] is False and acc["allow_paths"] == ["~/Downloads"]


def test_unknown_fs_value_falls_back_to_workspace():
    assert fs_access_from_tools({"fs": "banana"})["open_fs"] is False


# ----------------------------------------------------------------- ponta a ponta: home libera Documents/Pictures
def test_home_profile_lets_agent_read_anywhere_under_home(tmp_path, monkeypatch):
    from okami.core.tools.base import ToolContext, _safe_path
    # finge que a home é tmp_path → cria Documents/Pictures/Desktop
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    for sub in ("Documents", "Pictures", "Desktop", "Downloads"):
        (tmp_path / sub).mkdir()
        (tmp_path / sub / "a.txt").write_text("x")
    acc = fs_access_from_tools({"fs": "home"})
    ws = tmp_path / "agentes" / "minerva"
    ws.mkdir(parents=True)
    ctx = ToolContext(workspace=ws, allow_paths=acc["allow_paths"])
    # qualquer subpasta da home resolve sem listar cada uma
    for sub in ("Documents", "Pictures", "Desktop", "Downloads"):
        p = _safe_path(ctx, str(tmp_path / sub / "a.txt"))
        assert p == (tmp_path / sub / "a.txt").resolve()


def test_endpoint_kwargs_uses_fs_profile():
    from types import SimpleNamespace

    from okami.gateway.builders import _endpoint_kwargs_from_cfg
    cfg = SimpleNamespace(tools={"fs": "full"})
    assert _endpoint_kwargs_from_cfg(cfg)["open_fs"] is True
