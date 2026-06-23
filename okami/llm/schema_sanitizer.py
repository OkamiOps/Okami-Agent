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
_REF_FORBIDDEN_SIBLINGS = ("default",)                       # draft-07-strict: nada ao lado de $ref
_TOP_LEVEL_FORBIDDEN = ("allOf", "anyOf", "oneOf", "enum", "not")   # Codex/strict: sem combinator no topo
# Modo AGRESSIVO (retry reativo após um grammar-400): tira também enum/const e todas as restrições
# numéricas/tamanho que alguns grammar-converters não digerem. Perde validação advisory, não correção.
_AGGRESSIVE_STRIP = ("enum", "const", "examples", "minLength", "maxLength", "minimum", "maximum",
                     "exclusiveMinimum", "exclusiveMaximum", "minItems", "maxItems", "multipleOf",
                     "uniqueItems", "minProperties", "maxProperties")


def _collapse_union(branches: list) -> dict | None:
    """SÓ colapsa o caso NULLABLE `[T, {type:null}]` → T. União GENUÍNA de 2+ tipos reais ([T1, T2]) NÃO
    é colapsada (pegar só o 1º descartava o T2 em silêncio — Hermes preserva). None = não dá p/ colapsar."""
    non_null = [b for b in branches if isinstance(b, dict) and b.get("type") != "null"]
    if len(non_null) == 1:                                # exatamente 1 não-null (resto era null) → colapsa
        return non_null[0]
    return None                                          # 0 ou 2+ não-null → mantém a união como veio


def sanitize_tool_schema(schema, *, aggressive: bool = False):
    """Devolve uma CÓPIA sanitizada do `schema` (recursivo). Não muta o original. `aggressive` (retry
    reativo) tira também enum/const/limites."""
    if isinstance(schema, list):
        return [sanitize_tool_schema(x, aggressive=aggressive) for x in schema]
    if not isinstance(schema, dict):
        return schema

    node = dict(schema)
    if aggressive:
        for k in _AGGRESSIVE_STRIP:
            node.pop(k, None)

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

    # $ref com sibling proibido (ex.: `default`) → draft-07-strict (Fireworks) rejeita
    if "$ref" in node:
        for k in _REF_FORBIDDEN_SIBLINGS:
            node.pop(k, None)

    # recursão: properties / $defs / items / additionalProperties / anyOf|oneOf|allOf
    if isinstance(node.get("properties"), dict):
        node["properties"] = {k: sanitize_tool_schema(v, aggressive=aggressive)
                              for k, v in node["properties"].items()}
    for defs_key in ("$defs", "definitions"):
        if isinstance(node.get(defs_key), dict):
            node[defs_key] = {k: sanitize_tool_schema(v, aggressive=aggressive)
                              for k, v in node[defs_key].items()}
    if "items" in node:
        node["items"] = sanitize_tool_schema(node["items"], aggressive=aggressive)
    if "additionalProperties" in node and not isinstance(node["additionalProperties"], bool):
        node["additionalProperties"] = sanitize_tool_schema(node["additionalProperties"], aggressive=aggressive)
    for comb in ("anyOf", "oneOf", "allOf"):
        if isinstance(node.get(comb), list):
            node[comb] = [sanitize_tool_schema(x, aggressive=aggressive) for x in node[comb]]

    # objeto sem properties → injeta {} (o grammar-converter rejeita objeto sem campos)
    if node.get("type") == "object" and not isinstance(node.get("properties"), dict):
        node["properties"] = {}

    # poda `required` que não existe em properties (defesa: o handler revalida required de verdade)
    if node.get("type") == "object" and isinstance(node.get("required"), list):
        props = node.get("properties") or {}
        valid = [r for r in node["required"] if isinstance(r, str) and r in props]
        if valid:
            node["required"] = valid
        else:
            node.pop("required", None)

    return node


def sanitize_tool_schemas(schemas: list, *, aggressive: bool = False) -> list:
    """Sanitiza cada schema de função (estrutura OpenAI {type:function, function:{parameters:{...}}})."""
    out = []
    for s in schemas or []:
        if isinstance(s, dict) and isinstance(s.get("function"), dict) and "parameters" in s["function"]:
            s = dict(s)
            fn = dict(s["function"])
            params = sanitize_tool_schema(fn["parameters"], aggressive=aggressive)
            if isinstance(params, dict):                    # backend strict (Codex): sem combinator NO TOPO
                params = {k: v for k, v in params.items() if k not in _TOP_LEVEL_FORBIDDEN}
            fn["parameters"] = params
            s["function"] = fn
        out.append(s)
    return out


__all__ = ["sanitize_tool_schema", "sanitize_tool_schemas"]
