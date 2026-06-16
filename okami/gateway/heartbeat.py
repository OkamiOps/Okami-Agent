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


def heartbeat_message(*, elapsed_s: float) -> str:
    """'ainda trabalhando, ~N min' (arredonda p/ minuto; <1min vira ~1)."""
    mins = max(1, round(elapsed_s / 60.0))
    return f"⏳ ainda trabalhando nisso, ~{mins} min…"


__all__ = ["heartbeat_due", "heartbeat_message"]
