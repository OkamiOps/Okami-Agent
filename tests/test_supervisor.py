"""Onda 3 — supervisor multi-agente: cada agente = seu próprio gateway, supervisionado (sobe/cai/vigia).
Watchdog ressobe quem caiu. Registro durável + anti-PID-reuse. Lógica testada com spawn/liveness fakes."""
from __future__ import annotations

import okami.gateway.supervisor as sup
from okami.gateway.supervisor import AgentSupervisor


def _sup(tmp_path, agents, spawned, alive):
    """Supervisor com spawn fake (registra e devolve pid sintético) e _proc_start fake (pid em `alive`)."""
    counter = {"n": 1000}

    def fake_spawn(aid):
        counter["n"] += 1
        spawned.append(aid)
        alive.add(counter["n"])                            # nasce vivo
        return counter["n"]
    return AgentSupervisor(spawn_fn=fake_spawn, registry_path=tmp_path / "agents.json",
                           agent_ids_fn=lambda: list(agents)), counter


def _patch_liveness(monkeypatch, alive):
    # _proc_start(pid): start-time fixo se "vivo", None se "morto" → controla is_alive() determinística.
    monkeypatch.setattr(sup, "_proc_start", lambda pid: 111.0 if pid in alive else None)


def test_up_spawns_each_agent_once(tmp_path, monkeypatch):
    spawned, alive = [], set()
    s, _ = _sup(tmp_path, ["a", "b"], spawned, alive)
    _patch_liveness(monkeypatch, alive)
    s.up()
    assert sorted(spawned) == ["a", "b"]                   # subiu os dois
    st = {x["id"]: x["alive"] for x in s.status()}
    assert st == {"a": True, "b": True}
    s.up()                                                 # idempotente: já vivos → não duplica
    assert sorted(spawned) == ["a", "b"]


def test_watchdog_respawns_dead_agent(tmp_path, monkeypatch):
    spawned, alive = [], set()
    s, _ = _sup(tmp_path, ["a", "b"], spawned, alive)
    _patch_liveness(monkeypatch, alive)
    s.up()
    # 'a' morre (sai do conjunto de vivos)
    a_pid = next(p for p in alive if True)  # noqa: SIM118 — pega algum pid vivo
    # mata especificamente o pid do agente 'a'
    import json
    reg = json.loads((tmp_path / "agents.json").read_text(encoding="utf-8"))
    alive.discard(reg["a"]["pid"])
    assert s.is_alive("a") is False and s.is_alive("b") is True
    respawned = s.supervise_once()                         # watchdog
    assert [r["id"] for r in respawned] == ["a"]           # só ressubiu o que caiu
    assert s.is_alive("a") is True
    _ = a_pid


def test_stop_and_down(tmp_path, monkeypatch):
    spawned, alive = [], set()
    s, _ = _sup(tmp_path, ["a", "b"], spawned, alive)
    _patch_liveness(monkeypatch, alive)
    monkeypatch.setattr(sup, "terminate_pid", lambda pid, *a: True)
    s.up()
    assert s.stop("a") is True and s.is_alive("a") is False
    s.down()                                               # derruba o resto
    import json
    assert json.loads((tmp_path / "agents.json").read_text(encoding="utf-8")) == {}


def test_registry_durable_across_instances(tmp_path, monkeypatch):
    """O registro sobrevive — uma nova instância (restart do supervisor) enxerga quem já está vivo."""
    spawned, alive = [], set()
    s1, _ = _sup(tmp_path, ["a"], spawned, alive)
    _patch_liveness(monkeypatch, alive)
    s1.up()
    s2 = AgentSupervisor(spawn_fn=lambda aid: spawned.append(aid) or 9, registry_path=tmp_path / "agents.json",
                         agent_ids_fn=lambda: ["a"])
    assert s2.is_alive("a") is True                        # reconhece o já-vivo, não ressobe
    assert s2.supervise_once() == []
