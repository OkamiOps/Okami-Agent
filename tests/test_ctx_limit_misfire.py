"""Bug ATIVO (minimax, mas o método é multi-vendor): o erro de overflow do minimax diz "context window
exceeds limit (2013)" — onde 2013 é o EXCESSO (delta), NÃO o teto. _extract_ctx_limit lia 2013 como limite
e despencava a janela p/ ~6K chars (2013*3.2). Mensagem de EXCEDER-por-N não tem teto confiável → None."""
from __future__ import annotations

from okami.llm.errors import _extract_ctx_limit


def test_minimax_exceeds_delta_not_read_as_limit():
    assert _extract_ctx_limit("context window exceeds limit (2013)") is None
    assert _extract_ctx_limit("input exceeded context window by 4096 tokens") is None


def test_real_limit_still_extracted():
    assert _extract_ctx_limit("maximum context length is 8192 tokens") == 8192
    assert _extract_ctx_limit("This model's context window of 32768 was exceeded") == 32768
    assert _extract_ctx_limit("8192 tokens is the maximum context") == 8192


def test_delta_then_real_limit_prefers_real():
    # se vier o excesso E o teto, ignora o excesso e pega o teto
    assert _extract_ctx_limit("exceeds by 2013; maximum context length is 40960 tokens") == 40960
