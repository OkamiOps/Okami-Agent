"""Classificador de falhas do agente: provider (delega), tool, sandbox-deny e despacho genérico."""

from __future__ import annotations

from okami.core.errors import Action, FailureKind, classify, classify_provider, classify_tool


class _Exc(Exception):
    def __init__(self, msg, status=None):
        super().__init__(msg)
        self.status_code = status


class _Res:
    def __init__(self, ok, output):
        self.ok = ok
        self.output = output


def test_provider_delegates_to_llm_errors():
    f = classify_provider(_Exc("Too Many Requests", 429))
    assert f.kind is FailureKind.RATE_LIMIT and f.retryable and f.action is Action.RETRY
    bad = classify_provider(_Exc("invalid request body", 400))
    assert bad.kind is FailureKind.BAD_REQUEST and not bad.retryable and bad.action is Action.ABORT
    perm = classify_provider(_Exc("403 forbidden", 403))
    assert perm.kind is FailureKind.AUTH_PERMANENT and perm.action is Action.ASK_USER and not perm.retryable
    over = classify_provider(_Exc("overloaded_error", 529))
    assert over.kind is FailureKind.TRANSIENT and over.retryable


def test_tool_failure_vs_sandbox_deny():
    tf = classify_tool(_Res(False, "exit=1\ncommand not found: foo"))
    assert tf.kind is FailureKind.TOOL_FAIL and tf.retryable and tf.action is Action.RETRY
    sb = classify_tool(_Res(False, "sandbox read-only: comando que altera estado bloqueado (mkdir x)"))
    assert sb.kind is FailureKind.SANDBOX_DENY and not sb.retryable and sb.action is Action.ABORT
    esc = classify_tool(_Res(False, "caminho fora do workspace: ../x"))
    assert esc.kind is FailureKind.SANDBOX_DENY and esc.action is Action.ABORT


def test_generic_dispatch():
    assert classify(_Exc("read timed out")).kind is FailureKind.TRANSIENT     # exceção → provider
    assert classify(_Res(False, "erro qualquer da tool")).kind is FailureKind.TOOL_FAIL
    assert classify("coisa solta").kind is FailureKind.UNKNOWN
