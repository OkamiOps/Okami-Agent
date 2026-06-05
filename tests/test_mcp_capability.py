"""Capability manifest de MCP (#8): classifica tools, recusa http remoto, força go/no-go por capability."""

from __future__ import annotations

from okami.integrations.mcp import McpTool, _mcp_url_ok, infer_capabilities, load_mcp_tools


def test_infer_capabilities_from_name_and_desc():
    assert "write" in infer_capabilities({"name": "create_file", "description": "creates a file"})
    assert "network" in infer_capabilities({"name": "web_search", "description": "search the web"})
    assert "shell" in infer_capabilities({"name": "run_command", "description": "execute a command"})
    assert "secret-access" in infer_capabilities({"name": "get_token", "description": "returns the api key"})
    assert infer_capabilities({"name": "list_items", "description": "list things"}) == {"read"}


def test_mcp_url_policy_https_or_local_only():
    assert _mcp_url_ok("https://api.example.com/mcp")
    assert _mcp_url_ok("http://localhost:3000") and _mcp_url_ok("http://127.0.0.1:8080")
    assert not _mcp_url_ok("http://evil.example.com/mcp")     # plaintext remoto → recusa


def test_mcp_tool_carries_capabilities():
    t = McpTool(client=None, spec={"name": "write_thing", "description": "writes data"}, prefix="srv__")
    assert t.name == "srv__write_thing" and "write" in t.capabilities and t.trusted is False


def test_load_rejects_insecure_remote_url():
    msgs = []
    tools, _ = load_mcp_tools({"bad": {"url": "http://evil.com/mcp"}}, emit=msgs.append)
    assert tools == {} and any("RECUSADO" in m for m in msgs)


def test_harness_gates_dangerous_mcp_tool_with_approval(tmp_path):
    from okami.core import Harness, Task
    from okami.core.tools import Tool, ToolResult, default_registry
    from okami.llm.usage import Completion

    class _FakeMcp(Tool):
        name = "srv__delete_all"
        description = "deletes everything"
        args_schema = {"target": "what"}
        capabilities = {"write", "external-side-effect"}
        trusted = False

        def run(self, args, ctx):
            return ToolResult(True, "apaguei tudo", effect=True)

    reg = default_registry()
    reg["srv__delete_all"] = _FakeMcp()
    seen = {}
    calls = {"n": 0}

    def approver(req):
        seen.update(req)
        return False                                          # nega → não executa a tool MCP perigosa

    def gen(messages, schema=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return Completion(text='```json\n{"tool":"srv__delete_all","args":{"target":"x"}}\n```')
        return Completion(text='```json\n{"tool":"respond","args":{"message":"ok"}}\n```')

    Harness(gen, Task(goal="apaga"), tmp_path, registry=reg, approve=approver).run()
    assert seen.get("tool") == "srv__delete_all" and seen.get("category") == "mcp_capability"
