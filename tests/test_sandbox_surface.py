"""Sandbox ciente da superfície (#P1.1): superfície exposta endurece por padrão; CLI fica dev."""

from __future__ import annotations

from okami.core.sandbox import EXPOSED_SURFACES, effective_sandbox


def test_cli_stays_local_default():
    assert effective_sandbox({}, "cli").backend == "local"
    assert effective_sandbox(None, "").backend == "local"


def test_exposed_surface_hardens_to_auto():
    for s in ("telegram", "group", "paperclip", "api", "slack", "discord", "mattermost"):
        assert effective_sandbox({}, s).backend == "auto", s
    assert "telegram" in EXPOSED_SURFACES


def test_paperclip_roles_are_exposed():
    # #P1: o split por papel não pode deixar o worker/manager REMOTO fora do endurecimento por superfície.
    from okami.core.sandbox import is_exposed
    for s in ("paperclip-worker", "paperclip-manager", "paperclip-reviewer", "paperclip-external"):
        assert is_exposed(s), s
        assert effective_sandbox({}, s).backend == "auto", s
    assert not is_exposed("cli")


def test_explicit_backend_wins_over_surface():
    # operador pôs backend local de propósito → respeita mesmo em superfície exposta
    assert effective_sandbox({"backend": "local"}, "telegram").backend == "local"


def test_explicit_profile_wins_over_surface():
    # profile dev explícito → não endurece
    assert effective_sandbox({"profile": "dev"}, "api").backend == "local"
    # profile hardened explícito → auto (em qualquer superfície)
    assert effective_sandbox({"profile": "hardened"}, "cli").backend == "auto"


def test_auto_degrades_to_local_without_docker(monkeypatch):
    from okami.core import sandbox
    monkeypatch.setattr(sandbox.shutil, "which", lambda *_: None)   # sem docker
    p = effective_sandbox({}, "telegram")
    assert p.backend == "auto" and p.effective_backend() == "local"  # endurece, mas não quebra


def test_require_isolation_forces_docker_on_exposed():
    # #P1.2 estrito: exposto exige Docker (backend docker EXPLÍCITO → recusa se faltar, não degrada)
    p = effective_sandbox({"require_isolation": True}, "telegram")
    assert p.backend == "docker"
    assert effective_sandbox({"profile": "hardened-strict"}, "api").backend == "docker"


def test_require_isolation_does_not_brick_cli():
    # CLI = máquina do dono → não força Docker mesmo com require_isolation
    assert effective_sandbox({"require_isolation": True}, "cli").backend == "local"


def test_strict_exposed_without_docker_refuses_shell(tmp_path, monkeypatch):
    from okami.core import sandbox
    from okami.core.sandbox import run_sandboxed
    monkeypatch.setattr(sandbox.shutil, "which", lambda *_: None)   # sem docker
    pol = effective_sandbox({"require_isolation": True}, "telegram")
    res = run_sandboxed("echo oi", tmp_path, pol)
    assert res.returncode == 126 and "DESABILITADO" in res.output    # recusa, NÃO roda local
