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


# ---------------------------------------------------------------- rg fast-path (#2)

def test_rg_used_when_available(tmp_path, monkeypatch):
    """Com `rg` no PATH, o subprocess é chamado (mockado) e o resultado do rg-mock decide QUAIS
    arquivos são varridos — prova que o fast-path é de fato tomado, não só um no-op decorativo."""
    import subprocess as _subprocess

    from okami.core.tools import search as search_mod

    (tmp_path / "a.py").write_text("BUSCA_ALVO\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("BUSCA_ALVO\n", encoding="utf-8")   # rg-mock NÃO vai listar este

    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        assert cmd[0] == "/usr/bin/rg"
        assert "--files-with-matches" in cmd
        return _subprocess.CompletedProcess(cmd, 0, stdout=str(tmp_path / "a.py") + "\n", stderr="")

    monkeypatch.setattr(search_mod.shutil, "which", lambda name: "/usr/bin/rg" if name == "rg" else None)
    monkeypatch.setattr(search_mod.subprocess, "run", fake_run)

    res = SearchFiles().run({"query": "BUSCA_ALVO"}, ToolContext(workspace=tmp_path))
    assert calls, "rg deveria ter sido invocado"
    assert res.ok
    assert "a.py:1" in res.output
    assert "b.py" not in res.output          # só o que o rg (mockado) devolveu foi varrido


def test_rg_unavailable_falls_back_to_python(tmp_path, monkeypatch):
    """Sem `rg` no PATH, cai no motor puro-Python — resultado IDÊNTICO ao fast-path p/ o mesmo input."""
    from okami.core.tools import search as search_mod

    (tmp_path / "a.py").write_text("BUSCA_ALVO\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("BUSCA_ALVO\n", encoding="utf-8")

    monkeypatch.setattr(search_mod.shutil, "which", lambda name: None)
    res = SearchFiles().run({"query": "BUSCA_ALVO"}, ToolContext(workspace=tmp_path))
    assert res.ok
    assert "a.py:1" in res.output and "b.py:1" in res.output   # sem rg, varre tudo


def test_rg_and_fallback_produce_identical_output(tmp_path):
    """Com `rg` real instalado (ambiente de CI/dev tem ripgrep), o resultado do fast-path bate
    byte-a-byte com o fallback puro-Python forçado (regressão de formato)."""
    import okami.core.tools.search as search_mod

    if search_mod.shutil.which("rg") is None:
        import pytest
        pytest.skip("rg não instalado neste ambiente")

    (tmp_path / "a.py").write_text("import os\ndef foo():\n    return BUSCA_ALVO\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("nada aqui\noutra BUSCA_ALVO linha\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.py").write_text("x = 1  # BUSCA_ALVO no comentário\n", encoding="utf-8")

    ctx = ToolContext(workspace=tmp_path)
    with_rg = SearchFiles().run({"query": "BUSCA_ALVO", "context": 1}, ctx)

    real_which = search_mod.shutil.which
    search_mod.shutil.which = lambda name: None if name == "rg" else real_which(name)
    try:
        without_rg = SearchFiles().run({"query": "BUSCA_ALVO", "context": 1}, ctx)
    finally:
        search_mod.shutil.which = real_which

    assert with_rg.ok and without_rg.ok
    assert with_rg.output == without_rg.output


def test_rg_respects_gitignore(tmp_path):
    """rg pula sozinho o que está no .gitignore — arquivo ignorado NÃO aparece nem no fast-path."""
    import subprocess

    import okami.core.tools.search as search_mod

    if search_mod.shutil.which("rg") is None:
        import pytest
        pytest.skip("rg não instalado neste ambiente")

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text("ignored_dir/\n", encoding="utf-8")
    (tmp_path / "a.py").write_text("BUSCA_ALVO\n", encoding="utf-8")
    (tmp_path / "ignored_dir").mkdir()
    (tmp_path / "ignored_dir" / "b.py").write_text("BUSCA_ALVO\n", encoding="utf-8")

    res = SearchFiles().run({"query": "BUSCA_ALVO"}, ToolContext(workspace=tmp_path))
    assert res.ok
    assert "a.py:1" in res.output
    assert "ignored_dir" not in res.output


def test_rg_incompatible_regex_falls_back(tmp_path):
    """Regex com backreference (só existe em Python `re`, não no motor do rg) → rg erra (rc != 0/1) →
    cai no fallback puro-Python em vez de devolver lista vazia/errada."""
    (tmp_path / "a.py").write_text("abab\n", encoding="utf-8")
    res = SearchFiles().run({"query": r"(ab)\1"}, ToolContext(workspace=tmp_path))
    assert res.ok
    assert "a.py:1" in res.output
