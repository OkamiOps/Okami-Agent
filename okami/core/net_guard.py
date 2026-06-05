"""Guarda anti-SSRF p/ URLs controladas pelo usuário/modelo (#6).

Toda URL que vem de FORA (o `@https://…` do usuário, o `browse` do modelo) é hostil até prova em
contrário. Antes de buscar QUALQUER uma delas, valida:
- esquema: só `http`/`https` (bloqueia file://, gopher://, ftp://…);
- host: resolve via getaddrinfo e RECUSA se QUALQUER IP cair em faixa não-roteável —
  loopback (127/8, ::1), privada (10/8, 172.16/12, 192.168/16, fc00::/7), link-local
  (169.254/16 → metadata de nuvem 169.254.169.254, fe80::/10), reservada, multicast;
- redirect: segue só p/ destino que TAMBÉM passa na validação (evita 302→rede interna);
- IPv6-mapeado (::ffff:127.0.0.1) é desmascarado e validado como IPv4.

getaddrinfo normaliza formas ofuscadas (decimal `2130706433`, hex `0x7f.1`, `[::1]`) p/ o IP real,
então elas caem no mesmo filtro. DNS-rebinding TOCTOU puro (o resolver muda ENTRE validar e conectar)
fica fora do escopo — exigiria fixar a conexão no IP validado e quebraria SNI/TLS; mitigado na prática
por validar a origem E revalidar cada redirect. `allow_private=True` é o opt-in explícito (dev local).
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.request
from urllib.parse import urlparse


class BlockedURL(ValueError):
    """URL recusada pela guarda anti-SSRF (esquema proibido, host não-roteável, ou DNS sem resposta)."""


def _ip_blocked(ip: str) -> bool:
    """True se `ip` NÃO for um endereço público roteável (fail-closed: não parseou → bloqueia)."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped                     # ::ffff:127.0.0.1 → 127.0.0.1
    return (addr.is_loopback or addr.is_private or addr.is_link_local or addr.is_reserved
            or addr.is_multicast or addr.is_unspecified or not addr.is_global)


def _resolve_ips(host: str, port: int) -> list[str]:
    """Todos os IPs (A/AAAA) que o host resolve. Vazio → DNS falhou (caller bloqueia)."""
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, OSError, UnicodeError):
        return []
    return [sockaddr[0] for *_, sockaddr in infos]


def validate_public_url(url: str, *, allow_private: bool = False) -> None:
    """Levanta BlockedURL se a URL não for http(s) pública. `allow_private` libera rede interna (dev)."""
    u = urlparse(url)
    if u.scheme not in ("http", "https"):
        raise BlockedURL(f"esquema não permitido: {u.scheme or '(vazio)'}:// — só http/https")
    host = u.hostname
    if not host:
        raise BlockedURL("URL sem host")
    if allow_private:
        return
    port = u.port or (443 if u.scheme == "https" else 80)
    ips = _resolve_ips(host, port)
    if not ips:
        raise BlockedURL(f"host não resolveu: {host}")
    for ip in ips:
        if _ip_blocked(ip):
            raise BlockedURL(f"host {host} → {ip} é rede interna/não-roteável (SSRF bloqueado)")


class _GuardedRedirect(urllib.request.HTTPRedirectHandler):
    """Revalida cada destino de redirect — um 302 não pode escapar p/ rede interna."""

    def __init__(self, allow_private: bool):
        super().__init__()
        self.allow_private = allow_private

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_public_url(newurl, allow_private=self.allow_private)   # levanta BlockedURL → aborta o fetch
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def guarded_urlopen(url: str, *, timeout: float = 15.0, allow_private: bool = False,
                    headers: dict | None = None):
    """urlopen com validação anti-SSRF na origem E em cada redirect. Levanta BlockedURL se hostil."""
    validate_public_url(url, allow_private=allow_private)
    req = urllib.request.Request(url, headers=headers or {})
    opener = urllib.request.build_opener(_GuardedRedirect(allow_private))
    return opener.open(req, timeout=timeout)        # noqa: S310 — validado acima
