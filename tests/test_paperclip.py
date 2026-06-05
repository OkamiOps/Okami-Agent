"""Testes do adapter Paperclip (heartbeat) — cliente HTTP fake, run_task fake."""

from __future__ import annotations

import pytest

from okami.channels.paperclip import (
    PaperclipClient,
    PaperclipConflict,
    PaperclipError,
    _pick_issue,
    run_heartbeat,
)
from okami.core import Task, TaskState


class FakePaperclip:
    def __init__(self, issues=None, me=None, checkout_conflict=False):
        self._issues = issues if issues is not None else []
        self._me = me or {"id": "a1", "companyId": "c1", "role": "dev", "budget": 100}
        self.checkout_conflict = checkout_conflict
        self.calls: list = []
        self.patches: list = []
        self.interactions: list = []

    def me(self):
        self.calls.append(("me",))
        return self._me

    def list_issues(self, company_id, agent_id, statuses=None):
        self.calls.append(("list", company_id, agent_id))
        return self._issues

    def checkout(self, issue_id, agent_id, expected_statuses=None):
        self.calls.append(("checkout", issue_id))
        if self.checkout_conflict:
            raise PaperclipConflict("409")
        return {"ok": True}

    def heartbeat_context(self, issue_id):
        return {"comments": []}

    def get_issue(self, issue_id):
        return {}

    def patch_issue(self, issue_id, status, comment):
        self.patches.append((issue_id, status, comment))
        return {}

    def create_interaction(self, issue_id, kind, prompt, payload=None):
        self.interactions.append((issue_id, kind, prompt))
        return {}


def make_runner(state, result="feito", reason="", sensitive=None):
    def runner(cfg, ws, goal, *, approve=None, extra_context="", emit=lambda m: None, **kw):
        if sensitive and approve:
            approve(sensitive)                       # simula uma ação sensível pedindo go/no-go
        t = Task(goal=goal)
        t.state, t.result, t.reason = state, result, reason
        return t
    return runner


_EVID = "Corrigi o off-by-one em okami/core/harness.py e rodei `pytest`: 690 testes passaram."


def test_heartbeat_happy_path_checks_out_and_marks_done():
    cli = FakePaperclip(issues=[{"id": "i1", "title": "fix bug", "status": "todo", "priority": 2}])
    res = run_heartbeat(None, ".", run_task=make_runner(TaskState.COMPLETE, result=_EVID),
                        client=cli, env={})
    assert res.status == "done" and res.issue_id == "i1"
    assert ("checkout", "i1") in cli.calls           # checkout ANTES de trabalhar
    assert cli.patches == [("i1", "done", _EVID)]


def test_heartbeat_complete_without_evidence_falls_to_in_review():
    # #P1: control plane não marca done só porque o agente disse 'complete' — exige prova material.
    cli = FakePaperclip(issues=[{"id": "i1", "title": "fix bug", "status": "todo"}])
    res = run_heartbeat(None, ".", run_task=make_runner(TaskState.COMPLETE, result="Concluído."),
                        client=cli, env={})
    assert res.status == "in_review"                 # board bonito sem prova → revisão, não done
    assert cli.patches[0][1] == "in_review" and "evidência" in cli.patches[0][2].lower()


def test_require_evidence_opt_out_via_config():
    # operador pode desligar (cfg.paperclip.require_evidence: false) — volta a aceitar 'complete' cru
    from okami.config import build_config
    cfg = build_config({"default_provider": "a", "providers": {"a": {"model": "m"}},
                        "paperclip": {"require_evidence": False}})
    cli = FakePaperclip(issues=[{"id": "i1", "title": "x", "status": "todo"}])
    res = run_heartbeat(cfg, ".", run_task=make_runner(TaskState.COMPLETE, result="ok"),
                        client=cli, env={})
    assert res.status == "done"


def test_has_material_evidence_heuristic():
    from okami.channels.paperclip import has_material_evidence
    assert not has_material_evidence("Concluído.") and not has_material_evidence("Feito ✓")
    assert has_material_evidence("Editei src/app.py e validei o fluxo de login com o time todo.")
    assert has_material_evidence("Rodei `pytest`, 12 testes passaram sem erro nenhum aqui agora.")
    assert has_material_evidence("Evidência: commit a1b2c3d na branch fix/login resolve o caso.")


