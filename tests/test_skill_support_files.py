"""Paridade Hermes (#7): use_skill ENUMERA os arquivos de apoio da skill (references/scripts/…) em vez de
o modelo adivinhar o path no tier-3."""
from __future__ import annotations

from okami.core.tools import UseSkill
from okami.core.tools.base import ToolContext


def _skill(tmp_path):
    sd = tmp_path / "minha-skill"
    (sd / "references").mkdir(parents=True)
    (sd / "scripts").mkdir(parents=True)
    (sd / "SKILL.md").write_text("---\nname: minha-skill\n---\ncorpo", encoding="utf-8")
    (sd / "references" / "guia.md").write_text("ref", encoding="utf-8")
    (sd / "scripts" / "run.js").write_text("// js", encoding="utf-8")
    return sd


def test_use_skill_lists_support_files(tmp_path):
    _skill(tmp_path)
    ctx = ToolContext(workspace=tmp_path, skills={"minha-skill": "corpo do procedimento"},
                      skills_dir=str(tmp_path))
    r = UseSkill().run({"name": "minha-skill"}, ctx)
    assert r.ok
    assert "references/guia.md" in r.output and "scripts/run.js" in r.output   # arquivos LISTADOS
    assert 'path=' in r.output                                                 # ensina a carregar


def test_use_skill_no_support_files_is_clean(tmp_path):
    sd = tmp_path / "vazia"
    sd.mkdir()
    (sd / "SKILL.md").write_text("---\nname: vazia\n---\nx", encoding="utf-8")
    ctx = ToolContext(workspace=tmp_path, skills={"vazia": "corpo"}, skills_dir=str(tmp_path))
    r = UseSkill().run({"name": "vazia"}, ctx)
    assert r.ok and "arquivos de apoio" not in r.output                        # sem apoio → sem ruído
