"""Paridade Hermes (entity flattening inbound): quando o dono MANDA uma mensagem formatada (negrito/código/
link), o Telegram entrega `text` PLANO + um array `entities`. O Okami lia só o text e perdia a formatação.
Agora reconstrói markdown a partir das entities → o agente vê **negrito**, `código`, [texto](url)."""
from __future__ import annotations

from okami.channels.telegram import _flatten_entities


def test_bold_and_code():
    # "diz oi em python" com 'oi' bold (off 4,len 2) e 'python' code (off 10,len 6)
    txt = "diz oi em python"
    ents = [{"type": "bold", "offset": 4, "length": 2}, {"type": "code", "offset": 10, "length": 6}]
    assert _flatten_entities(txt, ents) == "diz **oi** em `python`"


def test_text_link():
    txt = "veja aqui"
    ents = [{"type": "text_link", "offset": 5, "length": 4, "url": "https://x.com"}]
    assert _flatten_entities(txt, ents) == "veja [aqui](https://x.com)"


def test_no_entities_returns_raw():
    assert _flatten_entities("texto puro", None) == "texto puro"
    assert _flatten_entities("texto puro", []) == "texto puro"


def test_supplementary_plane_char_skips_flatten_safely():
    # emoji fora do BMP → offsets UTF-16 do Telegram não casam com índices Python → devolve cru (não corrompe)
    txt = "oi 😀 mundo"
    ents = [{"type": "bold", "offset": 0, "length": 2}]
    assert _flatten_entities(txt, ents) == txt
