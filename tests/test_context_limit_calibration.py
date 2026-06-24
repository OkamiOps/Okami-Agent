"""Paridade Hermes (multi-vendor): extrair o limite de contexto que o PROVIDER reporta no erro de overflow e
recalibrar a compactação. Crítico p/ Ollama/LMStudio — o contexto carregado quase nunca bate o catálogo
estático, então sem isso o agente estoura, compacta cego e estoura de novo."""
from __future__ import annotations

from okami.core import Harness, Task
from okami.core.errors import classify_provider
from okami.core.tools.registry import default_registry
from okami.llm.errors import _extract_ctx_limit
from okami.llm.usage import Completion


# ---------------------------------------------------------------- extração (multi-formato de vendor)
def test_extract_openai_style():
    assert _extract_ctx_limit("This model's maximum context length is 8192 tokens, you requested 9000") == 8192


def test_extract_window_style():
    assert _extract_ctx_limit("context window of 32768 exceeded by the request") == 32768


def test_extract_tokens_first_style():
    assert _extract_ctx_limit("requested 70000 tokens but the maximum context is 65536") in (70000, 65536)


def test_extract_none_when_no_number():
    assert _extract_ctx_limit("the conversation is too long, please shorten it") is None


def test_classify_carries_context_limit():
    f = classify_provider(Exception("maximum context length is 4096 tokens"))
    assert f.context_limit == 4096


# ---------------------------------------------------------------- recalibra o teto no loop
def test_overflow_recalibrates_budget(tmp_path):
    seq = iter([
        Exception("This model's maximum context length is 8192 tokens, however you requested 9001"),
        Completion(text="oi! tudo certo por aqui.", tool_calls=[]),   # depois responde (conversa)
    ])

    def gen(messages, schema=None):
        x = next(seq)
        if isinstance(x, Exception):
            raise x
        return x

    h = Harness(gen, Task(goal="oi"), tmp_path, registry=default_registry())
    h.budget.max_context_chars = 400000
    h.run()
    assert h.budget.max_context_chars <= 8192 * 4     # recalibrou pro limite REAL reportado (~80%)
    assert h.budget.max_context_chars < 400000
