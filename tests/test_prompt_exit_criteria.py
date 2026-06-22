"""Bug (sweep #1): os critérios de saída eram despejados como dict CRU no prompt do modo-trabalho
(`f"  - {c}"` → "{'type': 'file_exists', 'path': 'hello.txt'}"), ilegível p/ o modelo. Devem virar
descrição legível ("o arquivo 'hello.txt' deve existir")."""
from __future__ import annotations

from okami.core.harness.models import Task
from okami.core.harness.prompt import build_system_prompt


def test_exit_criteria_formatted_readably_not_raw_dict():
    t = Task(goal="criar o arquivo hello.txt", exit_criteria=[
        {"type": "file_exists", "path": "hello.txt"},
        {"type": "shell_ok", "cmd": "pytest -q"},
    ])
    p = build_system_prompt(t, {})
    assert "{'type'" not in p                         # NÃO despeja o dict cru no prompt
    assert "hello.txt" in p and "pytest -q" in p      # mostra os campos de forma legível
