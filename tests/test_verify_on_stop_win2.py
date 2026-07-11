"""WIN2 (Hermes-parity audit, espírito verification_stop.py): verify-on-stop MÍNIMO.

task_complete com exit_criteria VAZIO (nada verificável declarado) + efeito real nesta corrida (escreveu/
editou/rodou algo) + NENHUM run_shell bem-sucedido depois do último efeito → o harness empurra UMA vez
("verifique antes de concluir") em vez de aceitar de bandeja; na 2ª tentativa aceita DE QUALQUER JEITO
(sem risco de loop — é nudge, não gate como check_exit)."""
from __future__ import annotations

import json

from okami.core import Harness, Task, TaskState
from okami.core.harness.loop import _verified_since_last_effect
from okami.core.harness.models import Step


def J(tool: str, **args) -> str:
    return "```json\n" + json.dumps({"tool": tool, "args": args}) + "\n```"


class Script:
    def __init__(self, outputs, default=None):
        self.outputs = list(outputs)
        self.default = default

    def __call__(self, messages, schema=None):
        return self.outputs.pop(0) if self.outputs else self.default


# ------------------------------------------------------------------ unit: a heurística em si
def test_verified_since_last_effect_true_when_no_effect_yet():
    assert _verified_since_last_effect([]) is True
    assert _verified_since_last_effect([Step(1, "read_file", {}, "conteudo", False, True)]) is True


def test_verified_since_last_effect_false_without_run_shell_after():
    steps = [Step(1, "write_file", {}, "ok", True, True)]
    assert _verified_since_last_effect(steps) is False


def test_verified_since_last_effect_true_with_ok_run_shell_after():
    steps = [Step(1, "write_file", {}, "ok", True, True),
             Step(2, "run_shell", {}, "tudo passou", False, True)]
    assert _verified_since_last_effect(steps) is True


def test_verified_since_last_effect_false_when_run_shell_failed():
    steps = [Step(1, "write_file", {}, "ok", True, True),
             Step(2, "run_shell", {}, "erro", False, False)]     # rodou mas FALHOU (ok=False) → não conta
    assert _verified_since_last_effect(steps) is False


def test_verified_since_last_effect_false_when_run_shell_before_the_effect():
    # run_shell ANTES do efeito não comprova o resultado DESSE efeito
    steps = [Step(1, "run_shell", {}, "ok", False, True),
             Step(2, "write_file", {}, "ok", True, True)]
    assert _verified_since_last_effect(steps) is False


# ------------------------------------------------------------------ integração: Harness fim-a-fim
def test_task_complete_nudged_once_then_accepted_regardless(tmp_path):
    outputs = [
        J("write_file", path="a.py", content="x=1"),   # efeito real (CODIGO exige verify)
        J("task_complete", summary="feito"),            # sem verify → nudge (1ª tentativa REJEITADA)
        J("task_complete", summary="feito"),             # 2ª tentativa: aceita de qualquer jeito
    ]
    events = []
    t = Task(goal="cria a.txt")                          # exit_criteria VAZIO
    r = Harness(Script(outputs), t, tmp_path, on_event=events.append).run()

    assert r.state == TaskState.COMPLETE
    rejects = [e for e in events if e["kind"] == "complete_rejected"
               and "sem verificação" in str(e.get("missing"))]
    assert len(rejects) == 1                              # avisou exatamente 1x, não mais


def test_task_complete_accepted_immediately_when_run_shell_confirms(tmp_path):
    outputs = [
        J("write_file", path="a.py", content="x=1"),
        J("run_shell", cmd="true"),                        # verificação BEM-SUCEDIDA depois do efeito
        J("task_complete", summary="feito e verificado"),
    ]
    events = []
    t = Task(goal="cria a.txt")
    r = Harness(Script(outputs), t, tmp_path, on_event=events.append).run()

    assert r.state == TaskState.COMPLETE
    rejects = [e for e in events if e["kind"] == "complete_rejected"
               and "sem verificação" in str(e.get("missing"))]
    assert not rejects                                     # não precisou nudgear — já tinha verificação


def test_task_complete_not_nudged_when_no_effect_happened(tmp_path):
    """Tarefa read-only (análise/relatório): sem efeito nenhum → nada a verificar, aceita direto."""
    outputs = [
        J("read_file", path="a.txt"),
        J("task_complete", summary="analisei, tudo ok"),
    ]
    (tmp_path / "a.txt").write_text("conteudo", encoding="utf-8")
    events = []
    t = Task(goal="analise a.txt")
    r = Harness(Script(outputs), t, tmp_path, on_event=events.append).run()

    assert r.state == TaskState.COMPLETE
    rejects = [e for e in events if e["kind"] == "complete_rejected"
               and "sem verificação" in str(e.get("missing"))]
    assert not rejects


def test_task_complete_not_nudged_when_exit_criteria_present(tmp_path):
    """Exit_criteria NÃO-vazio já é verificação de verdade (check_exit) — o nudge de WIN2 é só p/ o caso
    exit_criteria VAZIO; não deve duplicar/incomodar quando já existe um critério declarado."""
    outputs = [
        J("write_file", path="a.txt", content="oi"),     # casa com o exit_criteria (teste não é sobre doc-exclusion)
        J("task_complete", summary="feito"),
    ]
    events = []
    t = Task(goal="cria a.txt", exit_criteria=[{"type": "file_exists", "path": "a.txt"}])
    r = Harness(Script(outputs), t, tmp_path, on_event=events.append).run()

    assert r.state == TaskState.COMPLETE
    rejects = [e for e in events if e["kind"] == "complete_rejected"
               and "sem verificação" in str(e.get("missing"))]
    assert not rejects


def test_step_records_tool_result_ok_flag(tmp_path):
    """Step.ok (novo campo, models.py) reflete res.ok — é o que a heurística de WIN2 lê."""
    outputs = [J("run_shell", cmd="false"), J("task_blocked", reason="rodou mas falhou")]
    t = Task(goal="roda algo que falha")
    r = Harness(Script(outputs), t, tmp_path).run()
    assert r.steps and r.steps[0].tool == "run_shell"
    assert r.steps[0].ok is False                          # `false` sai com exit != 0


def test_edit_de_doc_nao_dispara_nudge_de_verify(tmp_path):
    """Paridade Hermes: editar README.md (prosa) NÃO exige rodar teste — antes disparava nudge espúrio."""
    outputs = [
        J("write_file", path="README.md", content="# docs"),   # doc-only → sem verify
        J("task_complete", summary="atualizei o readme"),
    ]
    events = []
    r = Harness(Script(outputs), Task(goal="atualiza README"), tmp_path, on_event=events.append).run()
    assert r.state == TaskState.COMPLETE
    rejects = [e for e in events if e["kind"] == "complete_rejected" and "sem verificação" in str(e.get("missing"))]
    assert not rejects                                     # doc não pede verificação
