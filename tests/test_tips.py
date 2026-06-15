"""Corpus de dicas contextuais — `okami.core.tips`. Ensina features REAIS do Okami em one-liners."""
from __future__ import annotations


def test_corpus_tem_pelo_menos_24_dicas():
    from okami.core.tips import TIPS
    assert len(TIPS) >= 24


def test_get_tip_deterministico_por_seed():
    from okami.core.tips import TIPS, get_tip
    assert get_tip(0) == TIPS[0]
    assert get_tip(1) == TIPS[1]
    # seed estável (módulo) — mesmo além do tamanho da lista
    assert get_tip(len(TIPS)) == TIPS[0]
    assert get_tip(7) == TIPS[7 % len(TIPS)]


def test_get_tip_sem_seed_vem_do_corpus():
    from okami.core.tips import TIPS, get_tip
    # repetido p/ exercitar o random.choice em vários sorteios
    for _ in range(50):
        assert get_tip(None) in TIPS


def test_get_tip_default_e_none():
    from okami.core.tips import TIPS, get_tip
    # chamada sem argumento == seed None (aleatória, mas sempre do corpus)
    assert get_tip() in TIPS


def test_todas_as_tips_sao_str_nao_vazias_curtas():
    from okami.core.tips import TIPS
    for t in TIPS:
        assert isinstance(t, str)
        assert t.strip(), "tip vazia"
        assert len(t) < 140, f"tip longa demais ({len(t)}): {t!r}"


def test_sem_duplicatas():
    from okami.core.tips import TIPS
    assert len(set(TIPS)) == len(TIPS)
