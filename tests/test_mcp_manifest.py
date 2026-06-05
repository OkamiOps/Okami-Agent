"""Manifesto/trust-store de MCP (#11): trust levels + manifesto por-tool + 'unknown != read'."""

from __future__ import annotations

from okami.core.tools import Tool, ToolResult, default_registry
from okami.integrations.mcp import McpTool, _tool_manifest, _trust_of
from okami.llm.usage import Completion


def test_trust_levels():
    assert _trust_of({}) == "untrusted"                     # default = untrusted (fail-safe)
    assert _trust_of({"trust": "reviewed"}) == "reviewed"
    assert _trust_of({"trust": "trusted"}) == "trusted"
    assert _trust_of({"trusted": True}) == "trusted"        # legado
    assert _trust_of({"trust": "lol"}) == "untrusted"       # valor inválido → untrusted


def test_tool_manifest_precedence():
    conf = {"capabilities": ["read"],                        # override do servidor todo
            "tools": {"write_page": {"capabilities": ["write"], "approval": "always"}}}
    caps, policy, has = _tool_manifest(conf, "write_page")
    assert caps == {"write"} and policy == "always" and has is True
    caps2, policy2, has2 = _tool_manifest(conf, "search")   # cai no override do servidor
    assert caps2 == {"read"} and policy2 == "auto" and has2 is True
    caps3, policy3, has3 = _tool_manifest({}, "x")           # sem nada → infere
    assert caps3 is None and has3 is False


def test_mcp_tool_unverified_and_policy():
    t = McpTool(client=None, spec={"name": "anything", "description": "list stuff"},
                prefix="srv__", unverified=True, approval_policy="always")
    assert t.unverified is True and t.approval_policy == "always"


# ---------------- gate no harness ----------------

def _mcp_tool(name, *, caps, trusted=False, policy="auto", unverified=False):
    class _T(Tool):
        def run(self, args, ctx):
            return ToolResult(True, "ok", effect=True)
    t = _T()
    t.name, t.description, t.args_schema = name, "x", {"a": "b"}
    t.capabilities, t.trusted, t.approval_policy, t.unverified = set(caps), trusted, policy, unverified
    return t


def _run_capture(tool):
    from okami.core import Harness, Task
    reg = default_registry()
    reg[tool.name] = tool
    seen, calls = {}, {"n": 0}

    def approver(req):
        seen.update(req)
        return False

    def gen(messages, schema=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return Completion(text='```json\n{"tool":"%s","args":{"a":"1"}}\n```' % tool.name)
        return Completion(text='```json\n{"tool":"respond","args":{"message":"ok"}}\n```')

    import tempfile
    Harness(gen, Task(goal="t"), tempfile.mkdtemp(), registry=reg, approve=approver).run()
    return seen


def test_unverified_tool_is_gated_even_if_looks_read():
    """'list stuff' inferiria read, mas servidor untrusted sem manifesto → go/no-go."""
    seen = _run_capture(_mcp_tool("srv__list_stuff", caps={"read"}, unverified=True))
    assert seen.get("category") == "mcp_unverified"


def test_trusted_tool_not_gated():
    seen = _run_capture(_mcp_tool("srv__delete_all", caps={"write"}, trusted=True))
    assert seen == {}                                        # confiável → não pede aprovação


def test_manifest_never_skips_gate():
    seen = _run_capture(_mcp_tool("srv__writer", caps={"write"}, policy="never"))
    assert seen == {}                                        # liberada explicitamente no manifesto


def test_manifest_always_forces_gate():
    seen = _run_capture(_mcp_tool("srv__reader", caps={"read"}, policy="always"))
    assert seen.get("category") == "mcp_manifest"            # exige aprovação mesmo sendo read
