"""Paridade Hermes: UMA tool de busca. search_files agora faz CONTEÚDO (grep, default) E NOME de arquivo
(target=files, delega ao find_files fuzzy) — o modelo não precisa escolher entre 2 tools de busca."""
from __future__ import annotations

from okami.core.tools.search import SearchFiles
from okami.core.tools.base import ToolContext


def test_search_files_target_files_finds_by_name(tmp_path):
    (tmp_path / "Okami-Agent.md").write_text("x", encoding="utf-8")
    (tmp_path / "outro.txt").write_text("y", encoding="utf-8")
    ctx = ToolContext(workspace=tmp_path)
    r = SearchFiles().run({"query": "okami_agent", "target": "files"}, ctx)   # fuzzy: caso/hífen/_
    assert r.ok and "Okami-Agent.md" in r.output
    assert "outro.txt" not in r.output


def test_search_files_default_is_content(tmp_path):
    (tmp_path / "a.py").write_text("alvo_unico = 1\n", encoding="utf-8")
    ctx = ToolContext(workspace=tmp_path)
    r = SearchFiles().run({"query": "alvo_unico"}, ctx)                       # default = conteúdo (grep)
    assert r.ok and "alvo_unico" in r.output and "a.py" in r.output
