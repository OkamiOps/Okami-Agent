"""Proxy de EGRESS com allowlist (#5 — egress allowlist real).

`--network none` é tudo-ou-nada. Quando o sandbox precisa de rede MAS só p/ destinos específicos
(ex.: `pypi.org`, `*.github.com`), este proxy filtrante é o mecanismo: um forward-proxy local que
só deixa passar host na allowlist (exato, subdomínio, ou wildcard `*.dominio`) E cujo IP resolvido
NÃO seja interno (reusa a guarda anti-SSRF do net_guard — a allowlist não vira porta dos fundos p/
a rede interna). Suporta CONNECT (túnel HTTPS) e GET/POST http simples.

Enforcement: o run_sandboxed (backend local) sobe o proxy e injeta HTTP_PROXY/HTTPS_PROXY no ambiente
do comando → toda ferramenta que respeita proxy (curl, pip, npm, requests…) passa pelo filtro. No
backend local NÃO há isolamento de rede de verdade, então um processo malicioso PODE ignorar o proxy;
enforcement à prova de bala exige netns/iptables (camada mais funda) — documentado, não fingido.
"""

from __future__ import annotations

import socket
import socketserver
import threading
from urllib.parse import urlsplit


def _match(host: str, allow: str) -> bool:
    host, allow = host.lower().strip("."), allow.lower().strip(".")
    if allow.startswith("*."):
        return host.endswith("." + allow[2:])            # *.github.com → api.github.com (não github.com)
    return host == allow or host.endswith("." + allow)   # github.com → github.com E api.github.com


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        try:
            line = self._readline()
            if not line:
                return
            parts = line.split(" ")
            if len(parts) < 2:
                return
            method, target = parts[0].upper(), parts[1]
            if method == "CONNECT":
                self._connect(target)
            else:
                self._plain(method, target, line)
        except OSError:
            pass
        finally:
            try:
                self.request.close()
            except OSError:
                pass

    def _readline(self) -> str:
        buf = b""
        while not buf.endswith(b"\n") and len(buf) < 8192:
            ch = self.request.recv(1)
            if not ch:
                break
            buf += ch
        return buf.decode("latin-1").strip()

    def _drain_headers(self) -> None:
        while True:
            ln = self._readline()
            if ln == "" or ln is None:
                break

    def _deny(self, host: str) -> None:
        self.request.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
        srv = self.server
        srv.denied.append(host)  # type: ignore[attr-defined]

    def _connect(self, target: str) -> None:
        host, _, port = target.partition(":")
        self._drain_headers()
        if not self.server.allowed(host):  # type: ignore[attr-defined]
            self._deny(host)
            return
        try:
            up = socket.create_connection((host, int(port or 443)), timeout=10)
        except OSError:
            self.request.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            return
        self.request.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
        self._pump(self.request, up)

    def _plain(self, method: str, target: str, first_line: str) -> None:
        u = urlsplit(target)
        host, port = u.hostname or "", u.port or 80
        if not host or not self.server.allowed(host):  # type: ignore[attr-defined]
            self._drain_headers()
            self._deny(host)
            return
        # reconstrói em origin-form (GET /path) e repassa os headers que sobram
        path = u.path or "/"
        if u.query:
            path += "?" + u.query
        headers = []
        while True:
            ln = self._readline()
            if not ln:
                break
            headers.append(ln)
        try:
            up = socket.create_connection((host, int(port)), timeout=10)
        except OSError:
            self.request.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            return
        req = f"{method} {path} HTTP/1.1\r\n" + "\r\n".join(headers) + "\r\n\r\n"
        up.sendall(req.encode("latin-1"))
        self._pump(self.request, up)

    def _pump(self, a: socket.socket, b: socket.socket) -> None:
        import select
        socks = [a, b]
        a.setblocking(False)
        b.setblocking(False)
        while True:
            try:
                r, _, _ = select.select(socks, [], [], 30)
            except OSError:
                break
            if not r:
                break
            done = False
            for s in r:
                try:
                    data = s.recv(65536)
                except OSError:
                    done = True
                    break
                if not data:
                    done = True
                    break
                (b if s is a else a).sendall(data)
            if done:
                break
        for s in (a, b):
            try:
                s.close()
            except OSError:
                pass


class EgressProxy:
    def __init__(self, allow, *, allow_private: bool = False):
        self.allow = [str(a) for a in (allow or [])]
        self.allow_private = allow_private
        self.denied: list[str] = []
        self._srv: socketserver.TCPServer | None = None
        self._thread: threading.Thread | None = None

    def allowed(self, host: str) -> bool:
        if not host or not any(_match(host, a) for a in self.allow):
            return False
        if self.allow_private:
            return True
        from okami.core.net_guard import _ip_blocked            # allowlist não escapa p/ rede interna
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError:
            return False
        return bool(infos) and not any(_ip_blocked(sa[0]) for *_, sa in infos)

    def start(self) -> int:
        proxy = self

        class _Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

            def allowed(self, host):
                return proxy.allowed(host)

            @property
            def denied(self):
                return proxy.denied

        self._srv = _Server(("127.0.0.1", 0), _Handler)
        self._thread = threading.Thread(target=self._srv.serve_forever, daemon=True)
        self._thread.start()
        return self._srv.server_address[1]

    @property
    def port(self) -> int:
        return self._srv.server_address[1] if self._srv else 0

    def proxy_env(self) -> dict:
        """Variáveis p/ rotear ferramentas (curl/pip/npm/requests) por este proxy."""
        url = f"http://127.0.0.1:{self.port}"
        return {"HTTP_PROXY": url, "HTTPS_PROXY": url, "ALL_PROXY": url,
                "http_proxy": url, "https_proxy": url, "all_proxy": url,
                "NO_PROXY": "", "no_proxy": ""}

    def stop(self) -> None:
        if self._srv:
            try:
                self._srv.shutdown()
                self._srv.server_close()
            except OSError:
                pass
            self._srv = None
