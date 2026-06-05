"""Context Engine: monta por prioridade dentro do orçamento, protege identidade, audita (manifest)."""

from __future__ import annotations

from okami.core.context import ContextEngine


def test_assembles_in_order_and_is_identical_under_budget():
    eng = ContextEngine(budget_chars=10000)
    eng.add("core", "IDENTIDADE").add("memory", "RECALL").add("skills", "SKILL")
    text, man = eng.build()
    assert text == "IDENTIDADE\n\nRECALL\n\nSKILL"           # = concatenação antiga, sem truncar
    assert [m["section"] for m in man] == ["core", "memory", "skills"]
    assert all(not m["truncated"] and not m["dropped"] for m in man)


def test_skips_empty_sections():
    eng = ContextEngine()
    eng.add("a", "X").add("b", "").add("c", None).add("d", "   ")
    text, man = eng.build()
    assert text == "X" and [m["section"] for m in man] == ["a"]


def test_protected_identity_never_truncated_rest_budgeted():
    eng = ContextEngine(budget_chars=20)
    eng.add("core", "I" * 50, protected=True)               # identidade > orçamento, mas PROTEGIDA
    eng.add("mem", "M" * 50)
    text, man = eng.build()
    assert text.startswith("I" * 50)                        # identidade inteira, intocada
    mem = next(m for m in man if m["section"] == "mem")
    assert mem["dropped"] or mem["truncated"]               # o resto não cabe → cortado


def test_truncation_is_marked_in_text_and_manifest():
    eng = ContextEngine(budget_chars=30)
    eng.add("big", "Z" * 100)
    text, man = eng.build()
    assert "truncado" in text and man[0]["truncated"] is True
