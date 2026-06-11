"""Mensagem de falha de provider HUMANA e acionável (dor: usuário viu 'provider falhou: overloaded'
seco no Telegram). Cada tipo de falha vira uma frase clara do que houve e o que fazer."""

from __future__ import annotations

from okami.core.errors import friendly_failure


def test_overloaded_is_human_and_actionable():
    msg = friendly_failure("overloaded").lower()
    assert "sobrecarregad" in msg
    assert "instante" in msg or "de novo" in msg or "tente" in msg   # diz o que fazer


def test_rate_limit():
    assert "limite" in friendly_failure("rate_limit").lower()


def test_auth():
    for r in ("auth", "auth_permanent"):
        assert "credencial" in friendly_failure(r).lower() or "login" in friendly_failure(r).lower()


def test_context_overflow_suggests_compact():
    msg = friendly_failure("context_overflow").lower()
    assert "longa" in msg or "/compact" in msg or "/new" in msg


def test_timeout():
    assert "demor" in friendly_failure("timeout").lower()


def test_unknown_reason_has_generic_message():
    msg = friendly_failure("algum-erro-desconhecido")
    assert msg and "algum-erro-desconhecido" in msg      # mostra o motivo cru no fallback


def test_no_raw_overloaded_token_leaks_for_known():
    # p/ falhas conhecidas, NÃO mostra o token técnico cru ('overloaded') sozinho — é frase humana
    assert friendly_failure("overloaded") != "overloaded"


# ----------------------------------------------------------------- integração no harness
def test_harness_fail_message_is_friendly():
    from okami.core import Task, TaskState
    from okami.core.harness.loop import Harness

    def boom(messages, schema):
        raise RuntimeError("Error code: 529 - overloaded_error")

    import tempfile
    h = Harness(boom, Task(goal="oi"), workspace=tempfile.mkdtemp())
    t = h.run()
    assert t.state in (TaskState.FAILED, TaskState.BLOCKED)
    low = (t.reason or t.result or "").lower()
    assert "sobrecarregad" in low                          # não é mais "provider falhou: overloaded"
