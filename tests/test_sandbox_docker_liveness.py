"""run_shell MORTO em produção: superfície exposta (Telegram) → backend 'auto' → escolhia Docker só
porque o BINÁRIO existe no PATH (`shutil.which`), sem checar se o DAEMON está no ar. Com o Docker
instalado mas parado (caso do dono, que NEM usa Docker), TODO comando virava
'Cannot connect to the Docker daemon …' e o agente ficava cego pro shell — não instalava nada.

Correção: 'auto' só vira docker se o daemon responde de VERDADE (`docker info`); senão degrada p/ local
(que é o que o comentário do código já prometia). Docker EXPLÍCITO com daemon morto → erro 126 LIMPO."""
from __future__ import annotations

import subprocess

import pytest

from okami.core.sandbox import SandboxPolicy, run_sandboxed


@pytest.fixture(autouse=True)
def _reset_daemon_cache():
    import okami.core.sandbox as sb
    sb._DAEMON_OK = None
    yield
    sb._DAEMON_OK = None


def _docker_present_daemon_dead(monkeypatch):
    """Cenário do dono: binário no PATH, daemon NÃO responde (`docker info` falha)."""
    monkeypatch.setattr("shutil.which", lambda x: "/usr/local/bin/docker")
    real_run = subprocess.run

    def fake_run(argv, *a, **k):
        if isinstance(argv, (list, tuple)) and list(argv[:2]) == ["docker", "info"]:
            return subprocess.CompletedProcess(argv, 1, "",
                                               "Cannot connect to the Docker daemon at unix:///…sock.")
        return real_run(argv, *a, **k)

    import okami.core.sandbox as sb
    monkeypatch.setattr(sb.subprocess, "run", fake_run)


def test_auto_with_dead_daemon_runs_locally(monkeypatch, tmp_path):
    """O FIX central: auto + daemon morto → run_shell roda LOCAL e funciona (não morre no Docker)."""
    _docker_present_daemon_dead(monkeypatch)
    res = run_sandboxed("echo alive", tmp_path, SandboxPolicy(backend="auto"))
    assert res.returncode == 0 and "alive" in res.output


def test_auto_backend_resolves_local_when_daemon_dead(monkeypatch):
    """effective_backend: auto + daemon morto (binário presente) → 'local', não 'docker'."""
    _docker_present_daemon_dead(monkeypatch)
    assert SandboxPolicy(backend="auto").effective_backend() == "local"


def test_auto_backend_resolves_docker_when_daemon_alive(monkeypatch):
    """Quando o daemon RESPONDE, auto continua escolhendo docker (isolamento real preservado)."""
    monkeypatch.setattr("okami.core.sandbox._docker_daemon_ok", lambda: True)
    assert SandboxPolicy(backend="auto").effective_backend() == "docker"


def test_explicit_docker_dead_daemon_gives_clean_error(monkeypatch, tmp_path):
    """Docker EXPLÍCITO (postura endurecida) com daemon morto NÃO cai no local nem cospe o erro cru
    do daemon — devolve 126 limpo dizendo que o shell está desabilitado."""
    _docker_present_daemon_dead(monkeypatch)
    res = run_sandboxed("echo hi", tmp_path, SandboxPolicy(backend="docker"))
    assert res.returncode == 126 and "desabilitado" in res.output.lower()
    assert "cannot connect to the docker daemon" not in res.output.lower()  # erro cru NÃO vaza


def test_daemon_probe_is_cached(monkeypatch):
    """O probe `docker info` roda no máximo 1x por processo (não paga ~ms em todo run_shell)."""
    monkeypatch.setattr("shutil.which", lambda x: "/usr/local/bin/docker")
    calls = {"n": 0}
    import okami.core.sandbox as sb

    def fake_run(argv, *a, **k):
        if list(argv[:2]) == ["docker", "info"]:
            calls["n"] += 1
            return subprocess.CompletedProcess(argv, 0, "", "")
        raise AssertionError("só o probe deveria rodar aqui")

    monkeypatch.setattr(sb.subprocess, "run", fake_run)
    assert sb._docker_daemon_ok() is True
    assert sb._docker_daemon_ok() is True
    assert calls["n"] == 1  # cacheado
