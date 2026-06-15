"""WebSocket (RFC 6455) puro — handshake + framing, stdlib-only (#8 item 8).

Base testável do `okami serve --ws` (servidor) e `okami attach` (cliente): o handshake calcula o
Sec-WebSocket-Accept; o framing codifica texto (servidor manda SEM máscara) e decodifica (cliente
manda COM máscara — desmascaramos). A cola de socket (handshake HTTP + loop send/recv) é fina; a
corretude do protocolo mora aqui.
"""
from __future__ import annotations

import base64
import hashlib
import os
import struct

_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"   # mágica do RFC 6455 §1.3

OP_TEXT = 0x1
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA


def accept_key(client_key: str) -> str:
    """Sec-WebSocket-Accept = base64(sha1(client_key + GUID)) — completa o handshake do servidor."""
    # SHA1 é EXIGIDO pelo handshake do RFC 6455 (não é uso de segurança/crypto) — usedforsecurity=False
    # sinaliza isso ao runtime e ao bandit.
    digest = hashlib.sha1(  # noqa: S324
        (client_key.strip() + _GUID).encode("ascii"), usedforsecurity=False).digest()
    return base64.b64encode(digest).decode("ascii")


def encode_frame(payload: bytes, opcode: int = OP_TEXT, *, mask: bytes | None = None) -> bytes:
    """Um frame FIN único. Servidor→cliente: mask=None (sem máscara). Cliente→servidor: mask=4 bytes."""
    b0 = 0x80 | (opcode & 0x0F)                    # FIN=1 + opcode
    n = len(payload)
    if n < 126:
        header = bytes([b0, n | (0x80 if mask else 0)])
    elif n < 65536:
        header = bytes([b0, 126 | (0x80 if mask else 0)]) + struct.pack(">H", n)
    else:
        header = bytes([b0, 127 | (0x80 if mask else 0)]) + struct.pack(">Q", n)
    if mask:
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return header + mask + masked
    return header + payload


def encode_text_frame(text: str, *, mask: bytes | None = None) -> bytes:
    return encode_frame(text.encode("utf-8"), OP_TEXT, mask=mask)


def close_frame() -> bytes:
    return encode_frame(b"", OP_CLOSE)


def ping_frame() -> bytes:
    return encode_frame(b"", OP_PING)


def pong_frame() -> bytes:
    return encode_frame(b"", OP_PONG)


def client_mask() -> bytes:
    return os.urandom(4)


def decode_frame(data: bytes):
    """Decodifica UM frame de `data`. Retorna (opcode, payload_bytes, bytes_consumidos) ou None se
    o buffer ainda está incompleto (o chamador acumula mais bytes e tenta de novo)."""
    if len(data) < 2:
        return None
    b1 = data[1]
    masked = bool(b1 & 0x80)
    length = b1 & 0x7F
    off = 2
    if length == 126:
        if len(data) < off + 2:
            return None
        length = struct.unpack(">H", data[off:off + 2])[0]
        off += 2
    elif length == 127:
        if len(data) < off + 8:
            return None
        length = struct.unpack(">Q", data[off:off + 8])[0]
        off += 8
    mask = b""
    if masked:
        if len(data) < off + 4:
            return None
        mask = data[off:off + 4]
        off += 4
    if len(data) < off + length:
        return None
    payload = data[off:off + length]
    if masked:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return (data[0] & 0x0F), payload, off + length
