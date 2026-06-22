"""Tokens SEMPRE visíveis (queixa do dono: gerou PDF, viu só '· 628s' sem tokens). Modelo local
(LMStudio) não reporta usage → total=0 → o rodapé somia os tokens. Fix: estimar via chars/token quando
o provider não reporta, marcado como ~estimado, e o rodapé passa a mostrar sempre."""
from __future__ import annotations

from okami.llm.usage import CanonicalUsage, estimate_usage


def test_estimate_usage_from_text():
    u = estimate_usage("abcd" * 100, "xy" * 50, chars_per_token=4.0)   # 400 in / 100 out chars
    assert u.input_tokens == 100 and u.output_tokens == 25
    assert u.estimated is True and u.requests == 1


def test_estimate_usage_handles_empty_and_bad_cpt():
    u = estimate_usage("", "", chars_per_token=0)        # cpt inválido → cai pro default 4
    assert u.input_tokens == 0 and u.output_tokens == 0 and u.estimated is True


def test_estimated_flag_round_trips():
    u = estimate_usage("a" * 40, "b" * 8)
    d = u.to_dict()
    assert d.get("estimated") is True
    assert CanonicalUsage.from_dict(d).estimated is True


def test_estimated_propagates_through_add():
    real = CanonicalUsage(input_tokens=10, output_tokens=5, requests=1)        # do provider
    est = estimate_usage("x" * 40, "y" * 4)                                    # estimado
    assert (real + est).estimated is True                                      # se um é estimado, a soma é
    assert (real + CanonicalUsage(requests=1)).estimated is False             # dois reais → não-estimado


def test_real_usage_not_marked_estimated():
    assert CanonicalUsage(input_tokens=10, output_tokens=5).estimated is False
