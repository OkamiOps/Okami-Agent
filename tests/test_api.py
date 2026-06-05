"""API HTTP mínima: lógica pura, fail-closed sem token, e um round-trip real (health/401/200)."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from okami.api import handle_chat, serve


class _Task:
    result, reason = "resposta", ""
    state = type("S", (), {"value": "COMPLETE"})()
    stats = {"usage": {"input": 5}}


def test_handle_chat_pure():
    out = handle_chat({"message": "olá"}, lambda a, m: _Task())
    assert out["reply"] == "resposta" and out["state"] == "COMPLETE" and out["usage"]["input"] == 5
    assert "error" in handle_chat({"message": "   "}, lambda a, m: _Task())   # message vazio


def test_serve_fail_closed_without_token():
    with pytest.raises(RuntimeError):
        serve(0, "", lambda a, m: _Task())


def test_api_roundtrip():
    srv = serve(0, "segredo", lambda a, m: _Task())          # porta efêmera
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health") as r:
            assert json.loads(r.read())["ok"] is True
        req = urllib.request.Request(f"http://127.0.0.1:{port}/chat", data=b'{"message":"oi"}', method="POST")
        with pytest.raises(urllib.error.HTTPError) as ex:    # sem token → 401
            urllib.request.urlopen(req)
        assert ex.value.code == 401
        req.add_header("Authorization", "Bearer segredo")    # com token → 200
        with urllib.request.urlopen(req) as r:
            assert json.loads(r.read())["reply"] == "resposta"
    finally:
        srv.shutdown()
