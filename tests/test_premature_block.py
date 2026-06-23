"""Anti-bail (rumo ao Hermes, que NEM tem tool de 'blocked'): o modelo fraco desiste CEDO declarando
task_blocked sem ter tentado nada e sem obstáculo REAL → era honrado na hora (a 'sensação de
incompetência'). Agora um bail PREMATURO (tarefa pede ação, quase nenhum passo, nenhuma tool falhou) é
rejeitado UMA vez e o agente é empurrado a tentar. Bloqueio GENUÍNO (tool falhou / já tentou) é honrado."""
from __future__ import annotations

import json

from okami.core import Harness, Task, TaskState


def J(tool: str, **args) -> str:
    return "```json\n" + json.dumps({"tool": tool, "args": args}) + "\n```"


class Script:
    def __init__(self, outs):
        self.outs = list(outs)

    def __call__(self, messages, schema=None):
        return self.outs.pop(0) if self.outs else J("task_complete", summary="fim")


def test_premature_block_is_rejected_then_agent_works(tmp_path):
    outs = [
        J("task_blocked", reason="não consigo"),            # bail logo de cara → deve ser REJEITADO 1x
        J("write_file", path="x.txt", content="oi"),        # empurrado → trabalha
        J("task_complete", summary="feito"),
    ]
    events = []
    t = Task(goal="crie o arquivo x.txt", exit_criteria=[{"type": "file_exists", "path": "x.txt"}])
    r = Harness(Script(outs), t, tmp_path, on_event=events.append).run()
    assert r.state == TaskState.COMPLETE
    assert (tmp_path / "x.txt").exists()
    assert any(e.get("kind") == "blocked_rejected" for e in events)


def test_genuine_block_after_real_failure_is_honored(tmp_path):
    outs = [
        J("read_file", path="naoexiste.xyz"),               # tool falha de VERDADE → obstáculo real
        J("task_blocked", reason="o arquivo não existe e não há alternativa"),
    ]
    t = Task(goal="crie um resumo de naoexiste.xyz")
    r = Harness(Script(outs), t, tmp_path).run()
    assert r.state == TaskState.BLOCKED                      # bloqueio legítimo → honrado, sem forçar spin


def test_second_block_is_honored_after_nudge(tmp_path):
    # rejeita 1x (one-shot); se insistir no bloqueio, é honrado (não trava o agente num spin)
    outs = [J("task_blocked", reason="x"), J("task_blocked", reason="sério, não dá")]
    t = Task(goal="crie o arquivo z.txt", exit_criteria=[{"type": "file_exists", "path": "z.txt"}])
    r = Harness(Script(outs), t, tmp_path).run()
    assert r.state == TaskState.BLOCKED
