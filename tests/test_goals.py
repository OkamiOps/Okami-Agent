"""/goal + /subgoal (pesquisa #5 item 41, paridade Hermes): objetivo PERSISTENTE por chat com
orçamento de turnos, juiz auxiliar FAIL-OPEN (LLM indisponível → nada quebra) e gate determinístico
de EVIDÊNCIA concreta p/ fechar subgoal (juiz que diz só "feito" não fecha nada).
"""
from __future__ import annotations

import json

from okami.gateway.goals import GoalStore, concrete_evidence, judge_turn


# ------------------------------------------------------------------ store persistente
def test_goal_persists_across_instances(tmp_path):
    GoalStore(tmp_path).set_goal("7", "entregar a release 1.0", turn_budget=10)
    g = GoalStore(tmp_path).get("7")
    assert g and g["goal"] == "entregar a release 1.0" and g["turn_budget"] == 10
    assert g["turns_used"] == 0 and not g["done"]


def test_subgoals_and_completion(tmp_path):
    st = GoalStore(tmp_path)
    st.set_goal("7", "release")
    st.add_subgoal("7", "rodar a suíte de testes")
    st.add_subgoal("7", "atualizar o changelog")
    st.complete_subgoal("7", 0, "pytest: 1485 passed em 20s")
    g = st.get("7")
    assert g["subgoals"][0]["done"] and "1485" in g["subgoals"][0]["evidence"]
    assert not g["subgoals"][1]["done"]


def test_bump_turn_and_clear(tmp_path):
    st = GoalStore(tmp_path)
    st.set_goal("7", "x", turn_budget=2)
    assert st.bump_turn("7")["turns_used"] == 1
    assert st.bump_turn("7")["turns_used"] == 2
    st.clear("7")
    assert st.get("7") is None


def test_context_block_lists_open_subgoals(tmp_path):
    st = GoalStore(tmp_path)
    assert st.context_block("7") == ""                   # sem objetivo → nada injetado
    st.set_goal("7", "entregar a release", turn_budget=20)
    st.add_subgoal("7", "rodar testes")
    st.add_subgoal("7", "changelog")
    st.complete_subgoal("7", 0, "pytest 1485 passed na CI de hoje")
    block = st.context_block("7")
    assert "entregar a release" in block
    assert "changelog" in block and "rodar testes" not in block.split("✅")[0] or "✅" in block
    assert "OBJETIVO" in block.upper()


def test_exhausted_budget_suspends_injection(tmp_path):
    st = GoalStore(tmp_path)
    st.set_goal("7", "x", turn_budget=1)
    st.bump_turn("7")
    assert st.get("7")["turns_used"] >= st.get("7")["turn_budget"]
    assert st.context_block("7") == ""                   # estourou → para de injetar (não vira loop eterno)


# ------------------------------------------------------------------ gate de evidência
def test_concrete_evidence_rejects_generic():
    assert not concrete_evidence("feito", "rodar testes")
    assert not concrete_evidence("ok", "rodar testes")
    assert not concrete_evidence("rodar testes", "rodar testes")   # repetir o subgoal ≠ evidência
    assert not concrete_evidence("", "rodar testes")


def test_concrete_evidence_accepts_specific():
    assert concrete_evidence("pytest rodou: 1485 passed, 0 failed (20.1s)", "rodar testes")


# ------------------------------------------------------------------ juiz fail-open
def _judge_payload(items, goal_done=False):
    return json.dumps({"completed": items, "goal_done": goal_done})


def test_judge_completes_with_concrete_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr("okami.llm.aux.aux_complete", lambda cfg, task, msgs, **kw:
                        _judge_payload([{"index": 0, "evidence": "saída real: 12 passed em 3.2s"}]))
    st = GoalStore(tmp_path)
    st.set_goal("7", "release")
    st.add_subgoal("7", "rodar testes")
    out = judge_turn(None, st, "7", "rodei a suíte: 12 passed")
    assert out["completed"] == [0]
    assert st.get("7")["subgoals"][0]["done"]


def test_judge_rejects_generic_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr("okami.llm.aux.aux_complete", lambda cfg, task, msgs, **kw:
                        _judge_payload([{"index": 0, "evidence": "feito"}]))
    st = GoalStore(tmp_path)
    st.set_goal("7", "release")
    st.add_subgoal("7", "rodar testes")
    out = judge_turn(None, st, "7", "fiz")
    assert out["completed"] == []                        # evidência rasa → NÃO fecha
    assert not st.get("7")["subgoals"][0]["done"]


def test_judge_fail_open_on_garbage(monkeypatch, tmp_path):
    monkeypatch.setattr("okami.llm.aux.aux_complete",
                        lambda cfg, task, msgs, **kw: (_ for _ in ()).throw(RuntimeError("sem modelo")))
    st = GoalStore(tmp_path)
    st.set_goal("7", "release")
    out = judge_turn(None, st, "7", "qualquer coisa")
    assert out == {"completed": [], "goal_done": False}  # juiz indisponível → nada quebra


# ------------------------------------------------------------------ comandos no registry
def test_goal_commands_registered():
    from okami import commands as cmds
    assert cmds.resolve("/goal") is not None
    assert cmds.resolve("/subgoal") is not None


# ------------------------------------------------------------------ integração no gateway
def test_endpoint_goal_flow(tmp_path):
    from tests.test_gateway import FakeChannel, _ok_task
    from okami.gateway import AgentEndpoint
    seen_ctx = []

    def runner(cfg, ws, goal, *, extra_context="", **kw):
        seen_ctx.append(extra_context)
        return _ok_task(goal)

    ch = FakeChannel()
    ep = AgentEndpoint("dev", cfg=None, ws=str(tmp_path), channel=ch, run_task=runner,
                       spawn=lambda fn: fn())
    ep.handle("7", "/goal entregar a release 1.0")
    assert any("release 1.0" in t for _, t in ch.sent)
    ep.handle("7", "/subgoal rodar a suíte")
    ep.handle("7", "bora trabalhar")                     # turno normal → objetivo entra no contexto
    assert any("entregar a release 1.0" in c for c in seen_ctx)
    ep.handle("7", "/goal")                              # status
    assert any("rodar a suíte" in t for _, t in ch.sent)
    ep.handle("7", "/goal clear")
    assert ep._goals.get("7") is None
