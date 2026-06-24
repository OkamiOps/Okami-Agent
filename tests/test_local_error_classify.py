"""Paridade harness Hermes (gap verificado): um erro LOCAL de programação (TypeError/ValueError/etc) na
geração era classificado como provider-error e o loop RETENTAVA/escalava 3x o MESMO bug. Agora erro local
→ ABORT (falha limpa). Exceções de DADO/transporte (JSONDecodeError, UnicodeError) seguem transitórias."""
from __future__ import annotations

import json

from okami.core.errors import Action, classify_provider


def test_typeerror_is_local_abort():
    f = classify_provider(TypeError("'NoneType' object is not subscriptable"))
    assert f.action == Action.ABORT          # bug local → NÃO martela 3x


def test_plain_valueerror_is_local_abort():
    assert classify_provider(ValueError("bad value")).action == Action.ABORT


def test_keyerror_attributeerror_local_abort():
    assert classify_provider(KeyError("x")).action == Action.ABORT
    assert classify_provider(AttributeError("y")).action == Action.ABORT


def test_jsondecode_is_not_local_bug():
    # JSON inválido da resposta = transporte/dado, NÃO bug local → segue a classificação normal (retriável)
    f = classify_provider(json.JSONDecodeError("Expecting value", "doc", 0))
    assert f.action != Action.ABORT


def test_unicode_is_not_local_bug():
    f = classify_provider(UnicodeDecodeError("utf-8", b"", 0, 1, "ruim"))
    assert f.action != Action.ABORT


def test_real_provider_error_still_classified():
    class _RateErr(Exception):
        pass
    f = classify_provider(_RateErr("rate limit exceeded, try again in 5s"))
    assert f.action in (Action.RETRY, Action.ESCALATE)   # erro de provider real segue retriável
