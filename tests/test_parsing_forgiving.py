"""Modelo LOCAL fraco (minimax m3) cospe JSON 'quase-válido' — aspas SIMPLES (estilo dict do Python),
None/True/False do Python, vírgula sobrando, estrutura truncada. O caminho de TEXTO do parser fazia
`json.loads` cru e DESCARTAVA tudo isso → nenhuma ação → loop de 'REJEITADO' (a sensação de 'burro').
O reparo multi-passe existia mas só rodava no caminho de function-call NATIVO. Aqui ele passa a valer
no caminho de texto, que é o que o modelo local usa de verdade (gap #1 vs Hermes message_sanitization)."""
from __future__ import annotations

from okami.core.harness.parsing import parse_action, parse_actions


def J(s: str) -> str:
    return "```json\n" + s + "\n```"


def test_single_quoted_action_is_parsed():
    a = parse_action(J("{'tool': 'read_file', 'args': {'path': 'x.txt'}}"))
    assert a is not None and a.tool == "read_file" and a.args == {"path": "x.txt"}


def test_python_literals_in_args_are_parsed():
    a = parse_action(J("{'tool': 'write_file', 'args': {'path': 'a', 'append': False, 'extra': None}}"))
    assert a is not None and a.tool == "write_file"
    assert a.args["append"] is False and a.args["extra"] is None


def test_trailing_comma_is_tolerated():
    a = parse_action(J('{"tool": "read_file", "args": {"path": "x",},}'))
    assert a is not None and a.tool == "read_file" and a.args == {"path": "x"}


def test_truncated_object_is_NOT_executed():
    # SEGURANÇA: objeto TRUNCADO (incompleto) NÃO pode virar ação — seria executar algo que o modelo
    # não terminou de especificar (ex.: um comando cortado). O harness re-pede a versão completa
    # (length-continuation); o parser não "adivinha" o resto.
    assert parse_actions(J('{"tool": "run_shell", "args": {"cmd": "rm -rf /tm')) == []


def test_valid_json_still_works():
    a = parse_action(J('{"tool": "read_file", "args": {"path": "y.txt"}}'))
    assert a is not None and a.tool == "read_file" and a.args == {"path": "y.txt"}


def test_batch_with_single_quotes():
    acts = parse_actions(J("{'tool': 'read_file', 'args': {'path': 'a'}}") + "\n" +
                         J("{'tool': 'read_file', 'args': {'path': 'b'}}"))
    assert [x.tool for x in acts] == ["read_file", "read_file"]
    assert [x.args["path"] for x in acts] == ["a", "b"]


def test_garbage_still_yields_no_action():
    assert parse_actions("isso é só conversa, sem json nenhum") == []
