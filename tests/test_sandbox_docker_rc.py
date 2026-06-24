"""sandbox (hunt#2): _ensure_container ignorava o returncode do docker (ps/start/run). Daemon fora ou
`docker run` que falha (rc!=0) sem exceção → a função devolvia True → o `docker exec` seguinte estourava em
container inexistente. Agora só devolve True se o comando relevante REALMENTE deu 0."""
from __future__ import annotations

from types import SimpleNamespace

import okami.core.sandbox as sb


def _runner(seq):
    state = {"i": 0}

    def fake(argv, **kw):
        rc, out = seq[state["i"]] if state["i"] < len(seq) else (0, "")
        state["i"] += 1
        return SimpleNamespace(returncode=rc, stdout=out, stderr="")
    return fake


def test_daemon_error_returns_false(monkeypatch, tmp_path):
    monkeypatch.setattr(sb.subprocess, "run", _runner([(1, "")]))      # docker ps falha (daemon fora)
    assert sb._ensure_container("c", tmp_path, object()) is False


def test_running_container_returns_true(monkeypatch, tmp_path):
    monkeypatch.setattr(sb.subprocess, "run", _runner([(0, "abc123")]))   # já no ar
    assert sb._ensure_container("c", tmp_path, object()) is True


def test_run_failure_returns_false(monkeypatch, tmp_path):
    monkeypatch.setattr(sb, "docker_run_persistent_argv", lambda *a, **k: ["docker", "run"])
    monkeypatch.setattr(sb.subprocess, "run",
                        _runner([(0, ""), (0, ""), (1, "")]))   # ps vazio, ps -aq vazio, RUN FALHA
    assert sb._ensure_container("c", tmp_path, object()) is False


def test_fresh_run_ok_returns_true(monkeypatch, tmp_path):
    monkeypatch.setattr(sb, "docker_run_persistent_argv", lambda *a, **k: ["docker", "run"])
    monkeypatch.setattr(sb.subprocess, "run",
                        _runner([(0, ""), (0, ""), (0, "newid")]))   # sobe limpo (rc 0)
    assert sb._ensure_container("c", tmp_path, object()) is True
