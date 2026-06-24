"""Paridade Hermes (multi-vendor): server OpenAI-compat / local (LMStudio e shims) às vezes devolve
`content` como LISTA de blocos ([{type:text,text:...}]) ou dict, não string. _message_text fazia `content
or ''` e `.strip()` → AttributeError em lista → agora vira ABORT (fix de erro-local). Normaliza p/ string."""
from __future__ import annotations

from types import SimpleNamespace

from okami.llm.providers import _message_text


def test_string_content_unchanged():
    assert _message_text(SimpleNamespace(content="oi")) == "oi"


def test_list_of_blocks_content():
    msg = SimpleNamespace(content=[{"type": "text", "text": "parte 1 "}, {"type": "text", "text": "parte 2"}])
    assert _message_text(msg) == "parte 1 parte 2"


def test_dict_content():
    assert _message_text(SimpleNamespace(content={"type": "text", "text": "oi dict"})) == "oi dict"


def test_empty_list_falls_back_to_reasoning():
    msg = SimpleNamespace(content=[], reasoning_content="a resposta veio no reasoning")
    assert _message_text(msg) == "a resposta veio no reasoning"


def test_list_with_plain_strings():
    assert _message_text(SimpleNamespace(content=["a", "b", "c"])) == "abc"
