"""Supervisor MULTI-AGENTE — cada agente roda como SEU PRÓPRIO gateway (Telegram/cron/heartbeat/tasks
isolados, casa própria em agents/<id>/), e o supervisor sobe/derruba/vigia todos. Se um agente cai, o
watchdog o ressobe. Registro durável em ~/.okami/runtime/agents.json (sobrevive a restart, anti-PID-reuse
via start-time). `spawn_fn` e `agent_ids_fn` são injetáveis → a lógica de ciclo de vida é testável sem
subir processo de verdade. Cross-plataforma (popen_session_kwargs / terminate_pid).
"""
from __future__ import annotations

import json
import subprocess  # nosec B404 — argv FIXO (okami gateway --agent), sem shell
import sys
import time
from pathlib import Path

from okami.core.filelock import _proc_start
from okami.core.platform_compat import popen_session_kwargs, terminate_pid


def _default_spawn(agent_id: str) -> int:
    """Sobe o gateway de UM agente como processo destacado (sobrevive ao supervisor). Devolve o pid."""
    proc = subprocess.Popen(  # nosec B603
        [sys.executable, "-m", "okami.cli", "gateway", "--foreground", "--agent", agent_id],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
        **popen_session_kwargs())
    return proc.pid


def _configured_agent_ids() -> list[str]:
    try:
        from okami.agents import load_agents
        return sorted((load_agents() or {}).keys())
    except Exception:  # noqa: BLE001
        return []


class AgentSupervisor:
    """Ciclo de vida de N gateways de agente. up/down/status + supervise_once (watchdog)."""

    def __init__(self, *, spawn_fn=None, registry_path=None, agent_ids_fn=None):
        self._spawn = spawn_fn or _default_spawn
        self._agent_ids = agent_ids_fn or _configured_agent_ids
        if registry_path is None:
            from okami.home import okami_home
            registry_path = okami_home() / "runtime" / "agents.json"
        self._reg = Path(registry_path)

    def _load(self) -> dict:
        try:
            d = json.loads(self._reg.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, reg: dict) -> None:
        try:
            self._reg.parent.mkdir(parents=True, exist_ok=True)
            self._reg.write_text(json.dumps(reg), encoding="utf-8")
        except OSError:
            pass

    def is_alive(self, agent_id: str) -> bool:
        """pid vivo E start-time bate com o registrado (anti reuso de PID)."""
        rec = self._load().get(agent_id)
        if not rec or not rec.get("pid"):
            return False
        cur = _proc_start(rec["pid"])
        return cur is not None and (rec.get("start") in (None, cur))

    def spawn(self, agent_id: str) -> dict:
        """Sobe o gateway do agente (idempotente: se já vivo, não duplica)."""
        if self.is_alive(agent_id):
            return {"id": agent_id, "already": True, **self._load().get(agent_id, {})}
        pid = self._spawn(agent_id)
        rec = {"pid": pid, "start": _proc_start(pid), "started_at": int(time.time())}
        reg = self._load()
        reg[agent_id] = rec
        self._save(reg)
        return {"id": agent_id, "already": False, **rec}

    def stop(self, agent_id: str) -> bool:
        reg = self._load()
        rec = reg.pop(agent_id, None)
        self._save(reg)
        return terminate_pid(rec["pid"]) if rec and rec.get("pid") else False

    def status(self) -> list[dict]:
        reg = self._load()
        out = []
        for aid in self._agent_ids():
            alive = self.is_alive(aid)
            rec = reg.get(aid, {})
            up = int(time.time()) - rec["started_at"] if alive and rec.get("started_at") else None
            out.append({"id": aid, "alive": alive, "pid": rec.get("pid") if alive else None, "uptime_s": up})
        return out

    def up(self) -> list[dict]:
        """Sobe TODOS os agentes configurados que não estão vivos."""
        return [self.spawn(aid) for aid in self._agent_ids()]

    def down(self) -> list[dict]:
        """Derruba todos os agentes registrados."""
        return [{"id": aid, "stopped": self.stop(aid)} for aid in list(self._load().keys())]

    def supervise_once(self) -> list[dict]:
        """Watchdog: ressobe os agentes configurados que caíram. Devolve os ressuscitados."""
        return [self.spawn(aid) for aid in self._agent_ids() if not self.is_alive(aid)]

    def supervise(self, *, interval: float = 30.0, stop=None) -> None:  # pragma: no cover - loop
        """Laço de vigia: a cada `interval`s, ressobe quem caiu. `stop` = callable que pede parada."""
        while not (stop() if callable(stop) else False):
            try:
                self.supervise_once()
            except Exception:  # noqa: BLE001 — vigia nunca morre por um erro pontual
                pass
            time.sleep(max(2.0, interval))


__all__ = ["AgentSupervisor"]
