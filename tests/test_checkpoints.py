"""Testes de checkpoints/rollback de arquivo (snapshot antes de escrever, estilo Hermes)."""

from __future__ import annotations

from okami.gateway.checkpoints import Checkpoints
from okami.core import Budget, Harness, Task
from okami.core.tools import ToolContext, WriteFile

import json


def J(tool, **args):
    return "```json\n" + json.dumps({"tool": tool, "args": args}) + "\n```"


class Script:
    def __init__(self, outputs):
        self.outputs = list(outputs)

    def __call__(self, messages, schema=None):
        return self.outputs.pop(0) if self.outputs else J("task_complete", summary="ok")


def test_rollback_restores_overwrite(tmp_path):
    (tmp_path / "a.txt").write_text("ORIGINAL", encoding="utf-8")
    cp = Checkpoints(tmp_path)
    ctx = ToolContext(workspace=tmp_path, read_files={"a.txt"}, checkpoints=cp)
    WriteFile().run({"path": "a.txt", "content": "NOVO"}, ctx)
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "NOVO"
    cp.rollback(1)
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "ORIGINAL"   # voltou ao original


def test_rollback_deletes_file_that_did_not_exist(tmp_path):
    cp = Checkpoints(tmp_path)
    ctx = ToolContext(workspace=tmp_path, checkpoints=cp)
    WriteFile().run({"path": "novo.txt", "content": "x"}, ctx)
    assert (tmp_path / "novo.txt").exists()
    cp.rollback(1)
    assert not (tmp_path / "novo.txt").exists()                             # não existia antes → apagado


def test_rollback_multiple_in_reverse(tmp_path):
    cp = Checkpoints(tmp_path)
    ctx = ToolContext(workspace=tmp_path, checkpoints=cp)
    WriteFile().run({"path": "a.txt", "content": "1"}, ctx)
    ctx.read_files.add("a.txt")
    WriteFile().run({"path": "a.txt", "content": "2"}, ctx)
    cp.rollback(2)                                                          # desfaz as duas escritas
    assert not (tmp_path / "a.txt").exists()


def test_harness_writes_are_checkpointed(tmp_path):
    (tmp_path / "f.txt").write_text("antes", encoding="utf-8")
    cp = Checkpoints(tmp_path)
    outputs = [J("read_file", path="f.txt"), J("write_file", path="f.txt", content="depois"),
               J("task_complete", summary="ok")]
    t = Task(goal="edita f", exit_criteria=[{"type": "file_contains", "path": "f.txt", "text": "depois"}])
    Harness(Script(outputs), t, tmp_path, budget=Budget(), checkpoints=cp).run()
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "depois"
    cp.rollback(1)
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "antes"      # rollback após a task
