"""Limite de sessões concorrentes (#11, port do Hermes hermes_cli/active_sessions.py).

Fora-de-escopo p/ o dono-único no caso comum, MAS útil se o bot passar a servir mais gente ou p/ evitar
estouro de quota com N chats simultâneos. Função pura; o caller passa a contagem ativa atual.
"""
from __future__ import annotations


def within_session_limit(*, current: int, limit: int) -> bool:
    """True se dá p/ abrir mais uma sessão. `limit<=0` = ilimitado (default; dono-único)."""
    if limit <= 0:
        return True
    return current < limit


__all__ = ["within_session_limit"]
