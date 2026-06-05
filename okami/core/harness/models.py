"""Modelos do harness: TaskState · Step · Task · Budget — o estado dono do harness (§3.1)."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

Generate = Callable[[list[dict], "dict | None"], str]  # (messages, action_schema) -> texto


class TaskState(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    BLOCKED = "BLOCKED"
    NEEDS_INPUT = "NEEDS_INPUT"
    FAILED = "FAILED"


@dataclass
class Step:
    n: int
    tool: str
    args: dict
    output: str
    effect: bool


@dataclass
class Task:
    goal: str
    exit_criteria: list[dict] = field(default_factory=list)
    state: TaskState = TaskState.PENDING
    steps: list[Step] = field(default_factory=list)
    result: str | None = None
    reason: str | None = None
    stats: dict = field(default_factory=dict)   # sinais p/ reflexão (§7): violations/loops/...


@dataclass
class Budget:
    max_steps: int = 90          # passos (ações) por tarefa — antes 24, baixo demais p/ tarefa real
    max_consecutive_violations: int = 3
    max_repeat: int = 3          # mesma ação N vezes → loop
    stall_limit: int = 4         # passos sem efeito observável → quebra
    max_loop_breaks: int = 3     # quebras de loop antes de FAILED
    max_total_turns: int = 300   # backstop bem acima de max_steps → o limite que vale é o de passos
    max_context_chars: int = 24000  # dispara auto-compaction (§6.4)
    max_wall_seconds: float = 240.0  # TETO de relógio do turno → nunca pendura ~6min e morre silencioso;
                                     # estourou → termina LIMPO (BLOCKED) com mensagem clara


# ----------------------------------------------------------------------------- protocolo
