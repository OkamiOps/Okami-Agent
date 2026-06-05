"""Sandbox backend auto + docker-exigido (#4): usa Docker quando há; não cai no local inseguro."""

from __future__ import annotations

from okami.core.sandbox import SandboxPolicy, run_sandboxed


def test_auto_backend_resolves_to_docker_when_present(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/docker")
    assert SandboxPolicy(backend="auto").effective_backend() == "docker"


def test_auto_backend_falls_to_local_without_docker(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda x: None)
    assert SandboxPolicy(backend="auto").effective_backend() == "local"
    assert SandboxPolicy(backend="local").effective_backend() == "local"


def test_explicit_docker_without_docker_disables_shell(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda x: None)
    res = run_sandboxed("echo hi", tmp_path, SandboxPolicy(backend="docker"))
    assert res.returncode == 126 and "desabilitado" in res.output.lower()   # NÃO roda local inseguro


def test_local_still_runs(tmp_path):
    res = run_sandboxed("echo oi", tmp_path, SandboxPolicy(backend="local"))
    assert res.returncode == 0 and "oi" in res.output
