"""Paridade Hermes (terminal VIVO): o harness anuncia a tool ANTES de rodá-la (tool_start), pra a TUI
mostrar spinner + relógio enquanto executa — não só o ✓/✗ depois que termina."""
from __future__ import annotations

from okami.core import Harness, Task
from okami.llm.usage import Completion


def test_emits_tool_start_before_step(tmp_path):
    (tmp_path / "a.txt").write_text("conteúdo", encoding="utf-8")
    calls = {"n": 0}

    def gen(messages, schema=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return Completion(text="", tool_calls=[
                {"id": "c1", "name": "read_file", "arguments": '{"path":"a.txt"}'}])
        return Completion(text="", tool_calls=[
            {"id": "c2", "name": "task_complete", "arguments": '{"summary":"ok"}'}])

    events = []
    h = Harness(gen, Task(goal="leia a.txt"), tmp_path, on_event=lambda e: events.append(e))
    h.run()
    kinds = [e["kind"] for e in events]
    assert "tool_start" in kinds                                  # anunciou ANTES de rodar
    assert kinds.index("tool_start") < kinds.index("step")       # start vem antes do step (resultado)
    ts = next(e for e in events if e["kind"] == "tool_start")
    assert ts["tool"] == "read_file"                             # carrega o nome da tool
    assert ts.get("args", {}).get("path") == "a.txt"            # e os args (p/ o preview vivo)
