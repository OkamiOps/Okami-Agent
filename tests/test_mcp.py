"""Testes do cliente MCP contra um servidor-mock real (stdio JSON-RPC)."""

from __future__ import annotations

import sys
from pathlib import Path

from okami.integrations.mcp import McpStdioClient, load_mcp_tools

MOCK = str(Path(__file__).resolve().parent / "_mock_mcp_server.py")


def test_mcp_handshake_list_and_call():
    c = McpStdioClient(sys.executable, [MOCK])
    tools = c.start()
    assert {t["name"] for t in tools} >= {"echo", "add"}
    ok, text = c.call_tool("echo", {"text": "oi MCP"})
    assert ok and text == "oi MCP"
    ok, text = c.call_tool("add", {"a": 2, "b": 3})
    assert ok and text == "5"
    c.close()


def test_mcp_tools_wrap_into_registry():
    tools, clients = load_mcp_tools({"mock": {"command": sys.executable, "args": [MOCK]}})
    try:
        assert "mock__echo" in tools and "mock__add" in tools
        assert tools["mock__add"].required == ("a", "b")   # veio do inputSchema
        res = tools["mock__echo"].run({"text": "hello"}, None)
        assert res.ok and res.output == "hello"
    finally:
        for c in clients:
            c.close()


def test_mcp_bad_server_does_not_crash():
    tools, clients = load_mcp_tools({"bad": {"command": "binario_que_nao_existe_xyz123"}})
    assert tools == {} and clients == []


# ----------------------------------------------------------------- HTTP transport (§12)
def test_mcp_parse_jsonrpc_plain_and_sse():
    from okami.integrations.mcp import _parse_jsonrpc
    assert _parse_jsonrpc('{"jsonrpc":"2.0","id":1,"result":{"tools":[]}}') == {"tools": []}
    sse = 'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n\n'
    assert _parse_jsonrpc(sse) == {"ok": True}


def test_mcp_http_client_lists_and_calls(monkeypatch):
    from okami.integrations.mcp import McpHttpClient
    c = McpHttpClient("https://x/mcp")
    posts = []

    def fake_post(method, params=None, notify=False):
        posts.append(method)
        if method == "tools/list":
            return {"tools": [{"name": "echo", "description": "echo", "inputSchema": {}}]}
        if method == "tools/call":
            return {"content": [{"type": "text", "text": "pong"}]}
        return {}

    monkeypatch.setattr(c, "_post", fake_post)
    assert c.start()[0]["name"] == "echo"
    ok, text = c.call_tool("echo", {"x": 1})
    assert ok and text == "pong" and "initialize" in posts
