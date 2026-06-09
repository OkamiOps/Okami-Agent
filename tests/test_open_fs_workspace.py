"""Casa ISOLADA (identidade/memória em agents/<id>/) + acesso a TODO o FS no CLI (open_fs).

Bug relatado (Windows e além): o agente não conseguia mexer em pastas fora do workspace porque o
workspace = a pastinha de config do próprio agente. Agora separa-se a CASA (identidade/memória/sessões,
isolada) do WORKSPACE de arquivos (CWD/--workspace), e o CLI liga open_fs → o dono alcança qualquer
arquivo. Telegram/grupo continua confinado (open_fs=False).
"""
from __future__ import annotations

import pytest


def test_safe_path_jailed_by_default_blocks_outside(tmp_path):
    from okami.core.file_safety import PathEscape, safe_path
    ws = tmp_path / "home"
    ws.mkdir()
    with pytest.raises(PathEscape):
        safe_path(ws, str(tmp_path / "outside.txt"))     # absoluto fora do ws → bloqueado (jail)


def test_safe_path_open_fs_allows_absolute_anywhere(tmp_path):
    from okami.core.file_safety import safe_path
    ws = tmp_path / "home"
    ws.mkdir()
    target = tmp_path / "proj" / "main.py"
    assert safe_path(ws, str(target), open_fs=True) == target.resolve()   # acesso amplo: absoluto livre


def test_safe_path_open_fs_relative_anchors_on_workspace(tmp_path):
    from okami.core.file_safety import safe_path
    ws = tmp_path / "proj"
    ws.mkdir()
    assert safe_path(ws, "main.py", open_fs=True) == (ws / "main.py").resolve()   # relativo ancora no ws


def test_tool_context_open_fs_flows_to_safe_path(tmp_path):
    from okami.core.file_safety import PathEscape
    from okami.core.tools.base import ToolContext, _safe_path
    ws = tmp_path / "home"
    ws.mkdir()
    with pytest.raises(PathEscape):
        _safe_path(ToolContext(workspace=ws), str(tmp_path / "x.txt"))            # jailed
    got = _safe_path(ToolContext(workspace=ws, open_fs=True), str(tmp_path / "x.txt"))
    assert got == (tmp_path / "x.txt").resolve()                                  # open_fs → permitido


def test_resolve_agent_separates_isolated_home_from_cwd_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    (tmp_path / "okami.yaml").write_text(
        "default_provider: lmstudio\nproviders: {lmstudio: {model: m}}\n", encoding="utf-8")
    proj = tmp_path / "project"
    proj.mkdir()
    monkeypatch.chdir(proj)                       # CWD = projeto (acha o okami.yaml de tmp_path no ancestral)
    from okami.cli._shared import _ensure_agent, _resolve_agent
    from okami.home import agents_dir
    _ensure_agent("okami")                        # grava em <base>/agents/okami (= tmp_path/agents/okami)
    cfg, ws, name, home = _resolve_agent("okami", "workspaces/default")
    assert name == "okami"
    assert ws.resolve() == proj.resolve()                       # ARQUIVOS = CWD (o projeto do usuário)
    assert home.resolve() == (agents_dir() / "okami").resolve()  # CASA = agents/okami (isolada, identidade/memória)
    # --workspace explícito vence o CWD
    _, ws2, _, _ = _resolve_agent("okami", str(tmp_path / "other"))
    assert ws2 == (tmp_path / "other")
