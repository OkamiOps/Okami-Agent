"""Finalização de turno (#11, port leve do Hermes agent/turn_finalizer.py).

O Hermes fatora a região PÓS-loop (montagem do resultado, hooks de plugin, diagnóstico do turno) numa
função com contrato explícito de result-dict. O Okami devolve uma Task mutada; aqui expomos um sumário
estruturado do resultado (contrato auditável) sem reescrever o loop — útil p/ telemetria/diagnóstico.
"""
from __future__ import annotations


def summarize_result(task, *, api_calls: int = 0, interrupted: bool = False) -> dict:
    """Dict de resultado do turno: estado, se concluiu, nº de passos/api-calls, razão de saída."""
    raw = getattr(getattr(task, "state", None), "value", "") or str(getattr(task, "state", ""))
    state = str(raw).lower()
    return {
        "state": state,
        "completed": state == "complete",
        "interrupted": interrupted,
        "api_calls": api_calls,
        "steps": len(getattr(task, "steps", []) or []),
        "has_result": bool(getattr(task, "result", "")),
        "exit_reason": getattr(task, "reason", "") or "",
    }


__all__ = ["summarize_result"]
