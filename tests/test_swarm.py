"""#12 Onda C: Kanban swarm — topologia workers→verificador→sintetizador (port Hermes kanban_swarm).

Sem 2º scheduler: monta o grafo (root + workers paralelos + verifier + synth) e o blackboard (JSON).
Aproveita a delegação/spawn existente p/ executar. Aqui testa o PLAN + blackboard."""
from __future__ import annotations


def test_build_swarm_plan_topology():
    from okami.automation.swarm import build_swarm_plan
    plan = build_swarm_plan("pesquisar X a fundo", [
        {"title": "entrevistas", "body": "levante necessidades"},
        {"title": "docs", "body": "leia a documentação"},
    ])
    assert plan["goal"] == "pesquisar X a fundo"
    assert len(plan["workers"]) == 2
    assert plan["verifier"]["prompt"] and plan["synthesizer"]["prompt"]
    # cada worker tem prompt com o protocolo de blackboard
    assert all("blackboard" in w["prompt"].lower() for w in plan["workers"])


def test_swarm_requires_goal_and_workers():
    import pytest
    from okami.automation.swarm import build_swarm_plan
    with pytest.raises(ValueError):
        build_swarm_plan("", [{"title": "x", "body": "y"}])
    with pytest.raises(ValueError):
        build_swarm_plan("meta", [])


def test_blackboard_roundtrip(tmp_path):
    from okami.automation.swarm import blackboard_append, blackboard_read
    bb = tmp_path / "swarm.json"
    blackboard_append(bb, "worker:docs", {"finding": "achei A"})
    blackboard_append(bb, "worker:entrevistas", {"finding": "achei B"})
    entries = blackboard_read(bb)
    assert len(entries) == 2
    assert entries[0]["author"] == "worker:docs" and entries[0]["data"]["finding"] == "achei A"


def test_blackboard_read_missing_is_empty(tmp_path):
    from okami.automation.swarm import blackboard_read
    assert blackboard_read(tmp_path / "nao-existe.json") == []
