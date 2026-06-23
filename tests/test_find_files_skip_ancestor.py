"""find_files CEGO em produção: o agente roda sob ~/.okami/agents/<nome>/, e '.okami' está no _SKIP.
Como o skip era testado contra `p.parts` (caminho ABSOLUTO do rglob), o ancestral '.okami' casava e
TODO arquivo era pulado → find_files sempre devolvia '(nada casou)', mesmo com o arquivo existindo
(queixa do dono: 'find_files não acha SKILL.md mesmo com arquivos existentes')."""
from __future__ import annotations

from types import SimpleNamespace

from okami.core.tools.files import FindFiles


def test_find_files_not_blinded_by_skiplisted_ancestor(tmp_path):
    ws = tmp_path / ".okami" / "agents" / "minerva"          # workspace SOB um nome skip-listed (caso real)
    (ws / "skills" / "gog").mkdir(parents=True)
    (ws / "skills" / "gog" / "SKILL.md").write_text("x", encoding="utf-8")
    res = FindFiles().run({"query": "SKILL.md"}, SimpleNamespace(workspace=ws))
    # o caminho RELATIVO real tem que aparecer (a msg de "(nada casou…)" também ecoa o query — não basta)
    assert res.ok and "skills/gog/SKILL.md" in res.output and "nada casou" not in res.output


def test_find_files_still_skips_junk_inside_workspace(tmp_path):
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "SKILL.md").write_text("x", encoding="utf-8")
    (tmp_path / "SKILL.md").write_text("y", encoding="utf-8")
    res = FindFiles().run({"query": "SKILL.md"}, SimpleNamespace(workspace=tmp_path))
    assert "SKILL.md" in res.output and "node_modules" not in res.output   # junk DENTRO do ws ainda pula
