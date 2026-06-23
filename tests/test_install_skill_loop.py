"""Paridade Hermes: a MESMA fonte de install_skill que já falhou NÃO é re-tentada na sessão — senão o
fetch lento/quebrado (git clone/npx sem timeout) virava loop de ~59min (transcript real do dono)."""
from __future__ import annotations

from types import SimpleNamespace

from okami.core.tools.agentic import InstallSkill
from okami.core.tools.base import ToolContext


def test_install_skill_does_not_retry_failed_source(tmp_path, monkeypatch):
    import okami.skills.install as inst
    calls = {"n": 0}

    def fake_install(*a, **k):
        calls["n"] += 1
        return SimpleNamespace(ok=False, reason="repo inexistente")

    monkeypatch.setattr(inst, "install_from_source", fake_install)
    ctx = ToolContext(workspace=tmp_path, skills_dir=str(tmp_path / "skills"))
    r1 = InstallSkill().run({"source": "ghost/repo"}, ctx)
    r2 = InstallSkill().run({"source": "ghost/repo"}, ctx)
    assert r1.ok is False and calls["n"] == 1              # 1ª tentativa roda o fetch
    assert r2.ok is False and calls["n"] == 1              # 2ª NÃO re-roda o fetch (cap anti-loop)
    assert "já falhou" in r2.output.lower()


def test_install_skill_different_source_still_tries(tmp_path, monkeypatch):
    import okami.skills.install as inst
    calls = {"n": 0}

    def fake_install(*a, **k):
        calls["n"] += 1
        return SimpleNamespace(ok=False, reason="x")

    monkeypatch.setattr(inst, "install_from_source", fake_install)
    ctx = ToolContext(workspace=tmp_path, skills_dir=str(tmp_path / "skills"))
    InstallSkill().run({"source": "a/repo"}, ctx)
    InstallSkill().run({"source": "b/repo"}, ctx)          # fonte DIFERENTE → tenta (não é o cap da mesma)
    assert calls["n"] == 2
