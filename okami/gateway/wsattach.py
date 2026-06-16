"""Attach a um gateway remoto por WebSocket (#8 item 8) — servidor + cliente, stdlib-only.

O dono roda o gateway numa máquina (VPS / outro host na tailnet) com `okami serve --ws` e fala com ele
de longe via `okami attach ws://<host>:porta/attach`. Casa com o ambiente Tailscale: aponte o cliente
pro host da tailnet. FAIL-CLOSED: exige token (não sobe sem ele); o token autentica o handshake.

A conexão é PERSISTENTE (multi-turno): cada conexão recebe um `session` estável, então o `run` do
chamador pode manter histórico por sessão. O protocolo (handshake + framing) mora em `wsproto`.
"""
from __future__ import annotations

import base64
import os
import secrets
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from okami.gateway.wsproto import (
    OP_CLOSE, OP_PING, OP_TEXT, accept_key, client_mask, close_frame, decode_frame,
    encode_text_frame, pong_frame,
)


def handshake_headers(client_key: str) -> bytes:
    """Resposta 101 Switching Protocols que completa o handshake do servidor."""
    return ("HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept_key(client_key)}\r\n\r\n").encode("ascii")


# ── Upload de arquivo do cliente p/ o gateway remoto (#10 file.attach) ──
_ATTACH_PREFIX = "\x00ATTACH\x00"


def encode_attach(name: str, data: bytes) -> str:
    """Frame de texto que carrega um anexo: sentinela + nome + base64 do conteúdo."""
    return _ATTACH_PREFIX + str(name) + "\x00" + base64.b64encode(data).decode("ascii")


def parse_attach(frame: str):
    """(nome, base64) se o frame é um anexo, senão None."""
    if not isinstance(frame, str) or not frame.startswith(_ATTACH_PREFIX):
        return None
    name, _, b64 = frame[len(_ATTACH_PREFIX):].partition("\x00")
    return name, b64


def materialize_attachment(attach_dir, name: str, b64: str) -> str:
    """Grava o anexo sob <attach_dir>/.okami/attachments/<nome-seguro> e devolve o caminho relativo a
    attach_dir (p/ virar um @file:). Anti path-traversal: usa só o basename sanitizado."""
    import os
    import re
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(str(name or "anexo"))) or "anexo"
    base = Path(attach_dir)
    d = base / ".okami" / "attachments"
    d.mkdir(parents=True, exist_ok=True)
    p = d / safe
    p.write_bytes(base64.b64decode(b64 or ""))
    return str(p.relative_to(base))


def _call_run(run, msg: str, session: str) -> str:
    """Chama o run com (msg, session) se ele aceitar; senão só (msg). Sempre devolve texto."""
    try:
        return str(run(msg, session=session))
    except TypeError:
        return str(run(msg))


def _make_handler(token: str, run, attach_dir=None):
    class _Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):   # silencia o log default
            pass

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path != "/attach" or self.headers.get("Upgrade", "").lower() != "websocket":
                self.send_response(404)
                self.end_headers()
                return
            qs = parse_qs(parsed.query)
            tok = (qs.get("token") or [""])[0] or \
                self.headers.get("Authorization", "").replace("Bearer ", "").strip()
            if tok != token:                       # fail-closed: token errado/ausente → recusa
                self.send_response(401)
                self.end_headers()
                return
            key = self.headers.get("Sec-WebSocket-Key", "")
            if not key:
                self.send_response(400)
                self.end_headers()
                return
            self.wfile.write(handshake_headers(key))
            self.wfile.flush()
            # session do ?session=<id> (reconectar com o mesmo id RESUME a conversa); senão um novo id.
            sess = (qs.get("session") or [""])[0].strip() or secrets.token_hex(4)
            self._ws_loop(sess)

        def _ws_loop(self, session: str) -> None:
            sock = self.connection
            buf = b""
            while True:
                try:
                    chunk = sock.recv(4096)
                except OSError:
                    return
                if not chunk:
                    return
                buf += chunk
                while True:
                    res = decode_frame(buf)
                    if res is None:
                        break
                    op, payload, consumed = res
                    buf = buf[consumed:]
                    if op == OP_CLOSE:
                        return
                    if op == OP_PING:
                        sock.sendall(pong_frame())
                        continue
                    if op == OP_TEXT:
                        msg = payload.decode("utf-8", "replace")
                        att = parse_attach(msg)
                        if att is not None:               # #10: upload de arquivo do cliente → @file:
                            try:
                                rel = materialize_attachment(attach_dir or ".", att[0], att[1])
                                reply = f"📎 anexado: @file:{rel} (referencie-o na sua próxima mensagem)"
                            except Exception as e:  # noqa: BLE001
                                reply = f"erro ao anexar: {e}"
                        else:
                            try:
                                reply = _call_run(run, msg, session)
                            except Exception as e:  # noqa: BLE001 — um turno que falha não derruba a conexão
                                reply = f"erro: {e}"
                        try:
                            sock.sendall(encode_text_frame(reply))
                        except OSError:
                            return

    return _Handler


