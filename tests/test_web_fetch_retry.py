"""WebFetch numa VPS: a rede oscila e fontes com rate-limit (429/5xx) não podem matar a tarefa no 1º erro.
fetch() agora repete com backoff em erro TRANSITÓRIO e falha na hora em PERMANENTE (403/404)."""
from __future__ import annotations

import urllib.error

import okami.integrations.browser as br


class _Resp:
    def __init__(self, body=b"<html><body>conteudo ok</body></html>"):
        self._b = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n):
        return self._b


def test_fetch_retries_transient_429_then_succeeds(monkeypatch):
    calls = []

    def fake_open(url, **kw):
        calls.append(1)
        if len(calls) < 3:
            raise urllib.error.HTTPError(url, 429, "rate limited", {}, None)   # transitório 2x
        return _Resp()
    monkeypatch.setattr("okami.core.net_guard.guarded_urlopen", fake_open)
    monkeypatch.setattr(br.time, "sleep", lambda s: None)                       # sem dormir no teste
    out = br.fetch("https://example.com")
    assert "conteudo ok" in out and len(calls) == 3                             # repetiu até passar


def test_fetch_does_not_retry_permanent_403(monkeypatch):
    calls = []

    def fake_open(url, **kw):
        calls.append(1)
        raise urllib.error.HTTPError(url, 403, "forbidden", {}, None)           # permanente
    monkeypatch.setattr("okami.core.net_guard.guarded_urlopen", fake_open)
    monkeypatch.setattr(br.time, "sleep", lambda s: None)
    out = br.fetch("https://example.com")
    assert "erro" in out.lower() and len(calls) == 1                            # falhou na hora, sem repetir


def test_fetch_honors_retry_after_header(monkeypatch):
    slept = []

    def fake_open(url, **kw):
        if not slept:
            raise urllib.error.HTTPError(url, 503, "busy", {"Retry-After": "2"}, None)
        return _Resp()
    monkeypatch.setattr("okami.core.net_guard.guarded_urlopen", fake_open)
    monkeypatch.setattr(br.time, "sleep", lambda s: slept.append(s))
    br.fetch("https://example.com")
    assert slept and slept[0] == 2.0                                            # respeitou o Retry-After do servidor


def test_transient_classifier():
    import socket
    assert br._transient(urllib.error.HTTPError("u", 429, "x", {}, None))[0] is True
    assert br._transient(urllib.error.HTTPError("u", 404, "x", {}, None))[0] is False
    assert br._transient(socket.timeout())[0] is True
