"""Memória/identidade escrevem na CASA do agente — nunca no workspace/CWD.

Bug real: MEMORY.md apareceu jogado em ~/ (raiz da home do Marcos). O runner LIA a
identidade da agent_home, mas as ESCRITAS (extract → append_fact, remember_user,
finish_setup) usavam ctx.workspace — que no CLI é o CWD. Casa do agente
(~/.okami/agents/<id>/) é onde memória/identidade moram; workspace é onde ele MEXE.
"""
from __future__ import annotations

import json

from okami.core import Budget, Harness, Task, TaskState
from okami.core.tools.base import ToolContext
from okami.core.tools.memory import FinishSetup, RememberUser


def J(tool, **args):
    return "```json\n" + json.dumps({"tool": tool, "args": args}) + "\n```"


class Script:
    def __init__(self, outputs):
        self.outputs = list(outputs)

    def __call__(self, messages, schema=None):
        return self.outputs.pop(0) if self.outputs else "(sem ação)"


def _dirs(tmp_path):
    ws = tmp_path / "projeto"
    home = tmp_path / "casa"
    ws.mkdir(), home.mkdir()
    return ws, home


# ── ToolContext.home: agent_home quando setado, workspace como fallback ─────

def test_ctx_home_falls_back_to_workspace(tmp_path):
    ws, home = _dirs(tmp_path)
    assert ToolContext(workspace=ws).home == ws
    assert ToolContext(workspace=ws, agent_home=home).home == home


# ── remember_user / finish_setup escrevem na CASA ───────────────────────────

def test_remember_user_writes_to_agent_home(tmp_path):
    ws, home = _dirs(tmp_path)
    ctx = ToolContext(workspace=ws, agent_home=home)
    assert RememberUser().run({"text": "prefere respostas curtas"}, ctx).ok
    assert (home / "USER.md").exists()
    assert not (ws / "USER.md").exists()                # nada vaza pro workspace/CWD


def test_finish_setup_seals_genesis_in_home(tmp_path):
    ws, home = _dirs(tmp_path)
    ctx = ToolContext(workspace=ws, agent_home=home)
    assert FinishSetup().run({"about_user": "Marcos, dev"}, ctx).ok
    assert (home / ".okami" / "genesis.done").exists()
    assert (home / "USER.md").exists()
    assert not (ws / ".okami").exists() and not (ws / "USER.md").exists()


# ── extract (fim de tarefa) grava MEMORY.md na CASA ─────────────────────────

class _Mem:
    def __init__(self):
        self.items = []

    def write(self, item):
        self.items.append(item)

    def recall(self, q, k=5):
        return []

    def inject(self, goal):
        return ""


def test_extract_writes_memory_md_to_home(tmp_path):
    ws, home = _dirs(tmp_path)
    r = Harness(Script([J("write_file", path="a.txt", content="x"),
                        J("task_complete", summary="criei o arquivo a.txt como pedido")]),
                Task(goal="cria o arquivo a.txt"), ws, budget=Budget(max_steps=6),
                memory=_Mem(), agent_home=home).run()
    assert r.state == TaskState.COMPLETE
    assert (home / "MEMORY.md").exists()                # fato na casa do agente
    assert not (ws / "MEMORY.md").exists()              # NÃO no workspace (era o bug: ~/MEMORY.md)


def test_extract_without_home_keeps_workspace_backcompat(tmp_path):
    ws = tmp_path / "só-ws"
    ws.mkdir()
    r = Harness(Script([J("write_file", path="a.txt", content="x"),
                        J("task_complete", summary="criei o arquivo a.txt")]),
                Task(goal="cria o arquivo a.txt"), ws, budget=Budget(max_steps=6),
                memory=_Mem()).run()
    assert r.state == TaskState.COMPLETE
    assert (ws / "MEMORY.md").exists()                  # sem agent_home → comportamento antigo
