"""Vazamento de raciocínio ao vivo (minimax/DeepSeek): reasoning vem SEM tag <think>, e o scrubber antigo
só pegava <think> literal + não tinha flush. Agora: variantes case-insensitive, flush, e reasoning_content
envolvido em <think> na origem (limpo no display E na resposta final)."""
from okami.llm.streaming import _ThinkScrubber


def test_variantes_e_case_insensitive():
    s = _ThinkScrubber()
    vis = "".join(s.feed(d) for d in ["A ", "<REASON", "ING>x</REASONING> B"]) + s.flush()
    assert "x" not in vis and "A" in vis and "B" in vis


def test_flush_recupera_tail_que_parecia_tag():
    s = _ThinkScrubber()
    v = s.feed("resposta<th") + s.flush()
    assert v == "resposta<th"        # não come o fim da resposta


def test_think_aberto_no_fim_descarta():
    s = _ThinkScrubber()
    v = s.feed("<think>raciocinio sem fechar") + s.flush()
    assert v == ""                    # fail-safe: não vaza think truncado


def test_tag_partida_entre_deltas():
    s = _ThinkScrubber()
    vis = "".join(s.feed(d) for d in ["oi <thi", "nk>secreto</thi", "nk> tchau"]) + s.flush()
    assert "secreto" not in vis and "oi" in vis and "tchau" in vis
