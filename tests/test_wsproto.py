"""Item 8 (#8): protocolo WebSocket (RFC 6455) puro — handshake + framing. Sem dependência extra.

Estes helpers são a base testável do `okami serve --ws` / `okami attach`: o handshake (Sec-WebSocket-
Accept), o encode de frame de texto (servidor→cliente, sem máscara) e o decode (cliente→servidor,
com máscara). A cola de socket é fina; a corretude mora aqui."""
from __future__ import annotations


def test_accept_key_matches_rfc_example():
    # Exemplo canônico do RFC 6455 §1.3.
    from okami.gateway.wsproto import accept_key
    assert accept_key("dGhlIHNhbXBsZSBub25jZQ==") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="


def test_encode_decode_roundtrip_unmasked():
    from okami.gateway.wsproto import decode_frame, encode_text_frame
    raw = encode_text_frame("olá mundo")
    op, payload, consumed = decode_frame(raw)
    assert op == 0x1 and payload.decode("utf-8") == "olá mundo" and consumed == len(raw)


def test_decode_masked_client_frame():
    # Cliente SEMPRE mascara (bit 0x80 + chave de 4 bytes). O decode tem que desmascarar.
    from okami.gateway.wsproto import decode_frame, encode_text_frame
    masked = encode_text_frame("ping", mask=b"\x01\x02\x03\x04")
    op, payload, _ = decode_frame(masked)
    assert op == 0x1 and payload.decode("utf-8") == "ping"


def test_decode_returns_none_on_incomplete():
    from okami.gateway.wsproto import decode_frame
    assert decode_frame(b"\x81") is None          # frame truncado → ainda não dá p/ decodificar


def test_encode_medium_length_uses_extended_16bit():
    from okami.gateway.wsproto import decode_frame, encode_text_frame
    text = "x" * 200                                # >125 → comprimento estendido de 16 bits
    raw = encode_text_frame(text)
    assert raw[1] == 126                            # marcador de 16-bit length
    op, payload, _ = decode_frame(raw)
    assert payload.decode() == text


def test_close_frame_opcode():
    from okami.gateway.wsproto import close_frame, decode_frame
    op, _, _ = decode_frame(close_frame())
    assert op == 0x8                               # opcode de close
