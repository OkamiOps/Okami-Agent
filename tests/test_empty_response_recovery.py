"""Reduz ERRO com modelo de reasoning (sweep #8): minimax/DeepSeek-R1 às vezes põem TUDO no reasoning_content
e devolvem content='' sem tool_calls. Persistir {role:assistant, content:''} envenena o histórico → próximo
request 400 ('assistant precisa de content OU tool_calls'). O loop agora NÃO persiste zumbi, é bounded e
recupera."""
from __future__ import annotations

from okami.core import Harness, Task, TaskState
from okami.core.tools.registry import default_registry
from okami.llm.usage import Completion


def _has_zombie(messages):
    return any(m.get("role") == "assistant" and not (m.get("content") or "").strip()
               and not m.get("tool_calls") for m in messages)


def test_empty_response_never_persists_zombie_and_is_bounded(tmp_path):
    calls = {"n": 0}

    def gen(messages, schema=None):
        calls["n"] += 1
        return Completion(text="", tool_calls=[])         # SEMPRE vazio (sem content, sem tool_calls)

    h = Harness(gen, Task(goal="faça algo"), tmp_path, registry=default_registry())
    t = h.run()
    assert not _has_zombie(h.messages)                     # nunca poluiu o histórico c/ assistant vazio
    assert t.state != TaskState.COMPLETE                   # não fingiu sucesso com resposta vazia
    assert calls["n"] < 12                                 # bounded: não spina até o backstop de passos


def test_empty_response_recovers_when_model_comes_back(tmp_path):
    calls = {"n": 0}
    seq = iter([
        Completion(text="", tool_calls=[]),                                    # 1 vazia
        Completion(text="Oi! Tudo bem por aqui, e com você?", tool_calls=[]),  # depois responde (conversa)
    ])

    def gen(messages, schema=None):
        calls["n"] += 1
        return next(seq)

    h = Harness(gen, Task(goal="oi, tudo bem?"), tmp_path, registry=default_registry())
    t = h.run()
    assert calls["n"] == 2                                  # recuperou: 2ª geração foi processada
    assert t.state == TaskState.COMPLETE                   # 1 vazia não derruba o turno
    assert not _has_zombie(h.messages)
