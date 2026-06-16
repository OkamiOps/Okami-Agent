"""Framer JSON-RPC 2.0 mínimo do LSP sobre streams async (#17, port do Hermes agent/lsp/protocol.py).

Formato de fio do LSP:

    Content-Length: <bytes>\\r\\n
    \\r\\n
    <corpo JSON utf-8>

O corpo é um envelope JSON-RPC 2.0 (request, response ou notification). Só stdlib — o cliente foca na
semântica do protocolo. Tudo aqui é PURO/testável offline.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional, Tuple

logger = logging.getLogger("okami.lsp.protocol")

ERROR_CONTENT_MODIFIED = -32801
ERROR_REQUEST_CANCELLED = -32800
ERROR_METHOD_NOT_FOUND = -32601


class LSPProtocolError(Exception):
    """Violação do protocolo de fio (framing/envelope quebrado) — distinto de um error-response conforme."""


class LSPRequestError(Exception):
    """Um request do LSP devolveu um error-response (carrega code/message/data)."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(f"LSP error {code}: {message}")
        self.code = code
        self.message = message
        self.data = data


def encode_message(obj: dict) -> bytes:
    """Codifica um envelope JSON-RPC como bytes com frame Content-Length (JSON compacto → contagem exata)."""
    body = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


async def read_message(reader: asyncio.StreamReader) -> Optional[dict]:
    """Lê UMA mensagem framed do stream. None em EOF limpo; LSPProtocolError em framing malformado."""
    headers: dict = {}
    header_bytes = 0
    while True:
        try:
            line = await reader.readuntil(b"\r\n")
        except asyncio.IncompleteReadError as e:
            if not e.partial and not headers:
                return None
            raise LSPProtocolError(f"EOF inesperado lendo headers LSP (partial={e.partial!r})") from e
        header_bytes += len(line)
        if header_bytes > 8192:                          # cap defensivo: header sem terminador
            raise LSPProtocolError("bloco de header LSP passou de 8 KiB sem terminador")
        line = line[:-2]                                 # tira o CRLF
        if not line:
            break                                        # linha em branco encerra os headers
        try:
            key, _, value = line.decode("ascii").partition(":")
        except UnicodeDecodeError as e:
            raise LSPProtocolError(f"header LSP não-ASCII: {line!r}") from e
        if not key:
            raise LSPProtocolError(f"linha de header LSP malformada: {line!r}")
        headers[key.strip().lower()] = value.strip()

    cl = headers.get("content-length")
    if cl is None:
        raise LSPProtocolError(f"mensagem LSP sem Content-Length: {headers!r}")
    try:
        n = int(cl)
    except ValueError as e:
        raise LSPProtocolError(f"Content-Length não-inteiro: {cl!r}") from e
    if n < 0 or n > 64 * 1024 * 1024:                    # cap de sanidade: 64 MiB
        raise LSPProtocolError(f"Content-Length absurdo: {n}")

    try:
        body = await reader.readexactly(n)
    except asyncio.IncompleteReadError as e:
        raise LSPProtocolError(f"corpo LSP truncado: esperava {n}, veio {len(e.partial)}") from e

    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise LSPProtocolError(f"JSON inválido no corpo LSP: {e}") from e
    except UnicodeDecodeError as e:
        raise LSPProtocolError(f"corpo LSP não-UTF-8: {e}") from e


def make_request(req_id: int, method: str, params: Any) -> dict:
    """Envelope de request JSON-RPC 2.0."""
    msg: dict = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def make_notification(method: str, params: Any) -> dict:
    """Envelope de notification (sem id)."""
    msg: dict = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def make_response(req_id: Any, result: Any) -> dict:
    """Envelope de success-response."""
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def make_error_response(req_id: Any, code: int, message: str, data: Any = None) -> dict:
    """Envelope de error-response."""
    err: dict = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def classify_message(msg: dict) -> Tuple[str, Any]:
    """(kind, key): kind ∈ request|response|notification|invalid. key = id (req/resp), método (notif) ou None."""
    if not isinstance(msg, dict):
        return "invalid", None
    if msg.get("jsonrpc") != "2.0":
        return "invalid", None
    has_id = "id" in msg
    has_method = "method" in msg
    if has_id and has_method:
        return "request", msg["id"]
    if has_id and ("result" in msg or "error" in msg):
        return "response", msg["id"]
    if has_method and not has_id:
        return "notification", msg["method"]
    return "invalid", None


__all__ = [
    "ERROR_CONTENT_MODIFIED", "ERROR_REQUEST_CANCELLED", "ERROR_METHOD_NOT_FOUND",
    "LSPProtocolError", "LSPRequestError", "encode_message", "read_message",
    "make_request", "make_notification", "make_response", "make_error_response", "classify_message",
]
