"""Qualidade da auto-destilação de skills — LLM-ou-nada + gate determinístico.

Bug real (11 skills-lixo em ~/.okami/skills): o destilador mecânico colava a FRASE CRUA
do usuário como nome/descrição ("tu-fez-cagada", "sou-marcos-santos") e a conversa como
corpo ("Pronto, gato."). Hermes: skill é PROCEDIMENTO generalizável escrito por LLM com
julgamento "vale salvar?" — sem LLM, melhor NÃO criar skill do que criar lixo.
"""
from __future__ import annotations

import json

from okami import learning
from okami.config import build_config
from okami.core import Step, Task, TaskState

GOAL = ("mas tu fez cagada voce criou só a pasta 00 - OKAMI e eu queria outras pastas "
        "no mesmo nivel voce só jogou as coisas pra dentro de uma pasta unica")


def _done_task(goal=GOAL):
    t = Task(goal=goal)
    t.state, t.result = TaskState.COMPLETE, "Pronto, gato. Agora ficou no nível certo."
    tools = ["list_dir", "move_path", "move_path", "make_dir", "make_dir"]
    t.steps = [Step(i, tl, {}, "", True) for i, tl in enumerate(tools)]
    return t


def _cfg():
    return build_config({"default_provider": "p", "providers": {"p": {"model": "m", "api_key": "k"}}})


GOOD = {"worth": True, "name": "organizar-pastas-nivel",
        "description": "Use quando a pessoa pedir para reorganizar uma árvore de pastas em "
                       "categorias no mesmo nível (não aninhadas).",
        "intent_examples": ["reorganiza essas pastas no mesmo nível",
                            "separa em categorias irmãs, não dentro de uma só"],
        "body": "## Quando usar\nReorganização de árvore de pastas em categorias irmãs.\n\n"
                "## Procedimento\n1. `list_dir` na raiz p/ mapear o estado real.\n"
                "2. `make_dir` p/ cada categoria NO MESMO NÍVEL da raiz.\n"
                "3. `move_path` item a item; confira com `list_dir` no fim.\n\n"
                "## Cuidados\n- Confirmar o NÍVEL desejado antes de mover (irmãs vs aninhadas).\n"
                "- Nunca sobrescrever; em conflito de nome, perguntar.\n"}


# ── LLM-ou-nada: o fallback determinístico NÃO escreve mais skill ───────────

def test_no_llm_means_no_skill(tmp_path):
    assert learning.maybe_write_skill(_done_task(), skills_dir=str(tmp_path), cfg=None) is None
    assert not list(tmp_path.glob("*/SKILL.md"))


def test_llm_failure_means_no_skill(tmp_path, monkeypatch):
    from okami.llm import providers as prov
    monkeypatch.setattr(prov, "complete_messages",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("503")))
    assert learning.maybe_write_skill(_done_task(), skills_dir=str(tmp_path), cfg=_cfg()) is None
    assert not list(tmp_path.glob("*/SKILL.md"))


# ── julgamento "vale salvar?" — o LLM pode (e deve) dizer NÃO ───────────────

def test_llm_worth_false_means_no_skill(tmp_path, monkeypatch):
    from okami.llm import providers as prov
    monkeypatch.setattr(prov, "complete_messages",
                        lambda *a, **k: json.dumps({**GOOD, "worth": False}))
    assert learning.maybe_write_skill(_done_task(), skills_dir=str(tmp_path), cfg=_cfg()) is None


# ── gate determinístico barra lixo mesmo se o LLM escorregar ────────────────

def test_gate_rejects_description_equal_to_goal(tmp_path, monkeypatch):
    from okami.llm import providers as prov
    bad = {**GOOD, "description": GOAL[:160]}                   # descrição = frase crua
    monkeypatch.setattr(prov, "complete_messages", lambda *a, **k: json.dumps(bad))
    assert learning.maybe_write_skill(_done_task(), skills_dir=str(tmp_path), cfg=_cfg()) is None


def test_gate_rejects_body_with_verbatim_conversation(tmp_path, monkeypatch):
    from okami.llm import providers as prov
    bad = {**GOOD, "body": "## Quando usar\n" + GOAL + "\n## Procedimento\n1. x\n"}
    monkeypatch.setattr(prov, "complete_messages", lambda *a, **k: json.dumps(bad))
    assert learning.maybe_write_skill(_done_task(), skills_dir=str(tmp_path), cfg=_cfg()) is None


def test_gate_rejects_skimpy_body(tmp_path, monkeypatch):
    from okami.llm import providers as prov
    bad = {**GOOD, "body": "list_dir → move_path → make_dir"}   # setas de tools não são procedimento
    monkeypatch.setattr(prov, "complete_messages", lambda *a, **k: json.dumps(bad))
    assert learning.maybe_write_skill(_done_task(), skills_dir=str(tmp_path), cfg=_cfg()) is None


def test_gate_rejects_conversational_name(tmp_path, monkeypatch):
    from okami.llm import providers as prov
    bad = {**GOOD, "name": "tu-fez-cagada"}                     # nome saído da frase do usuário
    monkeypatch.setattr(prov, "complete_messages", lambda *a, **k: json.dumps(bad))
    assert learning.maybe_write_skill(_done_task(), skills_dir=str(tmp_path), cfg=_cfg()) is None


# ── caminho feliz: skill BOA é escrita com frontmatter limpo ────────────────

def test_good_skill_written_with_clean_frontmatter(tmp_path, monkeypatch):
    from okami.llm import providers as prov
    monkeypatch.setattr(prov, "complete_messages", lambda *a, **k: json.dumps(GOOD))
    name = learning.maybe_write_skill(_done_task(), skills_dir=str(tmp_path), cfg=_cfg())
    assert name == "organizar-pastas-nivel"
    from okami import skills as skillmod
    sk = skillmod.parse_skill(tmp_path / name / "SKILL.md")
    assert sk.meta["description"].startswith("Use quando")       # descrição do LLM, não a frase crua
    assert GOAL[:40] not in sk.meta["description"]
    assert len(sk.intent_examples) >= 2                          # exemplos GENERALIZADOS do LLM
    assert sk.meta.get("origin") == "auto-distilled"
    assert "## Procedimento" in sk.body


def test_validate_distilled_unit():
    v = learning.validate_distilled
    assert v(GOOD, GOAL) is None                                 # boa → sem objeção
    assert v({**GOOD, "name": "x"}, GOAL)                        # nome de 1 palavra curta
    assert v({**GOOD, "name": "Tu Fez"}, GOAL)                   # não-kebab
    assert v({**GOOD, "description": ""}, GOAL)
    assert v({**GOOD, "body": ""}, GOAL)
