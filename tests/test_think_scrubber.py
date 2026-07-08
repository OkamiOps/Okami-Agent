"""think-scrubber no STREAMING (paridade Hermes agent/think_scrubber.py): modelo local/reasoning que
streama <think>...</think> NÃO pode vazar o raciocínio ao vivo no display (Telegram/TUI). O scrubber
suprime só o que vai pro on_token; o Completion.text acumula CRU (o harness já tira <think> onde precisa).
Cobre o caso difícil: a tag partida entre deltas."""
from okami.llm.streaming import _tail_prefix_len, _ThinkScrubber, streaming_generate


def test_scrubber_suprime_think_partido_entre_deltas():
    sc = _ThinkScrubber()
    deltas = ["Oi ", "<thi", "nk>rac", "iocínio secreto", "</thi", "nk> resposta ", "visível"]
    vis = "".join(sc.feed(d) for d in deltas)
    assert "raciocínio" not in vis and "secreto" not in vis   # não vazou
    assert "Oi" in vis and "resposta" in vis and "visível" in vis  # visível preservado


def test_scrubber_sem_think_passa_tudo():
    sc = _ThinkScrubber()
    assert "".join(sc.feed(d) for d in ["abc", "def", "ghi"]) == "abcdefghi"


def test_tail_prefix_len():
    assert _tail_prefix_len("abc<thi", "<think>") == 4   # segura '<thi'
    assert _tail_prefix_len("abc", "<think>") == 0
    assert _tail_prefix_len("x<", "<think>") == 1


def test_streaming_generate_nao_vaza_think_no_display_mas_completion_e_cru():
    deltas = ["Oi ", "<think>", "secreto", "</think>", " visível"]
    seen: list[str] = []
    comp = streaming_generate(None, [], on_token=seen.append, _stream=iter(deltas))
    assert "secreto" not in "".join(seen)                 # display limpo
    assert "<think>" in comp.text and "secreto" in comp.text   # Completion CRU (harness parseia)
