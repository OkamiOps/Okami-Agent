"""mcp_serve (pesquisa #6 item 29, paridade Hermes mcp_serve) — servir o PRÓPRIO agente como servidor
MCP. Outros clientes (Claude Code/Cursor/Codex) consomem o histórico/memória do Okami via MCP.

Handler JSON-RPC 2.0 testável (initialize / tools/list / tools/call) sobre as sessões e memória que
o Okami já mantém. Read-only por padrão (expor o que o agente SABE, sem dar controle de execução).
"""
from __future__ import annotations

from okami.gateway.sessions import TranscriptStore
from okami.integrations.mcp_serve import OkamiMcpServer


def _seed(home):
    st = TranscriptStore(home)
    st.append("42", "USER", "lembra que decidimos usar sqlite")
    st.append("42", "AGENTE", "sim, sqlite com FTS5")
    return st


def _rpc(method, params=None, _id=1):
    return {"jsonrpc": "2.0", "id": _id, "method": method, "params": params or {}}


def test_initialize(tmp_path):
    srv = OkamiMcpServer(tmp_path)
    resp = srv.handle(_rpc("initialize"))
    assert resp["result"]["serverInfo"]["name"] == "okami"
    assert "capabilities" in resp["result"]


def test_tools_list(tmp_path):
    srv = OkamiMcpServer(tmp_path)
    resp = srv.handle(_rpc("tools/list"))
    names = {t["name"] for t in resp["result"]["tools"]}
    assert {"sessions_list", "session_read", "session_search"} <= names
    for t in resp["result"]["tools"]:                 # cada tool tem schema
        assert "inputSchema" in t


def test_call_sessions_list(tmp_path):
    _seed(tmp_path)
    srv = OkamiMcpServer(tmp_path)
    resp = srv.handle(_rpc("tools/call", {"name": "sessions_list", "arguments": {}}))
    text = resp["result"]["content"][0]["text"]
    assert "42" in text


def test_call_session_read(tmp_path):
    _seed(tmp_path)
    srv = OkamiMcpServer(tmp_path)
    resp = srv.handle(_rpc("tools/call", {"name": "session_read", "arguments": {"chat_id": "42"}}))
    text = resp["result"]["content"][0]["text"]
    assert "sqlite" in text and "FTS5" in text


def test_call_session_search(tmp_path):
    _seed(tmp_path)
    srv = OkamiMcpServer(tmp_path)
    resp = srv.handle(_rpc("tools/call", {"name": "session_search", "arguments": {"query": "sqlite"}}))
    text = resp["result"]["content"][0]["text"]
    assert "sqlite" in text.lower()


def test_call_unknown_tool_errors(tmp_path):
    srv = OkamiMcpServer(tmp_path)
    resp = srv.handle(_rpc("tools/call", {"name": "nope", "arguments": {}}))
    assert "error" in resp or resp["result"].get("isError")


def test_unknown_method_returns_error(tmp_path):
    srv = OkamiMcpServer(tmp_path)
    resp = srv.handle(_rpc("frobnicate"))
    assert resp.get("error", {}).get("code") == -32601   # method not found


def test_notification_returns_none(tmp_path):
    srv = OkamiMcpServer(tmp_path)
    # JSON-RPC notification (sem id) → sem resposta
    assert srv.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
