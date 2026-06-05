"""Gateway de mensageria (§13) — control plane channel-agnóstico (estilo OpenClaw).

Por agente: um Channel (Telegram/…) → Sessões por chat (continuidade de conversa) → roda a tarefa no
workspace do agente. Este `__init__` é só a FACHADA do pacote — o código mora em submódulos:
  • genesis.py   — gênese/primeiro contato + bloco de histórico
  • endpoint.py  — Session + AgentEndpoint (control plane por agente)
  • group.py     — GroupEndpoint (sala multi-agente)
  • builders.py  — build_endpoints/build_group_endpoints/run_gateway + scheduler
  • sessions.py / checkpoints.py / approvals.py — serviços de apoio

A API pública (importada por testes, TUI, CLI) é re-exportada aqui — quem fazia `from okami.gateway
import AgentEndpoint` continua igual.
"""

from __future__ import annotations

from okami.gateway.builders import (
    build_endpoints,
    build_group_endpoints,
    run_gateway,
)
from okami.gateway.endpoint import AgentEndpoint, Session
from okami.gateway.genesis import (
    GENESIS_BLOCK,
    _history_block,
    _seal_genesis,
    genesis_pending,
)
from okami.gateway.group import GroupEndpoint

__all__ = [
    "Session", "AgentEndpoint", "GroupEndpoint",
    "build_endpoints", "build_group_endpoints", "run_gateway",
    "genesis_pending", "_seal_genesis", "_history_block", "GENESIS_BLOCK",
]
