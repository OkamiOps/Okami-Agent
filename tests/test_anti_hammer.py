"""Anti-martelo: chamar a MESMA tool dezenas de vezes (args mudando a cada chamada, o que escapa do
fingerprint/anti-loop) é o padrão nº1 de agente burro — logs reais tiveram 134× execute_code (200 passos,
teto), 67× move_path. O freio deve AVISAR cedo (12/25) e CORTAR (task_complete/blocked) em max_same_tool,
muito antes dos 200 passos. Prova dirigindo o Harness.run real com um modelo scriptado que martela."""
import json as _json

from okami.core import Budget, Harness, Task
from okami.core.tools import ToolContext  # noqa: F401  (garante import do pacote de tools)


class _Script:
    def __init__(self, outs):
        self.outs = list(outs)

    def __call__(self, messages, schema=None):
        # quando acaba o roteiro, o modelo "desiste" (task_blocked) — mas o freio deve cortar ANTES disso
        return self.outs.pop(0) if self.outs else '```json\n{"tool":"task_blocked","args":{"reason":"fim"}}\n```'


def _J(tool, **a):
    return "```json\n" + _json.dumps({"tool": tool, "args": a}) + "\n```"


def test_martelo_da_mesma_tool_e_cortado_antes_de_200(tmp_path):
    # 60 write_file com PATH diferente a cada chamada (args mudam → fingerprint NÃO pega)
    outs = [_J("write_file", path=f"f{i}.txt", content="x") for i in range(60)]
    events = []
    Harness(_Script(outs), Task(goal="crie muitos arquivos"), tmp_path,
            budget=Budget(stall_limit=99), on_event=events.append).run()

    kinds = [e.get("kind") for e in events]
    # 1) avisou cedo (consciência) em warn_same_tool e push_same_tool
    warns = [e for e in events if e.get("kind") == "same_tool_warn" and e.get("tool") == "write_file"]
    warn_counts = sorted(e.get("count") for e in warns)
    assert Budget().warn_same_tool in warn_counts, f"faltou nudge em {Budget().warn_same_tool}: {warn_counts}"
    assert Budget().push_same_tool in warn_counts, f"faltou nudge em {Budget().push_same_tool}: {warn_counts}"

    # 2) CORTOU o martelo (não deixou moer até 200)
    halts = [e for e in events if e.get("kind") == "same_tool_halt" and e.get("tool") == "write_file"]
    assert halts, "o freio anti-martelo NÃO disparou (deixou martelar sem cortar)"
    assert halts[0].get("count") >= Budget().max_same_tool

    # 3) nº de write_file REALMENTE executados ficou perto do teto, MUITO abaixo de 200/60
    steps = [e for e in events if e.get("kind") == "step" and e.get("tool") == "write_file"]
    assert len(steps) <= Budget().max_same_tool + 2, f"executou {len(steps)} write_file — martelou demais"


def test_tarefa_normal_curta_nao_dispara_o_freio(tmp_path):
    # 3 write_file + concluir: uso legítimo NÃO pode ganhar nudge nem halt
    outs = [_J("write_file", path=f"a{i}.txt", content="x") for i in range(3)]
    outs.append(_J("task_complete", summary="feito"))
    events = []
    Harness(_Script(outs), Task(goal="crie 3 arquivos"), tmp_path,
            budget=Budget(stall_limit=99), on_event=events.append).run()
    assert not [e for e in events if e.get("kind") in ("same_tool_warn", "same_tool_halt")]
