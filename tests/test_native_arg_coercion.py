"""Args TIPADOS no rail nativo (gap #1/#2 vs Hermes). Hoje todo arg vai como type:"string" no schema
(base.py) → no modo nativo o modelo emite STRING ("false", "30") e o tool recebe string. `bool("false")`
é True → BUG silencioso. Hermes carrega o tipo real no schema E coage o valor (model_tools.coerce_tool_args).
Aqui: arg_types declara o tipo → vai no schema nativo E o harness coage o string pro tipo certo. Coerção
é SCHEMA-AWARE (só o que foi declarado) → um path "123" NÃO vira int."""
from __future__ import annotations

from okami.core.tools.base import Tool, coerce_args


def test_coerce_boolean_string():
    assert coerce_args({"replace_all": "false"}, {"replace_all": "boolean"}) == {"replace_all": False}
    assert coerce_args({"replace_all": "true"}, {"replace_all": "boolean"}) == {"replace_all": True}


def test_coerce_integer_and_number():
    assert coerce_args({"timeout": "30"}, {"timeout": "integer"}) == {"timeout": 30}
    assert coerce_args({"ratio": "1.5"}, {"ratio": "number"}) == {"ratio": 1.5}


def test_already_typed_value_is_untouched():
    assert coerce_args({"replace_all": False}, {"replace_all": "boolean"}) == {"replace_all": False}
    assert coerce_args({"timeout": 30}, {"timeout": "integer"}) == {"timeout": 30}


def test_undeclared_arg_is_never_coerced():
    # SEGURANÇA: sem tipo declarado, um path/versão que PARECE número fica string
    assert coerce_args({"path": "123"}, {}) == {"path": "123"}
    assert coerce_args({"path": "123", "n": "5"}, {"n": "integer"}) == {"path": "123", "n": 5}


def test_uncoercible_value_stays_as_is():
    assert coerce_args({"timeout": "abc"}, {"timeout": "integer"}) == {"timeout": "abc"}   # não quebra


def test_to_openai_schema_carries_declared_types():
    class T(Tool):
        name = "t"
        description = "x"
        args_schema = {"replace_all": "trocar tudo", "timeout": "segundos", "path": "caminho"}
        arg_types = {"replace_all": "boolean", "timeout": "integer"}
    props = T().to_openai_schema()["function"]["parameters"]["properties"]
    assert props["replace_all"]["type"] == "boolean"
    assert props["timeout"]["type"] == "integer"
    assert props["path"]["type"] == "string"                # não declarado → string (default)
