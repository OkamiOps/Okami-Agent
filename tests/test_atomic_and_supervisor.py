"""Caça it.2: escrita ATÔMICA de segredo/estado (sem janela world-readable nem corrupção em crash) +
supervisor.is_alive detecta morte fora do Linux (antes dava sempre-vivo no macOS/Windows)."""
from __future__ import annotations


def test_write_atomic_posix_sets_mode_and_content(tmp_path, monkeypatch):
    import okami.core.platform_compat as pc
    monkeypatch.setattr(pc, "IS_WINDOWS", False)
    monkeypatch.setattr(pc, "IS_POSIX", True)
    from okami.core.safe_io import write_atomic
    p = tmp_path / "sub" / "secret.json"
    write_atomic(p, '{"a":1}', mode=0o600)
    assert p.read_text(encoding="utf-8") == '{"a":1}'
    assert oct(p.stat().st_mode)[-3:] == "600"          # segredo restrito ao dono
    assert not list(tmp_path.rglob("*.tmp"))            # tmp limpo (sem lixo)


def test_oauth_save_tokens_atomic_0600(tmp_path, monkeypatch):
    import okami.llm.oauth as oa
    monkeypatch.setattr(oa, "STORE_DIR", tmp_path)
    monkeypatch.setattr(oa, "_store_path", lambda prov: tmp_path / f"{prov}.json")
    oa.save_tokens("anthropic", {"access": "sk-" + "FAKETOKEN"})
    f = tmp_path / "anthropic.json"
    assert f.is_file() and oct(f.stat().st_mode)[-3:] == "600"   # token nunca world-readable


def test_supervisor_is_alive_detects_death_without_proc_start(tmp_path, monkeypatch):
    import okami.gateway.supervisor as sup
    from okami.gateway.supervisor import AgentSupervisor
    monkeypatch.setattr(sup, "_proc_start", lambda pid: "")      # macOS/Windows: sem start-time
    alive = {42}
    monkeypatch.setattr(sup, "_pid_alive", lambda pid: pid in alive)
    s = AgentSupervisor(spawn_fn=lambda aid: 42, registry_path=tmp_path / "a.json", agent_ids_fn=lambda: ["x"])
    s.spawn("x")
    assert s.is_alive("x") is True
    alive.discard(42)                                   # processo morre
    assert s.is_alive("x") is False                     # detecta (antes: sempre True fora do Linux)
