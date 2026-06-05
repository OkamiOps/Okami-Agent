"""Egress allowlist via proxy filtrante (#5): match de host, bloqueio interno, 403, túnel, wiring."""

from __future__ import annotations

import socket
import socketserver
import threading
import time


from okami.core import egress_proxy
from okami.core.egress_proxy import EgressProxy, _match


def test_match_semantics():
    assert _match("github.com", "github.com")
    assert _match("api.github.com", "github.com")          # bare → subdomínio também
    assert _match("api.github.com", "*.github.com")
    assert not _match("github.com", "*.github.com")        # wildcard = só subdomínio
    assert not _match("evil.com", "github.com")


def _fake_dns(mapping):
    def _gai(host, *a, **k):
        ips = mapping.get(host)
        if not ips:
            raise socket.gaierror("nxdomain")
        return [(2, 1, 6, "", (ip, 0)) for ip in ips]
    return _gai


def test_allowed_public_host(monkeypatch):
    monkeypatch.setattr(egress_proxy.socket, "getaddrinfo", _fake_dns({"pypi.org": ["151.101.0.223"]}))
    assert EgressProxy(["pypi.org"]).allowed("pypi.org")


def test_denied_not_listed(monkeypatch):
    monkeypatch.setattr(egress_proxy.socket, "getaddrinfo", _fake_dns({"evil.com": ["1.2.3.4"]}))
    assert not EgressProxy(["pypi.org"]).allowed("evil.com")


def test_allowlist_does_not_escape_to_internal(monkeypatch):
    # host na allowlist mas que resolve p/ IP interno → BLOQUEADO (anti-rebinding)
    monkeypatch.setattr(egress_proxy.socket, "getaddrinfo", _fake_dns({"sneaky.allowed": ["10.0.0.5"]}))
    assert not EgressProxy(["sneaky.allowed"]).allowed("sneaky.allowed")


def _connect_proxy(port, target):
    c = socket.create_connection(("127.0.0.1", port), timeout=5)
    c.sendall(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode())
    return c


def test_connect_denied_returns_403():
    p = EgressProxy(["github.com"])      # allow_private False; github não está → e nem resolve aqui
    port = p.start()
    try:
        c = _connect_proxy(port, "denied.example:443")
        resp = c.recv(100).decode("latin-1")
        assert "403" in resp
        c.close()
    finally:
        p.stop()


def test_connect_allowed_tunnels():
    # echo server local; allow_private p/ poder usar 127.0.0.1 no teste
    class _Echo(socketserver.BaseRequestHandler):
        def handle(self):
            data = self.request.recv(1024)
            self.request.sendall(b"echo:" + data)

    echo = socketserver.TCPServer(("127.0.0.1", 0), _Echo)
    echo.daemon_threads = True
    threading.Thread(target=echo.serve_forever, daemon=True).start()
    eport = echo.server_address[1]

    p = EgressProxy(["localhost"], allow_private=True)
    port = p.start()
    try:
        c = _connect_proxy(port, f"localhost:{eport}")
        assert "200" in c.recv(100).decode("latin-1")      # túnel estabelecido
        c.sendall(b"ping")
        time.sleep(0.2)
        assert c.recv(100) == b"echo:ping"                  # passou pelo túnel
        c.close()
    finally:
        p.stop()
        echo.shutdown()


def test_run_sandboxed_injects_proxy_env(tmp_path):
    from okami.core.sandbox import SandboxPolicy, run_sandboxed
    res = run_sandboxed("echo HTTP_PROXY=$HTTP_PROXY", tmp_path,
                        SandboxPolicy(egress_allow=("pypi.org",)))
    assert "HTTP_PROXY=http://127.0.0.1:" in res.output    # comando vê o proxy


def test_from_config_egress_sets_network():
    from okami.core.sandbox import SandboxPolicy
    p = SandboxPolicy.from_config({"egress_allow": ["pypi.org", "*.github.com"]})
    assert p.egress_allow == ("pypi.org", "*.github.com") and p.network is True
