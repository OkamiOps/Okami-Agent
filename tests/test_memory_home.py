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


# ── extract (fim de tarefa) grava na memória RANKED, NUNCA em MEMORY.md ──────
# Doctrine (alinhada a learning.reflect): MEMORY.md só recebe fato via remember_user/remember/reflect —
# o extract mecânico de TODA tarefa era a mesma fábrica de lixo já corrigida na reflexão/skill.

class _Mem:
    def __init__(self):
        self.items = []

    def write(self, item):
        self.items.append(item)

    def recall(self, q, k=5):
        return []

    def inject(self, goal):
        return ""


def test_extract_durable_task_writes_to_ranked_memory_not_file(tmp_path):
    ws, home = _dirs(tmp_path)
    mem = _Mem()
    r = Harness(Script([J("write_file", path="a.txt", content="x"),
                        J("write_file", path="b.txt", content="y"),
                        J("task_complete", summary="criei os arquivos a.txt e b.txt como pedido"),  # nudge (WIN2)
                        J("task_complete", summary="criei os arquivos a.txt e b.txt como pedido")]),  # 2ª: aceita
                Task(goal="cria os arquivos a.txt e b.txt"), ws, budget=Budget(max_steps=6),
                memory=mem, agent_home=home).run()
    assert r.state == TaskState.COMPLETE
    assert mem.items                                     # ≥2 passos com efeito → fato durável foi p/ ranked
    assert not (home / "MEMORY.md").exists()              # NUNCA MEMORY.md (nem na casa nem no workspace)
    assert not (ws / "MEMORY.md").exists()


def test_extract_trivial_task_writes_nothing(tmp_path):
    """1 único passo com efeito não é 'trabalho durável' — não vira fato em memória alguma."""
    ws, home = _dirs(tmp_path)
    mem = _Mem()
    r = Harness(Script([J("write_file", path="a.txt", content="x"),
                        J("task_complete", summary="criei o arquivo a.txt como pedido"),  # nudge (WIN2)
                        J("task_complete", summary="criei o arquivo a.txt como pedido")]),  # 2ª: aceita
                Task(goal="cria o arquivo a.txt"), ws, budget=Budget(max_steps=6),
                memory=mem, agent_home=home).run()
    assert r.state == TaskState.COMPLETE
    assert mem.items == []                                # nada persistido (nem ranked, nem MEMORY.md)
    assert not (home / "MEMORY.md").exists()
