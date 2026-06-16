"""Bookkeeping de recuperação por-attempt (#11, port do Hermes agent/turn_retry_state.py).

Centraliza os guards one-shot de recuperação (cada caminho caro — refresh OAuth, shrink de imagem,
strip de thinking — roda no MÁXIMO 1× por tentativa) que antes viviam espalhados como `recovered: set`
+ ifs inline no provider. Torna a estratégia de retry auditável e testável.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TurnRetryState:
    """Guards de recuperação já gastos nesta tentativa. `try_once(name)` devolve True só na 1ª vez."""
    attempted: set = field(default_factory=set)

    def try_once(self, name: str) -> bool:
        """True se `name` ainda não foi tentado (e marca como tentado); False se já foi."""
        if name in self.attempted:
            return False
        self.attempted.add(name)
        return True

    def did(self, name: str) -> bool:
        return name in self.attempted

    def reset(self) -> None:
        self.attempted.clear()


__all__ = ["TurnRetryState"]
