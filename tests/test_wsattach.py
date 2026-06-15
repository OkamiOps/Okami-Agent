"""Item 8 (#8): attach a um gateway REMOTO por WebSocket — servidor + cliente sobre loopback real.

Casa com o ambiente Tailscale recém-construído: o dono abre `okami attach ws://<host>:porta/attach`
no laptop e fala com o agente rodando noutra máquina. Token obrigatório (fail-closed)."""
from __future__ import annotations

import socket
import threading

import pytest


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_handshake_headers_include_accept():
    from okami.gateway.wsattach import handshake_headers
    resp = handshake_headers("dGhlIHNhbXBsZSBub25jZQ==")
    assert b"101" in resp and b"s3pPLMBiTxaQ9kYGzzhZRbK+xOo=" in resp
    assert b"Upgrade: websocket" in resp


def test_serve_requires_token():
    from okami.gateway.wsattach import serve_ws
    with pytest.raises(Exception):
        serve_ws(_free_port(), token="", run=lambda m: m)


def test_ws_attach_roundtrip():
    from okami.gateway.wsattach import WSClient, serve_ws
    port = _free_port()
    srv = serve_ws(port, token="secret", run=lambda msg: f"echo: {msg}", host="127.0.0.1")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        c = WSClient()
        c.connect(f"ws://127.0.0.1:{port}/attach", token="secret")
        c.send("oi remoto")
        assert c.recv() == "echo: oi remoto"
        c.send("de novo")
        assert c.recv() == "echo: de novo"             # conexão persistente (multi-turno)
        c.close()
    finally:
        srv.shutdown()


def test_ws_attach_rejects_bad_token():
    from okami.gateway.wsattach import WSClient, serve_ws
    port = _free_port()
    srv = serve_ws(port, token="secret", run=lambda m: m, host="127.0.0.1")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with pytest.raises(Exception):
            WSClient().connect(f"ws://127.0.0.1:{port}/attach", token="WRONG")
    finally:
        srv.shutdown()


def test_ws_client_session_is_honored_for_resume():
    # Reconectar com o MESMO ?session=<id> → o servidor reusa o id (base do resume: a história mora
    # no run keyed por session, então reconectar retoma a conversa em vez de começar do zero).
    from okami.gateway.wsattach import WSClient, serve_ws
    port = _free_port()
    seen = []

    def run(msg, session=None):
        seen.append(session)
        return msg
    srv = serve_ws(port, token="t", run=run, host="127.0.0.1")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        c1 = WSClient()
        c1.connect(f"ws://127.0.0.1:{port}/attach?session=abc", token="t")
        c1.send("1")
        c1.recv()
        c1.close()
        c2 = WSClient()
        c2.connect(f"ws://127.0.0.1:{port}/attach?session=abc", token="t")
        c2.send("2")
        c2.recv()
        c2.close()
        assert seen == ["abc", "abc"]                  # mesma sessão entre conexões → resume
    finally:
        srv.shutdown()


def test_ws_run_receives_session_so_history_persists():
    # O `run` recebe (message, session_id) → o servidor dá um id estável por conexão (base da continuidade).
    from okami.gateway.wsattach import WSClient, serve_ws
    port = _free_port()
    seen = {}

    def run(msg, session=None):
        seen["session"] = session
        return f"[{session}] {msg}"
    srv = serve_ws(port, token="t", run=run, host="127.0.0.1")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        c = WSClient()
        c.connect(f"ws://127.0.0.1:{port}/attach", token="t")
        c.send("x")
        reply = c.recv()
        assert seen["session"] and seen["session"] in reply   # id de sessão passado ao run
        c.close()
    finally:
        srv.shutdown()
