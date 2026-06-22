"""Item 9 da revisão de harness: spawn em SEGUNDO PLANO — não trava o turno do pai. Retorna na hora;
ao terminar, persiste .okami/spawn/<id>.json e avisa o DONO no chat que pediu (notify capturado)."""
from __future__ import annotations

import json


def _ctx(tmp_path, spawn=None, notify=None):
    from okami.core.tools.base import ToolContext
    return ToolContext(workspace=tmp_path, spawn=spawn, notify=notify)


# ── núcleo síncrono (sem thread) ──
def test_run_spawn_job_persists_and_notifies(tmp_path):
    from okami.core.spawn_jobs import run_spawn_job
    notified = []
    rec = run_spawn_job("ab12", "analisar X", None, None,
                        lambda g, a, m: f"resultado de {g}", lambda m: notified.append(m), tmp_path)
    assert rec["ok"] and "resultado de analisar X" in rec["result"]
    saved = json.loads((tmp_path / ".okami" / "spawn" / "ab12.json").read_text(encoding="utf-8"))
    assert saved == rec
    assert notified and "terminou" in notified[0].lower() and "✅" in notified[0]


def test_run_spawn_job_captures_failure(tmp_path):
    from okami.core.spawn_jobs import run_spawn_job
    notified = []

    def boom(g, a, m):
        raise RuntimeError("estourou")
    rec = run_spawn_job("zz99", "tarefa", None, None, boom, lambda m: notified.append(m), tmp_path)
    assert rec["ok"] is False and "estourou" in rec["result"]
    assert notified and "❌" in notified[0]


def test_run_spawn_job_failopen_no_notify(tmp_path):
    from okami.core.spawn_jobs import run_spawn_job
    rec = run_spawn_job("nn", "t", None, None, lambda g, a, m: "ok", None, tmp_path)
    assert rec["ok"]                                          # sem notify (CLI/sem dono) → só persiste


# ── tool spawn: background não bloqueia + síncrono segue default ──
def test_spawn_tool_background_returns_immediately_and_notifies(tmp_path):
    from okami.core.tools.agentic import Spawn
    notified = []
    tool = Spawn()
    ctx = _ctx(tmp_path, spawn=lambda g, a, m: f"feito: {g}", notify=lambda m: notified.append(m) or True)
    res = tool.run({"goal": "tarefa longa", "background": True}, ctx)
    assert res.ok and "segundo plano" in res.output.lower()  # retorna NA HORA
    tool._last_bg_thread.join(timeout=5)                      # espera o worker
    files = list((tmp_path / ".okami" / "spawn").glob("*.json"))
    assert len(files) == 1 and json.loads(files[0].read_text(encoding="utf-8"))["ok"]
    assert notified and "terminou" in notified[0].lower()


def test_spawn_tool_sync_is_still_default(tmp_path):
    from okami.core.tools.agentic import Spawn
    res = Spawn().run({"goal": "x"}, _ctx(tmp_path, spawn=lambda g, a, m: "RESULTADO SINCRONO"))
    assert res.ok and "RESULTADO SINCRONO" in res.output      # sem background → inline (comportamento atual)


def test_spawn_background_needs_spawn_hook(tmp_path):
    from okami.core.tools.agentic import Spawn
    res = Spawn().run({"goal": "x", "background": True}, _ctx(tmp_path, spawn=None))
    assert res.ok is False                                    # sem ctx.spawn → indisponível
