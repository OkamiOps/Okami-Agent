"""Paridade Hermes (Finding 5): no limite de passos, o modelo ganha UMA última iteração real (grace
call) — muitas tarefas terminam no passo seguinte. Sem grace, corta seco e entrega parcial."""
from __future__ import annotations

from okami.core import Harness, Task, TaskState
from okami.llm.usage import Completion


def _gen_factory(calls):
    def gen(messages, schema=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return Completion(text="", tool_calls=[
                {"id": "r1", "name": "read_file", "arguments": '{"path":"a.txt"}'}])
        if calls["n"] == 2:
            return Completion(text="", tool_calls=[
                {"id": "r2", "name": "read_file", "arguments": '{"path":"b.txt"}'}])
        return Completion(text="", tool_calls=[
            {"id": "d", "name": "task_complete", "arguments": '{"summary":"feito"}'}])
    return gen


def test_grace_step_allows_one_more_action_at_budget(tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "b.txt").write_text("y", encoding="utf-8")
    calls = {"n": 0}
    h = Harness(_gen_factory(calls), Task(goal="leia a e b"), tmp_path)
    h.budget.max_steps = 2                                  # esgota em 2 passos
    t = h.run()
    assert t.state == TaskState.COMPLETE                    # a 3ª geração (grace) fechou a tarefa
    assert calls["n"] == 3                                  # houve UMA geração extra após o budget


def test_grace_step_is_single_use(tmp_path):
    # se a tarefa NÃO fecha na grace, falha (a grace é uma só — não vira loop infinito)
    calls = {"n": 0}

    def gen(messages, schema=None):
        calls["n"] += 1                                    # sempre escreve arquivos diferentes (nunca conclui)
        return Completion(text="", tool_calls=[
            {"id": f"r{calls['n']}", "name": "write_file",
             "arguments": '{"path":"f%d.txt","content":"z"}' % calls["n"]}])

    events = []
    h = Harness(gen, Task(goal="trabalhe sem parar"), tmp_path,
                on_event=lambda e: events.append(e["kind"]))
    h.budget.max_steps = 2
    t = h.run()
    assert t.state != TaskState.COMPLETE                    # não concluiu → falhou
    assert events.count("grace_step") == 1                  # grace é UMA só (não vira loop infinito)
