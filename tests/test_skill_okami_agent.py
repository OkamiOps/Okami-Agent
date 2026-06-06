"""A skill `okami-agent` — auto-referência das capacidades do agente.

Trava o contrato dela: parseia, escaneia LIMPO (senão o runner a DESCARTA em runtime, §runner.py),
SOBE na busca por intenção p/ pedidos sobre o próprio Okami e documenta a superfície real (protocolo
de ação, critérios de saída, providers). É a skill que o agente carrega p/ saber o que consegue fazer.
"""

from __future__ import annotations

from pathlib import Path

from okami.skills import load_skills, parse_skill, rank_skills
from okami.skills.skill_security import scan_path

REPO_SKILLS = Path(__file__).resolve().parent.parent / "skills"
OKAMI_SKILL = REPO_SKILLS / "okami-agent" / "SKILL.md"


def test_okami_agent_skill_exists_and_parses():
    assert OKAMI_SKILL.exists(), "skills/okami-agent/SKILL.md sumiu"
    sk = parse_skill(OKAMI_SKILL)
    assert sk.name == "okami-agent"
    assert sk.description and len(sk.description) > 30
    assert sk.triggers and "okami" in sk.triggers
    assert sk.intent_examples, "sem intent_examples → não casa por intenção (frase não-literal)"
    assert "okami" in sk.aliases                      # `use_skill okami` também resolve


def test_okami_agent_skill_scans_clean():
    # CRÍTICO: o runner faz `safe = [s for s in skills if not scan_path(...).blocked]`. Se a skill
    # disparar HIGH/CRITICAL ela é DESCARTADA silenciosamente — o agente perde a própria documentação.
    rep = scan_path(OKAMI_SKILL.parent)
    assert not rep.blocked, [str(x) for x in rep.sorted()]


def test_okami_agent_skill_ranks_top_for_meta_queries():
    skills = load_skills(REPO_SKILLS)
    names = {s.name for s in skills}
    assert "okami-agent" in names and "tdd" in names
    for goal in ("quais são as capacidades do okami-agent?",
                 "que ferramentas o okami tem?",
                 "como o okami troca de provider?"):
        scores = {s.name: score for s, score in rank_skills(goal, skills)}
        assert scores["okami-agent"] > scores["tdd"], f"okami-agent não subiu em: {goal}"


def test_okami_agent_skill_documents_real_surface():
    # Guarda anti-drift: a doc precisa cobrir a superfície de fato (não virar casca vazia).
    body = parse_skill(OKAMI_SKILL).body.lower()
    for anchor in ('"tool"', "task_complete", "file_exists:", "use_skill",
                   "run_shell", "/model", "fallback", ".env", "ação-ou-termina"):
        assert anchor in body, f"a skill okami-agent não menciona {anchor!r}"