def test_heartbeat_409_stops_without_patch():
    cli = FakePaperclip(issues=[{"id": "i1", "title": "x", "status": "todo"}], checkout_conflict=True)
    res = run_heartbeat(None, ".", run_task=make_runner(TaskState.COMPLETE), client=cli, env={})
    assert res.status == "none" and cli.patches == []   # 409 → para, NUNCA repete nem trabalha


def test_heartbeat_no_actionable_issue():
    cli = FakePaperclip(issues=[])
    res = run_heartbeat(None, ".", run_task=make_runner(TaskState.COMPLETE), client=cli, env={})
    assert res.status == "none" and cli.patches == []


def _runner_capturing(captured):
    def runner(cfg, ws, goal, *, approve=None, extra_context="", emit=lambda m: None, surface="cli", **kw):
        captured["surface"] = surface
        t = Task(goal=goal)
        t.state = TaskState.COMPLETE
        return t
    return runner


def test_heartbeat_passes_role_based_surface():
    """#P1: o papel do Paperclip (me['role']) vira a superfície de tool policy do run_task."""
    cap = {}
    cli = FakePaperclip(issues=[{"id": "i1", "title": "x", "status": "todo"}],
                        me={"id": "a1", "companyId": "c1", "role": "manager"})
    run_heartbeat(None, ".", run_task=_runner_capturing(cap), client=cli, env={})
    assert cap["surface"] == "paperclip-manager"             # manager → surface sem execução

    cap2 = {}
    cli2 = FakePaperclip(issues=[{"id": "i1", "title": "x", "status": "todo"}],
                         me={"id": "a1", "companyId": "c1", "role": "dev"})   # papel desconhecido
    run_heartbeat(None, ".", run_task=_runner_capturing(cap2), client=cli2, env={})
    assert cap2["surface"] == "paperclip"                    # default = worker


def test_heartbeat_blocked_marks_blocked_with_reason():
    cli = FakePaperclip(issues=[{"id": "i1", "title": "x", "status": "in_progress"}])
    res = run_heartbeat(None, ".", run_task=make_runner(TaskState.BLOCKED, reason="faltou credencial"),
                        client=cli, env={})
    assert res.status == "blocked"
    assert cli.patches == [("i1", "blocked", "faltou credencial")]


def test_heartbeat_defer_sensitive_creates_interaction_and_in_review():
    cli = FakePaperclip(issues=[{"id": "i1", "title": "x", "status": "todo"}])
    sens = {"reason": "editar .env", "category": "env_file", "risk": "high"}
    res = run_heartbeat(None, ".", run_task=make_runner(TaskState.BLOCKED, reason="negado", sensitive=sens),
                        client=cli, env={}, approve_mode="defer")
    assert res.status == "in_review"                 # governança: adia p/ confirmação humana
    assert cli.interactions and cli.interactions[0][1] == "request_confirmation"
    assert cli.patches[0][1] == "in_review"


def test_heartbeat_yolo_auto_approves_no_interaction():
    cli = FakePaperclip(issues=[{"id": "i1", "title": "x", "status": "todo"}])
    sens = {"reason": "rm -rf", "category": "destructive_shell", "risk": "critical"}
    res = run_heartbeat(None, ".", run_task=make_runner(TaskState.COMPLETE, result=_EVID, sensitive=sens),
                        client=cli, env={}, approve_mode="yolo")
    assert res.status == "done" and cli.interactions == []   # yolo aprovou tudo


def test_pick_issue_priority_and_task_id():
    issues = [{"id": "a", "status": "todo"}, {"id": "b", "status": "in_progress"},
              {"id": "c", "status": "in_review"}]
    assert _pick_issue(issues, None)["id"] == "b"    # in_progress primeiro
    assert _pick_issue(issues, "c")["id"] == "c"     # PAPERCLIP_TASK_ID honrado
    assert _pick_issue([], None) is None


def test_from_env_requires_url_and_key():
    with pytest.raises(PaperclipError):
        PaperclipClient.from_env({})
    c = PaperclipClient.from_env({"PAPERCLIP_API_URL": "https://x/api", "PAPERCLIP_API_KEY": "k",
                                  "PAPERCLIP_RUN_ID": "r1"})
    assert c.run_id == "r1" and c._url("/api/agents/me") == "https://x/api/agents/me"  # não duplica /api
