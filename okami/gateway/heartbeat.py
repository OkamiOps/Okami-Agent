"""Heartbeat de turno longo (#11, port do Hermes _send_loading_heartbeat).

Num turno lento (>N s — geração/tool demorada) o canal mostra "📝 escrevendo…" por 30 min sem sinal de
vida. Este helper decide QUANDO emitir um "ainda trabalhando, ~N min" e formata a mensagem. A thread/
timer que chama isso fica no endpoint, gateado por display_config.long_running_notifications.
"""
from __future__ import annotations


def heartbeat_due(*, start: float, now: float, interval: float, last: float) -> bool:
    """True se passou `interval`s desde o último heartbeat (ou desde o start, se nunca houve). `last`=0
    significa 'nenhum ainda' → mede desde o start."""
    if interval <= 0:
        return False
    ref = last if last > start else start
    return (now - ref) >= interval


def heartbeat_message(*, elapsed_s: float, steps: int = 0, tokens: int = 0, tool: str = "") -> str:
    """'ainda trabalhando, ~N min' + (se houver) passo/tool atual e tokens acumulados — pro dono ver o que
    está rolando e o custo correndo num turno longo, não só os minutos. Sufixos só quando >0 (compat:
    sem extras → string idêntica à antiga)."""
    mins = max(1, round(elapsed_s / 60.0))
    msg = f"⏳ ainda trabalhando nisso, ~{mins} min…"
    extra: list[str] = []
    if steps:
        extra.append(f"passo {steps}" + (f" ({tool})" if tool else ""))
    if tokens:
        extra.append(f"~{round(tokens / 1000)}k tok" if tokens >= 1000 else f"~{tokens} tok")
    if extra:
        msg += " · " + " · ".join(extra)
    return msg


__all__ = ["heartbeat_due", "heartbeat_message"]
