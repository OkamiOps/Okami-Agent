"""Harness do Okami (Fase 1) — o coração confiável. FACHADA do pacote (era harness.py monolítico).

O protocolo é por AÇÃO JSON (model-agnóstico) — funciona em LLM fraca/local (base da paridade §3.5).
Código em models/parsing/prompt/loop; a API pública é re-exportada aqui (quem fazia `from
okami.core.harness import Harness/parse_action/Task/…` não muda).
"""
from __future__ import annotations

from okami.core.harness.loop import Harness
from okami.core.harness.models import Budget, Generate, Step, Task, TaskState
from okami.core.harness.parsing import (
    Action, action_schema, parse_action,
)
from okami.core.harness.prompt import (
    build_system_prompt, check_exit, format_observation, is_conversational,
)
from okami.core.harness.prompt import _user_start

__all__ = [
    "TaskState", "Step", "Task", "Budget", "Action", "Generate", "Harness",
    "parse_action", "action_schema", "build_system_prompt", "check_exit",
    "format_observation", "is_conversational", "_user_start",
]
