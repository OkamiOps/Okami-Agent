"""Sweep Hermes — mini-onda de confiabilidade (#44 cadeia de exceção, #27 payload do after_tool, #8 cron headless)."""
from __future__ import annotations

from okami.automation.scheduler import CRON_HEADLESS_PREAMBLE, headless_prompt
from okami.core import Harness, Task
from okami.core.tools.base import ToolResult
from okami.llm.errors import classify


# ---------------------------------------------------------------- #44 cadeia de exceção
def test_status_walks_cause_chain():
    inner = Exception("boom")
    inner.status_code = 429                              # status real escondido no __cause__
    outer = Exception("litellm wrapper")
    outer.__cause__ = inner
    assert classify(outer).reason == "rate_limit"


# ---------------------------------------------------------------- #27 after_tool com args+output
def test_after_tool_hook_gets_args_and_output(tmp_path):
    seen = {}

    class _Hooks:
        def fire(self, event, payload):
            if event == "after_tool":
                seen.update(payload)
            return True

    (tmp_path / "a.txt").write_text("conteúdo", encoding="utf-8")
    h = Harness(generate=lambda *a, **k: "", task=Task(goal="x"), workspace=tmp_path, hooks=_Hooks())
    h._handle_tool_result(h.task, 0, __import__("okami.core.harness.parsing", fromlist=["Action"]).Action(
        "read_file", {"path": "a.txt"}), ToolResult(True, "saída lida", effect=False))
    assert seen.get("tool") == "read_file" and seen.get("args") == {"path": "a.txt"}
    assert seen.get("output") == "saída lida" and seen.get("out_chars") == len("saída lida")


# ---------------------------------------------------------------- #8 cron headless
def test_headless_prompt_prepends_once():
    out = headless_prompt("faça o relatório diário")
    assert out.startswith(CRON_HEADLESS_PREAMBLE) and "relatório diário" in out
    assert headless_prompt(out) == out                   # idempotente (não duplica o preâmbulo)
