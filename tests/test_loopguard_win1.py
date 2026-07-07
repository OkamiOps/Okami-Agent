"""WIN1 (Hermes-parity audit): warn-before-block no loop guard + agregação de falha unificada.

Antes: repetir a MESMA ação bloqueava seco na 3ª tentativa (max_repeat=3). Agora avisa na 2ª repetição
(warn_repeat=2) — a tool AINDA roda — e só bloqueia de vez perto da 5ª (max_repeat=5). Além disso, nome
de tool ALUCINADO e args FALTANDO eram contadores DISJUNTOS: um modelo que ALTERNA entre os dois nunca
deixava nenhum isolado bater o próprio teto sozinho. Agora somam no MESMO contador unificado
(_consecutive_action_failures / Budget.max_tool_failures)."""
from __future__ import annotations

import json

from okami.core import Budget, Harness, Task, TaskState


def J(tool: str, **args) -> str:
    return "```json\n" + json.dumps({"tool": tool, "args": args}) + "\n```"


class Script:
    """Provider falso: devolve saídas na ordem; depois um default."""

    def __init__(self, outputs, default=None):
        self.outputs = list(outputs)
        self.default = default

    def __call__(self, messages, schema=None):
        return self.outputs.pop(0) if self.outputs else self.default


# ------------------------------------------------------------------ warn-before-block
def test_warn_emitted_at_second_repeat_but_tool_still_runs(tmp_path):
    """2ª repetição idêntica → evento loop_warn (não loop) e a tool RODA de verdade (não é rejeitada)."""
    s = Script([], default=J("read_file", path="naoexiste.txt"))
    events = []
    t = Task(goal="x")
    Harness(s, t, tmp_path, on_event=events.append).run()

    warns = [e for e in events if e["kind"] == "loop_warn"]
    assert warns, "esperava um evento loop_warn na 2ª repetição"
    assert warns[0]["repeats"] == 2                        # avisou exatamente na 2ª vez, não antes
    assert len(warns) == 1                                 # só avisa 1x por fingerprint (não spamma)

    # a tool rodou de verdade pelo menos nas 2 primeiras vezes (inclusive a avisada) — não foi rejeitada
    tool_steps = [e for e in events if e["kind"] == "step" and e["tool"] == "read_file"]
    assert len(tool_steps) >= 2


def test_block_only_arrives_near_new_higher_threshold(tmp_path):
    """O bloqueio de vez (evento 'loop') só chega perto do NOVO teto (max_repeat=5), não mais na 3ª."""
    s = Script([], default=J("read_file", path="naoexiste.txt"))
    events = []
    t = Task(goal="x")
    r = Harness(s, t, tmp_path, on_event=events.append).run()

    assert r.state == TaskState.FAILED
    loops = [e for e in events if e["kind"] == "loop"]
    assert loops, "esperava bloqueio de loop eventualmente"
    assert loops[0]["repeats"] >= 5                         # não bloqueia mais na 3ª tentativa (era o antigo)

    # a tool foi de fato DISPACHADA várias vezes antes do bloqueio (warn não é bloqueio)
    tool_steps = [e for e in events if e["kind"] == "step" and e["tool"] == "read_file"]
    assert len(tool_steps) >= 4                             # 1ª..4ª rodaram; só a 5ª foi barrada


def test_default_budget_matches_new_contract():
    b = Budget()
    assert b.warn_repeat == 2
    assert b.max_repeat == 5                                # era 3 (hard-block seco); agora dá mais corda


# ------------------------------------------------------------------ agregação unificada (fecha o buraco)
def test_alternating_bad_name_and_missing_arg_trips_aggregate_counter(tmp_path):
    """Modelo ALTERNA entre nome de tool ALUCINADO e nome válido SEM arg obrigatório, pro mesmo alvo.
    Nem _consecutive_violations nem _consecutive_arg_fails isolados bateriam o próprio teto rápido — o
    contador UNIFICADO (max_tool_failures) fecha esse buraco."""
    outputs = [
        J("zzz_totally_fake_tool", path="x"),                # nome ALUCINADO (sem reparo por difflib)
        J("write_file", content="sem o path obrigatorio"),    # nome válido, mas SEM 'path' (obrigatório)
        J("zzz_totally_fake_tool", path="x"),                 # alterna de novo
        J("write_file", content="sem o path obrigatorio"),    # e de novo — a 4ª falha agregada
    ]
    events = []
    t = Task(goal="x")
    # tetos INDIVIDUAIS bem folgados (nunca disparam sozinhos) — só o agregado (max_tool_failures) deve pegar.
    b = Budget(max_consecutive_violations=100, max_tool_failures=3, max_loop_breaks=100)
    r = Harness(Script(outputs), t, tmp_path, budget=b, on_event=events.append).run()

    assert r.state == TaskState.FAILED
    violations = [e for e in events if e["kind"] == "violation"]
    arg_fails = [e for e in events if e["kind"] == "malformed_args"]
    # nenhum dos DOIS contadores isolados chegou perto do próprio teto (100) — a falha veio do agregado
    assert violations and violations[-1]["n"] < 100
    assert arg_fails and arg_fails[-1]["n"] < 100
    # nenhuma das 4 chamadas foi um DISPATCH de verdade (não há passo real registrado)
    assert not any(e["kind"] == "step" for e in events)


def test_real_dispatch_resets_the_aggregate_counter(tmp_path):
    """Uma tool que DISPACHA de verdade zera o contador agregado — não é um teto vitalício."""
    outputs = [
        J("zzz_totally_fake_tool", path="x"),                 # falha #1 (agregado=1)
        J("write_file", path="ok.txt", content="oi"),          # DISPATCH de verdade → zera o agregado
        J("zzz_totally_fake_tool", path="x"),                  # falha #1 de novo (não #2 — foi zerado)
        J("task_complete", summary="ok"),
        J("task_complete", summary="ok"),                      # 2ª tentativa (WIN2 pode nudgear a 1ª)
    ]
    events = []
    t = Task(goal="x")
    b = Budget(max_consecutive_violations=100, max_tool_failures=2, max_loop_breaks=100)
    r = Harness(Script(outputs), t, tmp_path, budget=b, on_event=events.append).run()
    # com o reset, uma ÚNICA falha isolada depois do dispatch NÃO deveria por si só derrubar a tarefa
    assert r.state == TaskState.COMPLETE
    assert (tmp_path / "ok.txt").exists()
