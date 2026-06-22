"""Subagente em SEGUNDO PLANO + camada de leitura/gestão (revisão de subagente vs Hermes).

`spawn(background=true)` roda o subagente FORA do turno do pai. O Hermes empurra a conclusão por uma
fila global + turno forjado (acoplado ao gateway, desligado em sessão stateless); aqui o caminho é mais
simples e soberano: o resultado vira um REGISTRO durável em `.okami/spawn/<id>.json` (com estado
running→done/failed), o DONO é avisado por `ctx.notify` (chat certo), e o AGENTE pai lê o resultado de
volta pela tool `spawn_jobs` (status/result/list/await) — fechando o loop sem máquina de fila.

`run_spawn_job` é SÍNCRONO e puro (a thread mora na tool) → testável sem concorrência. Tudo fail-open.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

_JOB_RE = re.compile(r"^[0-9a-f]{8}$")             # id = 8 hex → jail contra traversal na leitura
_MAX_BG = max(1, int(os.environ.get("OKAMI_MAX_BACKGROUND", "3") or 3))
_BG_SEM = threading.BoundedSemaphore(_MAX_BG)      # cap de concorrência (modelo local satura GPU)


def new_job_id() -> str:
    import uuid
    return uuid.uuid4().hex[:8]


def spawn_dir(workspace) -> Path:
    d = Path(workspace or ".") / ".okami" / "spawn"
    d.mkdir(parents=True, exist_ok=True)
    return d


def acquire_slot() -> bool:
    """Pega uma vaga de background (NÃO-bloqueante). False = fila cheia → o caller roda inline (síncrono)."""
    return _BG_SEM.acquire(blocking=False)


def release_slot() -> None:
    try:
        _BG_SEM.release()
    except ValueError:                             # release sem acquire — inócuo
        pass


def _write(workspace, record: dict) -> None:
    try:
        (spawn_dir(workspace) / f"{record['job']}.json").write_text(
            json.dumps(record, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def run_spawn_job(job, goal, agent, model, spawn_fn, notify, workspace) -> dict:
    """Roda UM subagente: grava 'running' ANTES, sobrescreve com o estado terminal + resultado no fim, e
    avisa o dono. SÍNCRONO (a thread mora na tool). Nunca levanta (fail-open: erro → state='failed')."""
    started = time.time()
    _write(workspace, {"job": job, "goal": goal, "state": "running", "started_at": started})
    try:
        result = str(spawn_fn(goal, agent, model))
        ok = True
    except Exception as e:  # noqa: BLE001 — falha do subagente não derruba a thread
        result, ok = f"falhou: {e}", False
    record = {"job": job, "goal": goal, "ok": ok, "state": "done" if ok else "failed",
              "result": result, "started_at": started, "finished_at": time.time()}
    _write(workspace, record)
    if callable(notify):
        try:
            head = "✅" if ok else "❌"
            notify(f"{head} subagente {job} terminou ({str(goal)[:60]}):\n{result[:1500]}")
        except Exception:  # noqa: BLE001 — aviso é best-effort
            pass
    return record


def read_job(workspace, job) -> dict | None:
    """Lê o registro de um job, JAILED (id = 8 hex, sem traversal). None se id inválido/inexistente."""
    job = str(job or "").strip()
    if not _JOB_RE.match(job):
        return None
    f = spawn_dir(workspace) / f"{job}.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None
    except (OSError, ValueError):
        return None


def list_jobs(workspace) -> list[dict]:
    """Jobs (mais recentes primeiro) com {job, goal, state}."""
    out = []
    for f in sorted(spawn_dir(workspace).glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"job": r.get("job", f.stem), "goal": r.get("goal", ""), "state": r.get("state", "?")})
    return out


def await_job(workspace, job, timeout: float = 60.0):
    """Espera (poll) o job sair de 'running' até `timeout` (cap 300s). Devolve o registro terminal, ou o
    último estado (running) se estourar. Bloqueia SÓ este turno (a tool tampa o timeout)."""
    deadline = time.time() + max(1.0, min(float(timeout or 60), 300.0))
    rec = read_job(workspace, job)
    while rec is not None and rec.get("state") == "running" and time.time() < deadline:
        time.sleep(0.2)
        rec = read_job(workspace, job)
    return rec


def prune_spawn_jobs(workspace, keep: int = 50, max_age_days: float = 7.0) -> int:
    """GC: remove jobs além de `keep` (mais antigos) E mais velhos que `max_age_days`. Mesma higiene do
    BackgroundRegistry.prune. Devolve nº removido."""
    files = sorted(spawn_dir(workspace).glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    cutoff = time.time() - max_age_days * 86400
    removed = 0
    for i, f in enumerate(files):
        try:
            if i >= keep or f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        except OSError:
            continue
    return removed


__all__ = ["new_job_id", "spawn_dir", "acquire_slot", "release_slot", "run_spawn_job",
           "read_job", "list_jobs", "await_job", "prune_spawn_jobs"]
