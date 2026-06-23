"""Sandbox backend auto + docker-exigido (#4): usa Docker quando há; não cai no local inseguro."""

from __future__ import annotations

from okami.core.sandbox import SandboxPolicy, run_sandboxed


def test_auto_backend_resolves_to_docker_when_daemon_alive(monkeypatch):
    # auto → docker exige daemon NO AR (não só o binário no PATH) — ver test_sandbox_docker_liveness
    monkeypatch.setattr("okami.core.sandbox._docker_daemon_ok", lambda: True)
    assert SandboxPolicy(backend="auto").effective_backend() == "docker"


def test_auto_backend_falls_to_local_without_docker(monkeypatch):
    monkeypatch.setattr("okami.core.sandbox._docker_daemon_ok", lambda: False)
    assert SandboxPolicy(backend="auto").effective_backend() == "local"
    assert SandboxPolicy(backend="local").effective_backend() == "local"


def test_explicit_docker_without_docker_disables_shell(monkeypatch, tmp_path):
    monkeypatch.setattr("okami.core.sandbox._docker_daemon_ok", lambda: False)
    res = run_sandboxed("echo hi", tmp_path, SandboxPolicy(backend="docker"))
    assert res.returncode == 126 and "desabilitado" in res.output.lower()   # NÃO roda local inseguro


def test_local_still_runs(tmp_path):
    res = run_sandboxed("echo oi", tmp_path, SandboxPolicy(backend="local"))
    assert res.returncode == 0 and "oi" in res.output
