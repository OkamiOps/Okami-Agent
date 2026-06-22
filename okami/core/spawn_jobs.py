"""Subagente em SEGUNDO PLANO (item 9 da revisão de harness): roda o spawn FORA do turno do pai, persiste
o resultado e avisa o dono no chat certo quando termina — em vez de travar o canal por 5-25 min.

Separado da tool de propósito: `run_spawn_job` é SÍNCRONO e puro (testável sem thread); a tool é que cria
a thread daemon. O `notify` é capturado no momento do spawn (closure sobre o chat_id daquele turno) → o
aviso de conclusão vai pro chat que PEDIU, não pro último chat global.
"""
from __future__ import annotations

import json
from pathlib import Path


def new_job_id() -> str:
    import uuid
    return uuid.uuid4().hex[:8]


def spawn_dir(workspace) -> Path:
    d = Path(workspace or ".") / ".okami" / "spawn"
    d.mkdir(parents=True, exist_ok=True)
    return d


def run_spawn_job(job, goal, agent, model, spawn_fn, notify, workspace) -> dict:
    """Roda UM subagente até o fim, persiste {job,goal,ok,result} em .okami/spawn/<job>.json e avisa o
    dono (notify). NUNCA levanta (fail-open: erro do subagente vira ok=False com a mensagem). Devolve o
    registro persistido."""
    try:
        result = str(spawn_fn(goal, agent, model))
        ok = True
    except Exception as e:  # noqa: BLE001 — falha do subagente não derruba a thread; vira resultado
        result, ok = f"falhou: {e}", False
    record = {"job": job, "goal": goal, "ok": ok, "result": result}
    try:
        (spawn_dir(workspace) / f"{job}.json").write_text(
            json.dumps(record, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    if callable(notify):
        try:
            head = "✅" if ok else "❌"
            notify(f"{head} subagente {job} terminou ({str(goal)[:60]}):\n{result[:1500]}")
        except Exception:  # noqa: BLE001 — aviso é best-effort (não pode derrubar a thread)
            pass
    return record


__all__ = ["new_job_id", "spawn_dir", "run_spawn_job"]
