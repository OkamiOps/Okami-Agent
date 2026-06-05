"""Guarda anti-SSRF (#6): valida esquema + resolve host + bloqueia rede interna + redirect."""

from __future__ import annotations

import pytest

from okami.core import net_guard
from okami.core.net_guard import BlockedURL, _ip_blocked, validate_public_url


def _fake_dns(mapping):
    """Substitui getaddrinfo: {host: [ips]} (host desconhecido → não resolve)."""
    def _gai(host, port, *a, **k):
        ips = mapping.get(host)
        if not ips:
            import socket
            raise socket.gaierror(f"sem resolução p/ {host}")
        return [(2, 1, 6, "", (ip, port)) for ip in ips]
    return _gai


@pytest.mark.parametrize("ip", [
    "127.0.0.1", "0.0.0.0", "10.1.2.3", "172.16.0.5", "192.168.1.1",
    "169.254.169.254",                      # metadata de nuvem (AWS/GCP)
    "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1",   # IPv6 loopback/link-local/ULA/mapeado
])
def test_internal_ips_blocked(ip):
    assert _ip_blocked(ip) is True


@pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"])
def test_public_ips_allowed(ip):
    assert _ip_blocked(ip) is False


def test_bad_string_blocked():
    assert _ip_blocked("not-an-ip") is True       # fail-closed


def test_scheme_must_be_http(monkeypatch):
    monkeypatch.setattr(net_guard.socket, "getaddrinfo", _fake_dns({"example.com": ["93.184.216.34"]}))
    for bad in ("file:///etc/passwd", "gopher://x/", "ftp://host/f"):
        with pytest.raises(BlockedURL):
            validate_public_url(bad)


def test_localhost_name_blocked(monkeypatch):
    monkeypatch.setattr(net_guard.socket, "getaddrinfo", _fake_dns({"localhost": ["127.0.0.1"]}))
    with pytest.raises(BlockedURL):
        validate_public_url("http://localhost:8080/admin")


def test_metadata_endpoint_blocked(monkeypatch):
    monkeypatch.setattr(net_guard.socket, "getaddrinfo", _fake_dns({"metadata": ["169.254.169.254"]}))
    with pytest.raises(BlockedURL):
        validate_public_url("http://metadata/latest/meta-data/")


def test_rebinding_name_resolving_to_private_blocked(monkeypatch):
    # nome "público" que resolve p/ IP interno → bloqueado (resolve-then-validate)
    monkeypatch.setattr(net_guard.socket, "getaddrinfo", _fake_dns({"evil.example": ["10.0.0.7"]}))
    with pytest.raises(BlockedURL):
        validate_public_url("https://evil.example/")


def test_public_host_allowed(monkeypatch):
    monkeypatch.setattr(net_guard.socket, "getaddrinfo", _fake_dns({"example.com": ["93.184.216.34"]}))
    validate_public_url("https://example.com/page")          # não levanta


def test_unresolvable_host_blocked(monkeypatch):
    monkeypatch.setattr(net_guard.socket, "getaddrinfo", _fake_dns({}))
    with pytest.raises(BlockedURL):
        validate_public_url("https://does-not-exist.invalid/")


def test_allow_private_opt_in(monkeypatch):
    # dev local: allow_private pula a checagem de IP (mas mantém o esquema)
    validate_public_url("http://localhost:4480/v1", allow_private=True)
    with pytest.raises(BlockedURL):
        validate_public_url("file:///etc/passwd", allow_private=True)   # esquema ainda barra


def test_references_fetch_blocks_internal(monkeypatch):
    # o @url do usuário não pode bater em rede interna
    monkeypatch.setattr(net_guard.socket, "getaddrinfo", _fake_dns({"localhost": ["127.0.0.1"]}))
    from okami.integrations.references import _fetch_url
    out = _fetch_url("http://localhost:9999/secret")
    assert "recusada" in out.lower()