def serve_ws(port: int, token: str, run, *, host: str = "127.0.0.1", attach_dir=None) -> ThreadingHTTPServer:
    """Servidor WS de attach (fail-closed sem token). O chamador roda `serve_forever()`.
    Bind em 127.0.0.1 por padrão; passe host=<ip da tailnet>/0.0.0.0 p/ alcançar de outra máquina.
    attach_dir = onde materializar uploads do cliente (file.attach) — vira @file: no workspace."""
    if not token:
        raise RuntimeError("token obrigatório — o attach por WS não sobe sem token (fail-closed).")
    return ThreadingHTTPServer((host, port), _make_handler(token, run, attach_dir))


class WSClient:
    """Cliente WS mínimo (stdlib socket) p/ o `okami attach`. send/recv de texto, com close limpo."""

    def __init__(self):
        self.sock = None
        self._buf = b""

    def connect(self, url: str, token: str = "", timeout: float = 30.0) -> None:
        u = urlparse(url)
        host, port = u.hostname or "127.0.0.1", u.port or 80
        path = u.path or "/attach"
        if u.query:                                  # preserva ?session=<id> etc. da URL
            path += "?" + u.query
        if token:
            path += ("&" if "?" in path else "?") + f"token={token}"
        self.sock = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        req = (f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode("ascii"))
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self.sock.recv(1024)
            if not chunk:
                raise ConnectionError("handshake falhou — sem resposta do servidor.")
            resp += chunk
        status = resp.split(b"\r\n", 1)[0]
        if b"101" not in status:
            raise ConnectionError(f"handshake recusado: {status.decode('latin1')}")
        self._buf = resp.split(b"\r\n\r\n", 1)[1]   # bytes de frame que vieram colados (raro)

    def send(self, text: str) -> None:
        self.sock.sendall(encode_text_frame(text, mask=client_mask()))   # cliente SEMPRE mascara

    def send_attach(self, name: str, data: bytes) -> None:
        """Envia um arquivo do disco local p/ o gateway remoto (#10 file.attach) → vira @file: lá."""
        self.sock.sendall(encode_text_frame(encode_attach(name, data), mask=client_mask()))

    def recv(self, timeout: float = 120.0):
        self.sock.settimeout(timeout)
        while True:
            res = decode_frame(self._buf)
            if res is not None:
                op, payload, consumed = res
                self._buf = self._buf[consumed:]
                if op == OP_TEXT:
                    return payload.decode("utf-8", "replace")
                if op == OP_CLOSE:
                    return None
                if op == OP_PING:
                    self.sock.sendall(pong_frame())
                continue
            chunk = self.sock.recv(4096)
            if not chunk:
                return None
            self._buf += chunk

    def close(self) -> None:
        try:
            self.sock.sendall(close_frame())
            self.sock.close()
        except OSError:
            pass
