"""#18 cliente LSP PERSISTENTE — reusa o server vivo entre edições (vs one-shot)."""
from __future__ import annotations

import sys
from pathlib import Path

from okami.lsp.client import PersistentLspClient

_MOCK = str(Path(__file__).parent / "lsp_mock_server.py")


def _spawn_mock(tmp_path) -> PersistentLspClient:
    return PersistentLspClient.spawn(sys.executable, (_MOCK,), str(tmp_path))


def test_persistent_client_diagnoses_and_reuses_process(tmp_path):
    client = _spawn_mock(tmp_path)
    assert client is not None
    try:
        uri = (tmp_path / "a.py").resolve().as_uri()
        pid1 = client.pid()
        d1 = client.diagnose(uri, "linha ok\noutra", timeout=6)   # didOpen → 0 erros
        assert d1 == []
        d2 = client.diagnose(uri, "BUG_SENTINEL aqui", timeout=6)  # didChange → 1 erro (MESMO server)
        assert len(d2) == 1 and d2[0]["code"] == "MOCK001"
        assert client.pid() == pid1                                # processo REUSADO (não recriou)
    finally:
        client.close()


def test_persistent_client_close_terminates(tmp_path):
    client = _spawn_mock(tmp_path)
    assert client is not None
    client.close()
    # depois de close, diagnose não levanta (devolve [] — server morto)
    assert client.diagnose((tmp_path / "x.py").resolve().as_uri(), "BUG_SENTINEL", timeout=2) == []


def test_pool_reuses_client_across_paths(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from okami.lsp import pool as _pool
    # finge um servidor 'mock' que cobre .py, sempre disponível, raiz = tmp (com .git)
    (tmp_path / ".git").mkdir()
    fake = SimpleNamespace(id="mock", binary=sys.executable, args=(_MOCK,), extensions=(".py",),
                           languages=("python",))
    monkeypatch.setattr(_pool, "server_for_path", lambda p: fake if p.endswith(".py") else None)
    monkeypatch.setattr(_pool, "binary_available", lambda s: True)
    p = _pool.LspPool()
    try:
        d1 = p.diagnose_path(tmp_path, "a.py", "ok")
        d2 = p.diagnose_path(tmp_path, "b.py", "BUG_SENTINEL")
        assert d1 == [] and len(d2) == 1
        assert p.live_count() == 1                                 # 1 server vivo serviu os 2 arquivos
    finally:
        p.shutdown()
        assert p.live_count() == 0


def test_pool_off_outside_git(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from okami.lsp import pool as _pool
    fake = SimpleNamespace(id="mock", binary=sys.executable, args=(_MOCK,), extensions=(".py",),
                           languages=("python",))
    monkeypatch.setattr(_pool, "server_for_path", lambda p: fake)
    monkeypatch.setattr(_pool, "binary_available", lambda s: True)
    p = _pool.LspPool()                                            # tmp_path SEM .git
    assert p.diagnose_path(tmp_path, "a.py", "BUG_SENTINEL") == [] # gateado off → não sobe daemon
    assert p.live_count() == 0
