"""Prompts de CONTINUAÇÃO distintos por tipo de corte (pesquisa #5 item 3, paridade Hermes).

Casos diferentes pedem instruções diferentes:
- prosa cortada por tamanho → "continue de onde parou" (já existia);
- TOOL-CALL cortada por tamanho → continuar no meio do JSON é loteria; o certo é "NÃO repita igual:
  re-emita a ação com args MENORES (quebre em pedaços)";
- geração morreu no meio (rede/provider) e vamos re-gerar → "retome do estado atual, NÃO recomece".
"""
from __future__ import annotations

import okami.core.harness.loop as loop_mod
from okami.core import Task
from okami.core.harness import Harness
from okami.llm.usage import Completion


def test_truncated_prose_keeps_continue_prompt(tmp_path):
    seen = []

    def gen(messages, schema):
        if not seen:
            seen.append("x")
            return Completion(text="relatório longo sem ação nenhuma aqui", finish_reason="length")
        seen.append(messages[-1]["content"])
        return Completion(text='{"tool": "respond", "args": {"message": "fim"}}')

    h = Harness(generate=gen, task=Task(goal="oi"), workspace=tmp_path)
    res = h.run()
    assert res.state.name == "COMPLETE"
    nudge = seen[1]
    assert "Continue EXATAMENTE de onde parou" in nudge


def test_truncated_toolcall_asks_smaller_reemit_not_continuation(tmp_path):
    seen = []

    def gen(messages, schema):
        if not seen:
            seen.append("x")
            return Completion(
                text='vou escrever\n```json\n{"tool": "write_file", "args": {"path": "a.txt", "content": "aaaa',
                finish_reason="length")
        seen.append(messages[-1]["content"])
        return Completion(text='{"tool": "respond", "args": {"message": "fim"}}')

    h = Harness(generate=gen, task=Task(goal="oi"), workspace=tmp_path)
    res = h.run()
    assert res.state.name == "COMPLETE"
    nudge = seen[1]
    assert "NÃO repita" in nudge                     # não é o prompt de "continue de onde parou"
    assert "menor" in nudge.lower() or "pedaço" in nudge.lower()
    assert "Continue EXATAMENTE" not in nudge


def test_truncated_toolcall_discards_partial_not_concatenated(tmp_path):
    # a parte truncada NÃO pode ser concatenada com a re-emissão (viraria JSON duplicado/quebrado)
    calls = {"n": 0}

    def gen(messages, schema):
        calls["n"] += 1
        if calls["n"] == 1:
            return Completion(text='```json\n{"tool": "respond", "args": {"message": "aaa',
                              finish_reason="length")
        return Completion(text='{"tool": "respond", "args": {"message": "resposta inteira"}}')

    h = Harness(generate=gen, task=Task(goal="oi"), workspace=tmp_path)
    res = h.run()
    assert res.state.name == "COMPLETE"
    assert res.result == "resposta inteira"          # sem lixo da parte truncada


def test_network_death_retry_says_resume_not_restart(tmp_path, monkeypatch):
    calls = {"n": 0}
    seen = []

    def gen(messages, schema):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("connection reset by peer")   # transporte caiu no meio
        seen.append(messages[-1]["content"])
        return '{"tool": "task_complete", "args": {"summary": "ok"}}'

    monkeypatch.setattr(loop_mod._compaction, "compact", lambda m, mem, **k: ([m[0]], 0))
    monkeypatch.setattr(loop_mod._compaction, "estimate_chars",
                        lambda m: 100 if len(m) <= 1 else 5000)
    h = Harness(generate=gen, task=Task(goal="oi"), workspace=tmp_path)
    res = h.run()
    assert res.state.name == "COMPLETE"
    assert "recome" in seen[0].lower()               # "NÃO recomece do zero" no contexto re-gerado
