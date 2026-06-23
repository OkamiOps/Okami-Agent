"""Profundidade do sanitizador de schema (paridade Hermes tools/schema_sanitizer) — fecha os construtos
que o grammar-converter do llama.cpp / backends strict (Codex/Fireworks) rejeitam em schema de tool MCP
externa: $ref com sibling proibido, objeto sem properties, required órfão, recursão em
additionalProperties/anyOf/allOf, e combinator no TOPO dos parâmetros."""
from __future__ import annotations

from okami.llm.schema_sanitizer import sanitize_tool_schema, sanitize_tool_schemas


def test_strip_default_sibling_of_ref():
    out = sanitize_tool_schema({"$ref": "#/$defs/X", "default": 5})
    assert out == {"$ref": "#/$defs/X"}                     # 'default' ao lado de $ref → removido


def test_object_without_properties_gets_empty_props():
    out = sanitize_tool_schema({"type": "object"})
    assert out == {"type": "object", "properties": {}}      # objeto sem properties é rejeitado → injeta {}


def test_dangling_required_is_pruned():
    out = sanitize_tool_schema({"type": "object", "properties": {"a": {"type": "string"}},
                                "required": ["a", "b"]})
    assert out["required"] == ["a"]                          # 'b' não existe em properties → podado


def test_required_all_invalid_is_dropped():
    out = sanitize_tool_schema({"type": "object", "properties": {}, "required": ["x"]})
    assert "required" not in out


def test_recurse_into_additional_properties_and_combinators():
    out = sanitize_tool_schema({"type": "object", "properties": {},
                                "additionalProperties": {"type": ["string", "null"], "format": "uri"}})
    ap = out["additionalProperties"]
    assert ap["type"] == "string" and "format" not in ap    # type-array achatado + format removido (recursivo)


def test_genuine_multi_union_is_preserved():
    out = sanitize_tool_schema({"anyOf": [{"type": "string"}, {"type": "integer"}]})
    assert "anyOf" in out and len(out["anyOf"]) == 2         # união real [str,int] NÃO é descartada


def test_top_level_combinator_stripped_in_function_params():
    schemas = [{"type": "function", "function": {"name": "f", "description": "d",
                "parameters": {"type": "object", "properties": {"a": {"type": "string"}},
                               "allOf": [{"required": ["a"]}]}}}]
    out = sanitize_tool_schemas(schemas)
    params = out[0]["function"]["parameters"]
    assert "allOf" not in params                            # backend strict (Codex) rejeita combinator no topo
