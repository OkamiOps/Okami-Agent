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


def test_native_weak_model_prompt_has_zero_json_format_steering():
    # BUG: o modelo fraco (minimax) recebia ```json``` em 3 lugares MESMO no nativo (family guidance +
    # linha de fechamento), contradizendo "emita o tool_call de verdade" → ele cuspia JSON-texto e a ação
    # nunca rodava. No nativo NÃO pode sobrar NENHUMA instrução de formato json.
    p = build_system_prompt(Task(goal="crie hello.txt e leia de volta"), default_registry(),
                            model="minimax/MiniMax-M3", native=True)
    assert "```json" not in p                           # nem o bloco de exemplo da family guidance
    assert "bloco json" not in p.lower()                # nem a frase de fechamento "um único bloco json"


def test_native_conversational_prompt_has_no_json_closing():
    p = build_system_prompt(Task(goal="oi, tudo bem?"), default_registry(),
                            model="minimax/MiniMax-M3", native=True)
    assert "```json" not in p
    assert "bloco json" not in p.lower()


def test_json_weak_model_prompt_keeps_json_steering():
    p = build_system_prompt(Task(goal="crie hello.txt"), default_registry(),
                            model="minimax/MiniMax-M3", native=False)
    assert "```json" in p                               # rail JSON-em-texto: instrui o formato (correto)


def test_json_prompt_is_unchanged_by_default():
    p = build_system_prompt(Task(goal="x"), default_registry(), model="openai/gpt-5.4")   # native=False default
    assert "um bloco ```json" in p                      # rail JSON-em-texto intacto
    assert "SEU REPERTÓRIO" in p                        # repertório de tools no texto
    assert '{"tool": "read_file", "args":' in p         # few-shot preservado
