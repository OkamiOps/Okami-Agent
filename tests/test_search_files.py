"""search_files por CONTEÚDO (pesquisa #6 item 2, paridade Hermes search_tool) + fim do alias-trap.

Busca regex no CONTEÚDO dos arquivos do workspace (não só por nome, que é o find_files). Modos
content/files/count, filtro por glob, contexto -A/-B, paginação, case-insensitive. Jailed ao
workspace, pula binário/.git/.venv, redige segredo no match. E o alias `search_files→find_files`
do harness DEVE sumir (era trap: modelo pedia grep e recebia busca por nome).
"""
from __future__ import annotations

from pathlib import Path
from okami.core.tools import ToolContext
from okami.core.tools.search import SearchFiles


def _ws(tmp_path):
    (tmp_path / "a.py").write_text("import os\ndef foo():\n    return BUSCA_ALVO\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("nada aqui\noutra BUSCA_ALVO linha\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.py").write_text("x = 1  # BUSCA_ALVO no comentário\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "ignored.py").write_text("BUSCA_ALVO\n", encoding="utf-8")
    return ToolContext(workspace=tmp_path)


def test_content_mode_finds_matches(tmp_path):
    res = SearchFiles().run({"query": "BUSCA_ALVO"}, _ws(tmp_path))
    assert res.ok and res.effect is False
    assert "a.py:3" in res.output and "b.txt:2" in res.output
    assert "sub/c.py" in res.output
    assert ".git" not in res.output                  # pula .git


def test_files_mode_lists_files_only(tmp_path):
    res = SearchFiles().run({"query": "BUSCA_ALVO", "mode": "files"}, _ws(tmp_path))
    assert "a.py" in res.output and "b.txt" in res.output
    assert ":3" not in res.output and "def foo" not in res.output   # só nomes


def test_count_mode(tmp_path):
    res = SearchFiles().run({"query": "BUSCA_ALVO", "mode": "count"}, _ws(tmp_path))
    assert "3" in res.output                          # 3 arquivos com match (a, b, sub/c)


def test_glob_filter(tmp_path):
    res = SearchFiles().run({"query": "BUSCA_ALVO", "glob": "*.py"}, _ws(tmp_path))
    assert "a.py" in res.output and "c.py" in res.output
    assert "b.txt" not in res.output


def test_case_insensitive(tmp_path):
    res = SearchFiles().run({"query": "busca_alvo", "ignore_case": True}, _ws(tmp_path))
    assert "a.py:3" in res.output


def test_context_lines(tmp_path):
    res = SearchFiles().run({"query": "BUSCA_ALVO", "context": 1, "glob": "a.py"}, _ws(tmp_path))
    assert "def foo" in res.output                    # linha anterior ao match aparece com context=1


def test_no_match(tmp_path):
    res = SearchFiles().run({"query": "ZZZNADA"}, _ws(tmp_path))
    assert res.ok and ("nada" in res.output.lower() or "0" in res.output)


def test_invalid_regex_teaches(tmp_path):
    res = SearchFiles().run({"query": "[unclosed"}, _ws(tmp_path))
    assert not res.ok and "regex" in res.output.lower()


def test_secret_in_match_redacted(tmp_path):
    secret_line = "api_key=sk-ABCDEF1234567890SECRETVALUE find_me\n"  # pragma: allowlist secret  (FAKE)
    (tmp_path / "s.txt").write_text(secret_line, encoding="utf-8")
    res = SearchFiles().run({"query": "find_me"}, ToolContext(workspace=tmp_path))
    assert res.ok
    assert "SECRETVALUE" not in res.output            # redigido no output


def test_registered_and_no_alias_trap(tmp_path):
    from okami.core.tools import default_registry
    from okami.core.harness.loop import _TOOL_ALIASES
    assert "search_files" in default_registry()
    assert _TOOL_ALIASES.get("search_files") != "find_files"   # alias-trap removido


def test_remote_surface_allows_search(tmp_path):
    from okami.core.tool_policy import denied
    assert not denied("telegram", "search_files")     # leitura pura


def test_relative_workspace_does_not_crash(tmp_path, monkeypatch):
    # bug real (smoke): workspace relativo + rglob absoluto → relative_to estourava
    (tmp_path / "a.py").write_text("ACHE_ISSO = 1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    res = SearchFiles().run({"query": "ACHE_ISSO"}, ToolContext(workspace=Path(".")))
    assert res.ok and "a.py:1" in res.output
