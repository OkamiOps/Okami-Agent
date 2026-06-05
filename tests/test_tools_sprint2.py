"""Sprint 2 — tools: edit_file (replace seguro), audit log, tool-result budget."""

from __future__ import annotations

import json

from okami.core import Harness, Task
from okami.core.tools import EditFile, ToolContext


def J(tool: str, **args) -> str:
    return "```json\n" + json.dumps({"tool": tool, "args": args}) + "\n```"


class Script:
    def __init__(self, outputs, default="ok."):
        self.outputs, self.default = list(outputs), default

    def __call__(self, messages, schema=None):
        return self.outputs.pop(0) if self.outputs else self.default


# ----------------------------------------------------------------- edit_file
def test_edit_file_unique_replace(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\ny = 2\n")
    r = EditFile().run({"path": "a.py", "old": "y = 2", "new": "y = 3"}, ToolContext(workspace=tmp_path))
    assert r.ok and r.effect
    assert (tmp_path / "a.py").read_text() == "x = 1\ny = 3\n"


def test_edit_file_errors(tmp_path):
    (tmp_path / "a.py").write_text("a\na\n")
    ctx = ToolContext(workspace=tmp_path)
    assert EditFile().run({"path": "a.py", "old": "zzz", "new": "q"}, ctx).ok is False     # não achou
    assert EditFile().run({"path": "a.py", "old": "a", "new": "b"}, ctx).ok is False        # ambíguo (2×)
    assert EditFile().run({"path": "nope.py", "old": "a", "new": "b"}, ctx).ok is False     # não existe


def test_edit_file_replace_all(tmp_path):
    (tmp_path / "a.py").write_text("a\na\n")
    r = EditFile().run({"path": "a.py", "old": "a", "new": "b", "replace_all": True},
                       ToolContext(workspace=tmp_path))
    assert r.ok and (tmp_path / "a.py").read_text() == "b\nb\n"


def test_edit_file_on_identity_blocked_without_approver(tmp_path):
    """edit_file em SOUL.md é sensível → sem approver, NEGADO (não edita). Prova que classify cobre edit_file."""
    (tmp_path / "SOUL.md").write_text("essência antiga")
    Harness(Script([J("edit_file", path="SOUL.md", old="antiga", new="nova"),
                    J("respond", message="ok")]), Task(goal="muda a soul"), tmp_path).run()
    assert (tmp_path / "SOUL.md").read_text() == "essência antiga"     # bloqueado


# ----------------------------------------------------------------- audit log
def test_audit_log_records_tools(tmp_path):
    Harness(Script([J("write_file", path="a.txt", content="oi"), J("respond", message="feito")]),
            Task(goal="cria a.txt"), tmp_path, approve=lambda r: True).run()
    audit = (tmp_path / ".okami" / "audit.jsonl").read_text(encoding="utf-8").strip().splitlines()
    recs = [json.loads(ln) for ln in audit]
    assert any(r["event"] == "tool" and r["tool"] == "write_file" and r["ok"] for r in recs)
    assert all("ts" in r for r in recs)


# ----------------------------------------------------------------- tool-result budget
def test_tool_result_budget_truncates_and_persists(tmp_path):
    (tmp_path / "big.txt").write_text("x" * 20_000)
    Harness(Script([J("read_file", path="big.txt"), J("respond", message="li")]),
            Task(goal="lê o arquivo grande"), tmp_path).run()
    saved = tmp_path / ".okami" / "tool_outputs" / "step_1.txt"
    assert saved.exists() and len(saved.read_text(encoding="utf-8")) == 20_000   # completo persistido
