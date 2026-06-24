"""MCP (hunt#3): McpTool não extraía arg_types da inputSchema → to_openai_schema gerava type:string p/ TUDO
e coerce_args era pulado (modelo nativo manda "42"/"false" string → tool recebe string, quebra). E `required`
vinha cru da spec (podia exigir um campo que nem existe em properties → harness barra à toa)."""
from __future__ import annotations

from okami.integrations.mcp import McpTool

_SPEC = {
    "name": "x", "description": "d",
    "inputSchema": {
        "properties": {
            "count": {"type": "integer", "description": "quantos"},
            "flag": {"type": "boolean"},
            "name": {"type": "string"},
            "maybe": {"type": ["string", "null"]},
        },
        "required": ["count", "phantom"],     # phantom NÃO existe em properties
    },
}


def test_arg_types_extracted_for_native_coercion():
    t = McpTool(client=None, spec=_SPEC)
    assert t.arg_types.get("count") == "integer"
    assert t.arg_types.get("flag") == "boolean"
    assert "name" not in t.arg_types          # string é o default → não precisa coagir
    assert "maybe" not in t.arg_types         # ["string","null"] resolve p/ string → também não coage


def test_required_filtered_to_existing_props():
    t = McpTool(client=None, spec=_SPEC)
    assert t.required == ("count",)           # 'phantom' não existe em properties → filtrado


def test_args_schema_is_description_only():
    t = McpTool(client=None, spec=_SPEC)
    assert t.args_schema["count"] == "quantos"   # descrição, não o tipo misturado
