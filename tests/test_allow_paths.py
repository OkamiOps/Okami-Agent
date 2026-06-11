"""Acesso a pastas FORA do workspace por config (dor real: agente no Telegram não lia ~/Downloads).

Duas diretivas no bloco `tools` do agent.yaml/okami.yaml:
  - tools.open_fs: true        → acesso a TODO o FS (igual ao dono no CLI)
  - tools.allow_paths: [dirs]  → workspace + ESSAS pastas (granular, mais seguro)
Segredo (.env/.ssh/.aws) continua bloqueado nos dois casos."""

from __future__ import annotations

from pathlib import Path

import pytest

from okami.core.file_safety import PathEscape, safe_path
from okami.core.tools.base import ToolContext, _safe_path


# ----------------------------------------------------------------- safe_path com allow_paths
def test_allow_paths_permits_listed_dir(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    extra = tmp_path / "Downloads"
    extra.mkdir()
    (extra / "rel.pdf").write_text("x")
    p = safe_path(ws, str(extra / "rel.pdf"), allow_paths=[extra])
    assert p == (extra / "rel.pdf").resolve()


def test_allow_paths_still_blocks_unlisted(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (tmp_path / "secreto").mkdir()
    with pytest.raises(PathEscape):
        safe_path(ws, str(tmp_path / "secreto" / "x"), allow_paths=[tmp_path / "Downloads"])


def test_allow_paths_expanduser(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    # ~ é expandido nos allow_paths (config guarda "~/Downloads")
    home_sub = Path("~/.okami-test-allow").expanduser()
    p = safe_path(ws, str(home_sub / "a.txt"), allow_paths=["~/.okami-test-allow"])
    assert str(home_sub) in str(p)


def test_workspace_still_works_with_allow_paths(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    assert safe_path(ws, "interno.txt", allow_paths=[tmp_path / "X"]) == (ws / "interno.txt").resolve()


def test_open_fs_overrides_everything(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    assert safe_path(ws, "/etc/hosts", open_fs=True) == Path("/etc/hosts").resolve()


# ----------------------------------------------------------------- _safe_path lê do ToolContext
def test_toolcontext_carries_allow_paths(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    extra = tmp_path / "Downloads"
    extra.mkdir()
    ctx = ToolContext(workspace=ws, allow_paths=[str(extra)])
    p = _safe_path(ctx, str(extra / "y.txt"))
    assert p == (extra / "y.txt").resolve()


def test_toolcontext_default_no_allow_paths_confines(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    ctx = ToolContext(workspace=ws)
    with pytest.raises(ValueError):                    # PathEscape é subclasse de ValueError
        _safe_path(ctx, str(tmp_path / "fora" / "z"))


# ----------------------------------------------------------------- read_file/list_dir respeitam
def test_read_file_reads_allowed_path(tmp_path):
    from okami.core.tools.files import ReadFile
    ws = tmp_path / "ws"
    ws.mkdir()
    extra = tmp_path / "Downloads"
    extra.mkdir()
    (extra / "nota.txt").write_text("conteúdo de fora")
    ctx = ToolContext(workspace=ws, allow_paths=[str(extra)])
    r = ReadFile().run({"path": str(extra / "nota.txt")}, ctx)
    assert r.ok and "conteúdo de fora" in r.output


def test_list_dir_lists_allowed_path(tmp_path):
    from okami.core.tools.files import ListDir
    ws = tmp_path / "ws"
    ws.mkdir()
    extra = tmp_path / "Downloads"
    extra.mkdir()
    (extra / "a.pdf").write_text("x")
    ctx = ToolContext(workspace=ws, allow_paths=[str(extra)])
    r = ListDir().run({"path": str(extra)}, ctx)
    assert r.ok and "a.pdf" in r.output


def test_read_file_blocks_unlisted_path(tmp_path):
    from okami.core.tools.files import ReadFile
    ws = tmp_path / "ws"
    ws.mkdir()
    (tmp_path / "privado").mkdir()
    (tmp_path / "privado" / "s.txt").write_text("nope")
    ctx = ToolContext(workspace=ws, allow_paths=[str(tmp_path / "Downloads")])
    r = ReadFile().run({"path": str(tmp_path / "privado" / "s.txt")}, ctx)
    assert not r.ok                                        # fora do workspace E dos allow_paths


# ----------------------------------------------------------------- config → endpoint
def test_endpoint_reads_open_fs_and_allow_paths_from_config():
    from types import SimpleNamespace

    from okami.gateway import builders

    captured = {}

    class FakeEP:
        def __init__(self, *a, **kw):
            captured.update(kw)

    cfg = SimpleNamespace(tools={"open_fs": True, "allow_paths": ["~/Downloads"]},
                          gateway={}, voice={}, approvals={}, provider=lambda: SimpleNamespace(
                              chars_per_token=4.0))
    # _mk_endpoint deve repassar open_fs e allow_paths lidos de cfg.tools
    fn = builders._endpoint_kwargs_from_cfg(cfg)
    assert fn["open_fs"] is True
    assert fn["allow_paths"] == ["~/Downloads"]
