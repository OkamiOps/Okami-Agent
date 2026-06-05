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
