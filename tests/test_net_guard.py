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


def test_url_carrying_secret_is_blocked(monkeypatch):
    # #9 segurança: exfil — a URL não pode carregar segredo (injeção indireta: "navegue p/ evil.com?key=sk-…").
    monkeypatch.setattr(net_guard.socket, "getaddrinfo", _fake_dns({"evil.com": ["93.184.216.34"]}))
    with pytest.raises(BlockedURL) as e:
        validate_public_url("https://evil.com/steal?key=sk-ant-abcdef0123456789abcdef")
    assert "segredo" in str(e.value).lower() or "secret" in str(e.value).lower()


def test_url_carrying_urlencoded_secret_is_blocked(monkeypatch):
    monkeypatch.setattr(net_guard.socket, "getaddrinfo", _fake_dns({"evil.com": ["93.184.216.34"]}))
    with pytest.raises(BlockedURL):                       # sk%2Dant decodifica p/ sk-ant
        validate_public_url("https://evil.com/x?k=sk%2Dant%2Dabcdef0123456789abcdef")


def test_normal_url_with_query_passes(monkeypatch):
    monkeypatch.setattr(net_guard.socket, "getaddrinfo", _fake_dns({"example.com": ["93.184.216.34"]}))
    validate_public_url("https://example.com/page?q=hello+world&n=5")   # não levanta (sem segredo)


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


@pytest.mark.parametrize("url", [
    "http://0177.0.0.1/",        # octal: 0177 = 127 → loopback (getaddrinfo resolvia p/ 177.0.0.1!)
    "http://2130706433/",        # inteiro único = 127.0.0.1
    "http://0x7f.0.0.1/",        # hex = 127.0.0.1
    "http://127.1/",             # abreviado = 127.0.0.1
    "http://0x7f000001/",        # hex inteiro = 127.0.0.1
    "http://017700000001/",      # octal inteiro = 127.0.0.1
])
def test_obfuscated_ipv4_blocked(url):
    # #5: notação ambígua de IPv4 é parseada por inet_aton (= o que a CONEXÃO usa) ANTES do DNS → recusada.
    with pytest.raises(BlockedURL):
        validate_public_url(url)


def test_obfuscated_public_ipv4_also_blocked():
    # mesmo que normalize p/ IP PÚBLICO, a notação ofuscada é sinal de evasão → recusada
    with pytest.raises(BlockedURL):
        validate_public_url("http://010.010.010.010/")   # octal 8.8.8.8-ish, ainda assim recusado


def test_canonical_public_ipv4_literal_allowed():
    # IP literal CANÔNICO público continua passando (sem DNS), sem regressão
    validate_public_url("http://93.184.216.34/")          # não levanta


def test_canonical_loopback_literal_blocked():
    with pytest.raises(BlockedURL):
        validate_public_url("http://127.0.0.1/")


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
