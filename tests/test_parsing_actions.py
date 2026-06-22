"""detect_malformed deve CONCORDAR com parse_actions: se o parser robusto extrai uma ação válida, não é
malformado. Bug latente: respond cujo `message` traz um bloco ```code``` quebrava o _FENCE não-guloso e
detect_malformed reportava 'JSON inválido' (falso) — o loop então rejeitava resposta VÁLIDA com código."""
from __future__ import annotations

import json

from okami.core.harness.parsing import detect_malformed, parse_actions


def J(tool, **args):
    return "```json\n" + json.dumps({"tool": tool, "args": args}) + "\n```"


def test_respond_with_code_fence_is_not_malformed():
    raw = J("respond", message="segue:\n```python\ndef f():\n    return 1\n```")
    assert parse_actions(raw)                      # o parser EXTRAI a ação
    assert detect_malformed(raw) is None           # logo, NÃO é malformado (antes: 'unterminated string')


def test_respond_with_quotes_and_media_is_not_malformed():
    raw = J("respond", message='aqui\nMEDIA:"/tmp/x.png"')
    assert parse_actions(raw)
    assert detect_malformed(raw) is None


def test_genuinely_broken_json_still_detected():
    broken = '```json\n{"tool": "respond", "args": {"message": '   # nunca fecha
    assert not parse_actions(broken)
    assert detect_malformed(broken)                # continua ENSINANDO o erro (não silencia)
