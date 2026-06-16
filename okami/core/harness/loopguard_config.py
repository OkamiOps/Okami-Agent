"""Loop-guard config-driven (#11, port do Hermes agent/tool_guardrails.ToolCallGuardrailConfig).

Os thresholds de anti-loop já vivem no Budget (max_repeat/stall_limit/max_loop_breaks/max_poll_waits),
mas eram fixos. Aqui mapeamos o bloco de config `tools.loop_guardrails` p/ kwargs do Budget, pro dono
afinar a sensibilidade sem editar código. Default = nada (Budget mantém os defaults atuais).
"""
from __future__ import annotations

_ALLOWED = ("max_repeat", "stall_limit", "max_loop_breaks", "max_poll_waits", "max_consecutive_violations")


def guardrail_budget_overrides(cfg) -> dict:
    """kwargs de Budget vindos de `cfg.tools.loop_guardrails` (só inteiros positivos das chaves conhecidas)."""
    try:
        tools = getattr(cfg, "tools", None) or {}
        if not isinstance(tools, dict):
            tools = getattr(tools, "__dict__", {}) or {}
        block = tools.get("loop_guardrails") or {}
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for k in _ALLOWED:
        v = block.get(k)
        if isinstance(v, bool):
            continue
        if isinstance(v, int) and v > 0:
            out[k] = v
    return out


__all__ = ["guardrail_budget_overrides"]
