"""Ramo NATIVO do prompt: quando o provider honra function-calling, o manual NÃO manda escrever ```json```
(seria ruído — o modelo chama a tool pela API) e as tools NÃO vão no texto (vão no param tools=). O rail
JSON-em-texto (default) segue idêntico p/ local/desconhecido."""
from __future__ import annotations

from okami.core import Task
from okami.core.harness.prompt import build_system_prompt
from okami.core.tools.registry import default_registry


def test_native_prompt_drops_json_instructions_and_tool_dump():
    p = build_system_prompt(Task(goal="x"), default_registry(), model="openai/gpt-5.4", native=True)
    assert "function-calling" in p.lower()
    assert "um bloco ```json" not in p                  # não instrui a escrever JSON
    assert "SEU REPERTÓRIO" not in p                    # tools não despejadas no texto (vão na API)
    assert "respond" in p                               # mas o protocolo (respond/task_complete) é citado


def test_json_prompt_is_unchanged_by_default():
    p = build_system_prompt(Task(goal="x"), default_registry(), model="openai/gpt-5.4")   # native=False default
    assert "um bloco ```json" in p                      # rail JSON-em-texto intacto
    assert "SEU REPERTÓRIO" in p                        # repertório de tools no texto
    assert '{"tool": "read_file", "args":' in p         # few-shot preservado
