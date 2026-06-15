"""Item 7 (#8): convenções de SUBPASTA (AGENTS.md/CLAUDE.md/.cursorrules) descobertas ao navegar e
injetadas no RESULTADO da tool (não no system prompt → preserva o prompt cache). Em monorepo, cada
`packages/x/` tem regra própria que o core_block (raiz) nunca vê."""
from __future__ import annotations


def test_subdir_hint_surfaces_subfolder_agents_md(tmp_path):
    from okami.core.subdir_hints import subdir_hint
    (tmp_path / "packages" / "x").mkdir(parents=True)
    (tmp_path / "packages" / "x" / "AGENTS.md").write_text("Regra: use tabs aqui", encoding="utf-8")
    hint = subdir_hint(tmp_path, tmp_path / "packages" / "x" / "foo.py", set())
    assert "use tabs aqui" in hint and "packages/x" in hint


def test_subdir_hint_dedups_per_dir(tmp_path):
    from okami.core.subdir_hints import subdir_hint
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "CLAUDE.md").write_text("convencaoX", encoding="utf-8")
    seen: set[str] = set()
    first = subdir_hint(tmp_path, tmp_path / "pkg" / "a.py", seen)
    second = subdir_hint(tmp_path, tmp_path / "pkg" / "b.py", seen)
    assert "convencaoX" in first and second == ""        # 2ª vez na mesma pasta não repete


def test_subdir_hint_skips_workspace_root(tmp_path):
    # AGENTS.md da RAIZ já vai no core_block — não re-injeta como hint de subpasta.
    from okami.core.subdir_hints import subdir_hint
    (tmp_path / "AGENTS.md").write_text("raiz", encoding="utf-8")
    assert subdir_hint(tmp_path, tmp_path / "foo.py", set()) == ""


def test_subdir_hint_empty_outside_workspace(tmp_path):
    from okami.core.subdir_hints import subdir_hint
    (tmp_path / "ws").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "AGENTS.md").write_text("nope", encoding="utf-8")
    assert subdir_hint(tmp_path / "ws", outside / "x.py", set()) == ""


def test_subdir_hint_caps_large_file(tmp_path):
    from okami.core.subdir_hints import subdir_hint
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "AGENTS.md").write_text("A" * 20000, encoding="utf-8")
    hint = subdir_hint(tmp_path, tmp_path / "pkg" / "z.py", set())
    assert len(hint) < 12000                              # cap ~8k + moldura


def test_read_file_appends_subdir_hint(tmp_path):
    # Integração: ao LER um arquivo de subpasta, o resultado já traz a convenção daquela pasta.
    from okami.core.tools import ReadFile, ToolContext
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "AGENTS.md").write_text("Regra local: 2 espacos", encoding="utf-8")
    (tmp_path / "pkg" / "mod.py").write_text("print(1)", encoding="utf-8")
    ctx = ToolContext(workspace=tmp_path)
    r = ReadFile().run({"path": "pkg/mod.py"}, ctx)
    assert r.ok and "print(1)" in r.output and "Regra local: 2 espacos" in r.output


def test_read_file_hint_not_repeated_second_read(tmp_path):
    from okami.core.tools import ReadFile, ToolContext
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "AGENTS.md").write_text("convencao-unica", encoding="utf-8")
    (tmp_path / "pkg" / "a.py").write_text("a", encoding="utf-8")
    (tmp_path / "pkg" / "b.py").write_text("b", encoding="utf-8")
    ctx = ToolContext(workspace=tmp_path)
    ReadFile().run({"path": "pkg/a.py"}, ctx)
    second = ReadFile().run({"path": "pkg/b.py"}, ctx)
    assert "convencao-unica" not in second.output        # mesma pasta no mesmo turno → 1× só
