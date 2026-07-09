"""Tool search_skills (okami/core/tools/skills_search.py) + CLI `okami skill search|browse` — fecha o
gap real (incidente 'gog'): o agente só instalava skill com owner/repo já em mãos; agora DESCOBRE
primeiro. install-from-search reusa a pipeline EXISTENTE (quarentena+scan+lockfile) sem duplicar nada.
"""
from __future__ import annotations

from pathlib import Path


def _stub_registry(monkeypatch, candidates):
    """Troca okami.skills.registry.default_source() por uma fonte fake devolvendo `candidates` fixos —
    tanto pro tool quanto pro CLI (ambos importam default_source no ponto de uso)."""
    class _Fake:
        def search(self, query, limit=10):
            q = (query or "").lower()
            return [c for c in candidates if q in c.name.lower() or q in c.description.lower()][:limit]

        def browse(self, limit=20):
            return candidates[:limit]

    import okami.skills.registry as reg
    monkeypatch.setattr(reg, "default_source", lambda: _Fake())
    return _Fake()


def _cand(name, source="anthropics/skills", only=None, trust="trusted", description="uma skill"):
    from okami.skills.registry import SkillCandidate
    return SkillCandidate(name=name, description=description, source=source,
                          only=only or name, trust=trust)


# ------------------------------------------------------------------ tool search_skills
def test_search_skills_tool_registered():
    from okami.core.tools.registry import default_registry
    assert "search_skills" in default_registry()


def test_search_skills_tool_returns_candidates(monkeypatch):
    _stub_registry(monkeypatch, [_cand("gmail-access", description="Acessa Gmail via OAuth")])
    from okami.core.tools.skills_search import SearchSkills
    from okami.core.tools.base import ToolContext
    res = SearchSkills().run({"query": "gmail"}, ToolContext(workspace=Path(".")))
    assert res.ok and res.effect is False
    assert "gmail-access" in res.output and "anthropics/skills" in res.output


def test_search_skills_tool_empty_query_browses(monkeypatch):
    _stub_registry(monkeypatch, [_cand("a"), _cand("b")])
    from okami.core.tools.skills_search import SearchSkills
    from okami.core.tools.base import ToolContext
    res = SearchSkills().run({}, ToolContext(workspace=Path(".")))
    assert res.ok and "a" in res.output and "b" in res.output


def test_search_skills_tool_no_results_is_friendly(monkeypatch):
    _stub_registry(monkeypatch, [])
    from okami.core.tools.skills_search import SearchSkills
    from okami.core.tools.base import ToolContext
    res = SearchSkills().run({"query": "nada-disso"}, ToolContext(workspace=Path(".")))
    assert res.ok and "nenhuma skill" in res.output.lower()


def test_search_skills_tool_never_raises_on_backend_failure(monkeypatch):
    import okami.skills.registry as reg

    class _Boom:
        def search(self, query, limit=10):
            raise RuntimeError("rede fora")

        def browse(self, limit=20):
            raise RuntimeError("rede fora")

    monkeypatch.setattr(reg, "default_source", lambda: _Boom())
    from okami.core.tools.skills_search import SearchSkills
    from okami.core.tools.base import ToolContext
    res = SearchSkills().run({"query": "x"}, ToolContext(workspace=Path(".")))
    assert res.ok is False and "falha" in res.output.lower()


# ------------------------------------------------------------------ CLI: okami skill search / browse
def test_cli_skill_search_lists_table(monkeypatch):
    _stub_registry(monkeypatch, [_cand("gmail-access", description="Acessa Gmail via OAuth")])
    from typer.testing import CliRunner
    from okami.cli import app
    runner = CliRunner()
    out = runner.invoke(app, ["skill", "search", "gmail"])
    assert out.exit_code == 0 and "gmail-access" in out.output and "anthropics/skills" in out.output


def test_cli_skill_browse_json(monkeypatch):
    _stub_registry(monkeypatch, [_cand("a", description="skill a")])
    from typer.testing import CliRunner
    from okami.cli import app
    runner = CliRunner()
    out = runner.invoke(app, ["skill", "browse", "--json"])
    assert out.exit_code == 0
    import json
    payload = json.loads(out.output)
    assert payload and payload[0]["name"] == "a"


def test_cli_skill_search_empty_results(monkeypatch):
    _stub_registry(monkeypatch, [])
    from typer.testing import CliRunner
    from okami.cli import app
    runner = CliRunner()
    out = runner.invoke(app, ["skill", "search", "nada"])
    assert out.exit_code == 0 and "nenhuma" in out.output.lower()


# ------------------------------------------------------------------ install-from-search reusa a pipeline
def test_cli_skill_search_install_reuses_quarantine_scan_lockfile(tmp_path, monkeypatch):
    _stub_registry(monkeypatch, [_cand("html-to-pdf", source="anthropics/skills", only="html-to-pdf")])

    def fake_fetch(source, dest):
        d = Path(dest) / "repo" / "html-to-pdf"
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(
            "---\nname: html-to-pdf\ndescription: Converte HTML em PDF\n---\n## Como\nuse a lib.\n",
            encoding="utf-8")

    import okami.cli._shared as shared
    monkeypatch.setattr(shared, "_fetch_skill_source", fake_fetch)
    monkeypatch.setattr("okami.home.skills_dir", lambda: tmp_path / "skills")
    monkeypatch.chdir(tmp_path)

    from typer.testing import CliRunner
    from okami.cli import app
    runner = CliRunner()
    out = runner.invoke(app, ["skill", "search", "html", "--install"])
    assert out.exit_code == 0, out.output
    assert (tmp_path / "skills" / "html-to-pdf" / "SKILL.md").exists()
    lock = (tmp_path / "skills-lock.json")
    assert lock.exists() and "html-to-pdf" in lock.read_text(encoding="utf-8")


def test_search_skills_tool_then_install_skill_tool_end_to_end(monkeypatch, tmp_path):
    """Fluxo do agente: search_skills devolve um candidato → install_skill(source, name=only) instala
    pela pipeline JÁ existente (mesma usada por `okami learn`)."""
    _stub_registry(monkeypatch, [_cand("gmail-access", source="anthropics/skills", only="gmail-access")])
    from okami.core.tools.skills_search import SearchSkills
    from okami.core.tools.base import ToolContext
    found = SearchSkills().run({"query": "gmail"}, ToolContext(workspace=tmp_path))
    assert found.ok and "gmail-access" in found.output

    def fake_fetch(source, dest):
        d = Path(dest) / "repo" / "gmail-access"
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(
            "---\nname: gmail-access\ndescription: Acessa Gmail\n---\n## Como\nuse OAuth.\n", encoding="utf-8")

    import okami.cli._shared as shared
    monkeypatch.setattr(shared, "_fetch_skill_source", fake_fetch)
    from okami.core.tools.agentic import InstallSkill
    ctx = ToolContext(workspace=tmp_path, skills={}, skills_dir=str(tmp_path / "skills"))
    res = InstallSkill().run({"source": "anthropics/skills", "name": "gmail-access"}, ctx)
    assert res.ok and "gmail-access" in ctx.skills
