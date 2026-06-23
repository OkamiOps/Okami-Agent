"""Reduz ERRO+lentidão (sweep #9): tool que chama modelo auxiliar (vision/web_extract/video) levava um 429
do provider e devolvia 'falhou: ...' — classify_tool via TOOL_FAIL determinístico e o circuit breaker
martelava 3x a MESMA chamada com 429. Agora classify_tool reconhece o transitório → RATE_LIMIT, e o loop
avisa 'é limite, espere' em vez de tratar como tool quebrada."""
from __future__ import annotations

from okami.core.errors import FailureKind, classify_tool
from okami.core.tools.base import ToolResult


def test_rate_limit_in_tool_output_is_transient():
    r = ToolResult(False, "vision_analyze falhou: ClassifiedError(reason='rate_limit', status=429)")
    assert classify_tool(r).kind == FailureKind.RATE_LIMIT


def test_overloaded_is_transient():
    r = ToolResult(False, "web_extract falhou: provider overloaded, try again in 5s")
    assert classify_tool(r).kind == FailureKind.RATE_LIMIT


def test_normal_tool_error_stays_tool_fail():
    r = ToolResult(False, "erro: arquivo não encontrado")
    assert classify_tool(r).kind == FailureKind.TOOL_FAIL


def test_sandbox_still_wins_over_transient():
    r = ToolResult(False, "permission denied: read-only")
    assert classify_tool(r).kind == FailureKind.SANDBOX_DENY
