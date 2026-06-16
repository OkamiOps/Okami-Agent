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
    max_steps: int = 200         # passos (ações) por tarefa — alto p/ trabalho longo de verdade (review/refactor)
    max_consecutive_violations: int = 3
    max_repeat: int = 3          # mesma ação N vezes → loop
    stall_limit: int = 4         # passos sem efeito observável → quebra
    max_loop_breaks: int = 3     # quebras de loop antes de FAILED
    max_poll_waits: int = 8      # ESPERAS repetidas num processo em background (process_wait/poll/log) antes de
    #                              cobrar como loop — esperar um build/teste lento NÃO é loop inútil, é I/O
    max_total_turns: int = 1000  # backstop bem acima de max_steps → o limite que vale é o de passos
    max_context_chars: int = 64000  # dispara auto-compaction (§6.4). Produção SOBRESCREVE com o teto real
    #   do modelo (prov.compaction_threshold_chars); este default só vale p/ testes diretos de Harness. Subiu
    #   de 24000→64000 porque o próprio system-prompt (lista de tools) já beira 24K — a 24000 qualquer turno
    #   multi-passo disparava compaction espúria. Testes que EXIGEM compaction passam max_context_chars=24000.
    # Teto AGREGADO de tool-output do turno (Hermes: 200K chars). O teto por-resultado (8K) não
    # impede N resultados médios de inundar o contexto; estourou o agregado → outputs passam a ser
    # persistidos com preview CURTO mesmo abaixo do teto individual.
    max_turn_tool_chars: int = 200_000
    # NÃO é teto de relógio do turno (isso matava trabalho longo legítimo — review de 1M linhas, pytest de 10min).
    # É um detector de TRAVAMENTO: tempo MÁXIMO sem CONCLUIR um passo. Reseta a cada passo executado, então
    # durante atividade nunca dispara — só quando a agente fica de fato parada (provider pendurado/spinning).
    # 0 = desliga. Hang de uma chamada já tem timeout por-chamada no transporte; isto é a rede de segurança.
    max_stall_seconds: float = 300.0


# ----------------------------------------------------------------------------- protocolo
