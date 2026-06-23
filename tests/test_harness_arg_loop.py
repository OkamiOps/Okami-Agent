"""Loop SILENCIOSO de args malformados (queixa do dono: agente girava 50min sem entregar).

O caminho de re-prompt de argumento obrigatório faltante (loop.py) NÃO contava passo NEM violação, e
`_consecutive_violations` é zerado assim que chega uma ação parseável — então um modelo fraco que insiste
numa tool SEM o arg obrigatório, VARIANDO os outros args (fingerprint diferente a cada vez → o anti-loop
por args idênticos não pega), girava até o backstop de 1000 turns. Agora um contador próprio de
args-malformados-seguidos corta cedo (escala/falha), sem queimar minutos do dono."""
from __future__ import annotations

import json

from okami.core import Harness, Task, TaskState


def J(tool: str, **args) -> str:
    return "```json\n" + json.dumps({"tool": tool, "args": args}) + "\n```"


class DriftingMalformed:
    """Provider falso: SEMPRE read_file sem 'path' (obrigatório), com um arg-lixo DIFERENTE a cada chamada
    → cada ação tem fingerprint distinto, escapando do anti-loop por args idênticos."""

    def __init__(self):
        self.calls = 0

    def __call__(self, messages, schema=None):
        self.calls += 1
        return J("read_file", offset=self.calls)   # nunca manda 'path' (obrigatório); 'offset' varia


def test_repeated_missing_arg_fails_fast_without_burning_turns(tmp_path):
    model = DriftingMalformed()
    events = []
    h = Harness(model, Task(goal="escreva um arquivo"), tmp_path, on_event=events.append)
    r = h.run()
    assert r.state == TaskState.FAILED                       # NÃO fica girando — falha limpa
    assert model.calls <= 8                                  # cortou cedo, não rodou ~1000 turns
    assert not any(e.get("kind") == "step" for e in events)  # nenhum passo foi de fato dispatchado
    # a razão da falha aponta o problema REAL (args malformados), não um "esgotou passos" genérico
    assert "malform" in (r.reason or "").lower() or "argument" in (r.reason or "").lower() \
        or "obrigat" in (r.reason or "").lower()
