"""Sanitização de JSON-Schema p/ o conversor de gramática do llama.cpp (#11, inspirado no Hermes
tools/schema_sanitizer.py).

O conversor JSON-Schema→GBNF do llama.cpp rejeita certos construtos (HTTP 400 grammar-parse). Schema
nativo do Okami é trivial (tudo string), mas schema de tool MCP externa pode ter:
- união nullable `anyOf/oneOf: [T, {type:null}]` → colapsa p/ T
- `type: ["string","null"]` (array-form) → 1º tipo não-null
- `pattern`/`format` (advisory) → removidos
- combinator no topo → achatado p/ o 1º ramo objeto

Conservador: só normaliza; nunca inventa. Aplicado proativamente em openai_tools().
"""
from __future__ import annotations

_STRIP_KEYS = ("pattern", "format")


def _collapse_union(branches: list) -> dict | None:
    """[T, {type:null}] / [{type:null}, T] → T (1º ramo não-null). None se não der."""
    non_null = [b for b in branches if isinstance(b, dict) and b.get("type") != "null"]
    if len(non_null) == 1:
        return non_null[0]
    return non_null[0] if non_null else None


def sanitize_tool_schema(schema):
    """Devolve uma CÓPIA sanitizada do `schema` (recursivo). Não muta o original."""
    if isinstance(schema, list):
        return [sanitize_tool_schema(x) for x in schema]
    if not isinstance(schema, dict):
        return schema

    node = dict(schema)

    # união nullable anyOf/oneOf → tipo base
    for comb in ("anyOf", "oneOf"):
        if isinstance(node.get(comb), list):
            collapsed = _collapse_union(node[comb])
            if collapsed is not None:
                node.pop(comb)
                merged = dict(collapsed)
                merged.update({k: v for k, v in node.items() if k not in ("anyOf", "oneOf")})
                node = merged

    # type array-form ["string","null"] → 1º não-null
    t = node.get("type")
    if isinstance(t, list):
        non_null = [x for x in t if x != "null"]
        node["type"] = non_null[0] if non_null else "string"

    # remove pattern/format (advisory; o grammar-converter tropeça)
    for k in _STRIP_KEYS:
        node.pop(k, None)

    # recursão em properties / items / definitions
    if isinstance(node.get("properties"), dict):
        node["properties"] = {k: sanitize_tool_schema(v) for k, v in node["properties"].items()}
    if "items" in node:
        node["items"] = sanitize_tool_schema(node["items"])
    for defs_key in ("$defs", "definitions"):
        if isinstance(node.get(defs_key), dict):
            node[defs_key] = {k: sanitize_tool_schema(v) for k, v in node[defs_key].items()}

    return node


def sanitize_tool_schemas(schemas: list) -> list:
    """Sanitiza cada schema de função (estrutura OpenAI {type:function, function:{parameters:{...}}})."""
    out = []
    for s in schemas or []:
        if isinstance(s, dict) and isinstance(s.get("function"), dict) and "parameters" in s["function"]:
            s = dict(s)
            fn = dict(s["function"])
            fn["parameters"] = sanitize_tool_schema(fn["parameters"])
            s["function"] = fn
        out.append(s)
    return out


__all__ = ["sanitize_tool_schema", "sanitize_tool_schemas"]
