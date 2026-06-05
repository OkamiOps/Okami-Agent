"""Testes do runtime/router de skills (§4.2)."""

from __future__ import annotations

from pathlib import Path

from okami import skills as skillmod

REPO_SKILLS = Path(__file__).resolve().parent.parent / "skills"


def _write(tmp_path, name, triggers, body="corpo da skill"):
    d = tmp_path / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: d\ntriggers: [{', '.join(triggers)}]\n---\n{body}",
        encoding="utf-8",
    )


def test_parse_and_load(tmp_path):
    _write(tmp_path, "frontend-shadcn", ["shadcn", "ui"])
    sks = skillmod.load_skills(tmp_path)
    assert len(sks) == 1
    assert sks[0].name == "frontend-shadcn"
    assert "shadcn" in sks[0].triggers


def _write_rich(tmp_path, name, *, description, triggers=(), intent_examples=()):
    d = tmp_path / name
    d.mkdir(parents=True)
    import yaml as _yaml
    meta = {"name": name, "description": description,
            "triggers": list(triggers), "intent_examples": list(intent_examples)}
    (d / "SKILL.md").write_text("---\n" + _yaml.safe_dump(meta, allow_unicode=True) + "---\ncorpo",
                                encoding="utf-8")


def test_parse_intent_examples(tmp_path):
    _write_rich(tmp_path, "x", description="d", triggers=["t1"], intent_examples=["faça de novo a avaliação"])
    sk = skillmod.load_skills(tmp_path)[0]
    assert sk.intent_examples == ["faça de novo a avaliação"]


def test_rank_skills_by_intent_not_literal(tmp_path):
    # a DOR: pedido NÃO usa a palavra do nome ("validar"), mas a skill certa tem que subir por significado.
    _write_rich(tmp_path, "validar-okami-agent",
                description="Avaliar mudanças no Okami-Agent depois de commit/alterações grandes",
                triggers=["analisa o okami-agent", "vê se melhorou", "compara de novo"],
                intent_examples=["amor faz de novo a avaliação do okami-agent"])
    _write_rich(tmp_path, "humanizer", description="deixa o texto natural e humano",
                triggers=["humanizar texto"])
    skills = skillmod.load_skills(tmp_path)
    ranked = skillmod.rank_skills("amor, analisa de novo a pasta do okami agent", skills)  # sem embedder → HRR local
    assert ranked[0][0].name == "validar-okami-agent"
    assert ranked[0][1] > ranked[-1][1] > -1            # discriminou
    assert ranked[0][1] > 0


def test_rank_is_offline_deterministic(tmp_path):
    _write_rich(tmp_path, "a", description="rodar testes e lint do projeto", triggers=["roda os testes"])
    _write_rich(tmp_path, "b", description="escrever post de blog", triggers=["escreve um texto"])
    sks = skillmod.load_skills(tmp_path)
    r1 = skillmod.rank_skills("roda a suíte de testes", sks)
    r2 = skillmod.rank_skills("roda a suíte de testes", sks)
    assert [s.name for s, _ in r1] == [s.name for s, _ in r2]   # HRR é determinístico
    assert r1[0][0].name == "a"


def test_catalog_ranks_and_marks_provavel(tmp_path):
    _write_rich(tmp_path, "validar-okami-agent",
                description="Avaliar mudanças no Okami-Agent",
                triggers=["analisa o okami-agent", "vê se melhorou"])
    _write_rich(tmp_path, "humanizer", description="deixa o texto humano", triggers=["humanizar"])
    cat = skillmod.catalog(skillmod.load_skills(tmp_path), goal="analisa de novo o okami agent")
    assert "use_skill" in cat and "relevância" in cat
    linhas = [ln for ln in cat.splitlines() if ln.startswith("- ")]
    assert linhas[0].startswith("- validar-okami-agent") and "⭐" in linhas[0]   # mais provável no topo, marcada
    assert cat.index("validar-okami-agent") < cat.index("humanizer")            # ranqueado acima


def test_catalog_without_goal_stays_flat(tmp_path):
    _write_rich(tmp_path, "a", description="d", triggers=["x"])
    cat = skillmod.catalog(skillmod.load_skills(tmp_path))   # sem goal → comportamento antigo, sem ⭐
    assert "use_skill" in cat and "⭐" not in cat


def test_route_forces_frontend_skill_by_contract(tmp_path):
    _write(tmp_path, "frontend-shadcn", ["shadcn"])
    sks = skillmod.load_skills(tmp_path)
    contracts = {"ui": {"library": "shadcn"}}
    routed = skillmod.route("Crie um dashboard de vendas", contracts, sks)
    assert [s.name for s in routed] == ["frontend-shadcn"]


def test_route_ignores_when_not_frontend(tmp_path):
    _write(tmp_path, "frontend-shadcn", ["shadcn"])
    sks = skillmod.load_skills(tmp_path)
    routed = skillmod.route("Some os números 2 e 3", {"ui": {"library": "shadcn"}}, sks)
    assert routed == []


def test_repo_ships_frontend_skills():
    names = {s.name for s in skillmod.load_skills(REPO_SKILLS)}
    assert {"frontend-shadcn", "frontend-heroui"} <= names


def test_repo_ships_bundled_skills():
    names = {s.name for s in skillmod.load_skills(REPO_SKILLS)}
    assert {"humanizer", "proactive-agent", "tdd", "writing-plans", "communication-131"} <= names


def test_catalog_lists_and_excludes(tmp_path):
    _write(tmp_path, "frontend-shadcn", ["shadcn"])
    _write(tmp_path, "humanizer", ["humanizar"])
    cat = skillmod.catalog(skillmod.load_skills(tmp_path), exclude={"frontend-shadcn"})
    assert "humanizer:" in cat and "use_skill" in cat
    assert "frontend-shadcn:" not in cat


def test_use_skill_tool_loads_body():
    from pathlib import Path

    from okami.core.tools import ToolContext, UseSkill

    ctx = ToolContext(workspace=Path("."), skills={"humanizer": "corpo da skill humanizer"})
    ok = UseSkill().run({"name": "humanizer"}, ctx)
    assert ok.ok and "corpo da skill humanizer" in ok.output
    assert not UseSkill().run({"name": "inexistente"}, ctx).ok


def test_render_block_marks_mandatory(tmp_path):
    _write(tmp_path, "frontend-shadcn", ["shadcn"])
    block = skillmod.render_block(skillmod.load_skills(tmp_path))
    assert "OBRIGAT" in block.upper() and "frontend-shadcn" in block
