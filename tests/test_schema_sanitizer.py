"""#11 Onda 2: sanitização de JSON-Schema p/ o conversor de gramática do llama.cpp (GBNF).

Schemas de tools MCP externas podem ter construtos que o grammar-converter do llama.cpp rejeita
(união nullable anyOf/oneOf, pattern/format, combinator no topo) → HTTP 400. Sanitiza proativamente.
Schema nativo do Okami (tudo string) passa intacto.
"""
from __future__ import annotations


def test_nullable_anyof_union_collapses_to_base_type():
    from okami.llm.schema_sanitizer import sanitize_tool_schema
    sc = {"type": "object", "properties": {
        "x": {"anyOf": [{"type": "string"}, {"type": "null"}]}}}
    out = sanitize_tool_schema(sc)
    assert out["properties"]["x"].get("type") == "string"    # união nullable → tipo base
    assert "anyOf" not in out["properties"]["x"]


def test_pattern_and_format_stripped():
    from okami.llm.schema_sanitizer import sanitize_tool_schema
    sc = {"type": "object", "properties": {
        "email": {"type": "string", "format": "email", "pattern": "^.+@.+$"}}}
    out = sanitize_tool_schema(sc)
    assert "format" not in out["properties"]["email"]
    assert "pattern" not in out["properties"]["email"]
    assert out["properties"]["email"]["type"] == "string"    # tipo preservado


def test_array_form_type_collapses_to_first_non_null():
    from okami.llm.schema_sanitizer import sanitize_tool_schema
    sc = {"type": "object", "properties": {"y": {"type": ["string", "null"]}}}
    out = sanitize_tool_schema(sc)
    assert out["properties"]["y"]["type"] == "string"


def test_nested_objects_and_arrays_recursed():
    from okami.llm.schema_sanitizer import sanitize_tool_schema
    sc = {"type": "object", "properties": {
        "items": {"type": "array", "items": {"type": "string", "format": "uri"}}}}
    out = sanitize_tool_schema(sc)
    assert "format" not in out["properties"]["items"]["items"]


def test_simple_okami_schema_passes_unchanged():
    from okami.llm.schema_sanitizer import sanitize_tool_schema
    sc = {"type": "object", "properties": {"cmd": {"type": "string", "description": "comando"}},
          "required": ["cmd"]}
    assert sanitize_tool_schema(sc) == sc                    # schema simples (nativo) intacto


def test_openai_tools_applies_sanitizer():
    from okami.core.tools.base import openai_tools, Tool, ToolResult

    class _Weird(Tool):
        name = "weird"
        description = "x"

        def to_openai_schema(self):
            return {"type": "function", "function": {"name": "weird", "description": "x",
                    "parameters": {"type": "object", "properties": {
                        "p": {"anyOf": [{"type": "string"}, {"type": "null"}], "format": "uri"}}}}}

        def run(self, args, ctx):
            return ToolResult(True, "")

    schemas = openai_tools({"weird": _Weird()})
    p = schemas[0]["function"]["parameters"]["properties"]["p"]
    assert p.get("type") == "string" and "anyOf" not in p and "format" not in p
