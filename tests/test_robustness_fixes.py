"""Correções de robustez da caça field-fail: (1) cliente MCP stdio não pode deixar subprocesso/thread
zumbi quando o servidor trava (timeout) ou fecha (EOF); (2) browse com action≠read NÃO pode degradar
SILENCIOSO p/ fetch quando falta Playwright (o agente acha que tirou screenshot e recebeu só texto)."""
from __future__ import annotations

import io

import pytest


def _fake_proc(killed):
    class FakeProc:
        stdout = iter(())
        stdin = io.StringIO()

        def terminate(self):
            killed["v"] = True

        def wait(self, timeout=None):
            pass

        def kill(self):
            killed["v"] = True
    return FakeProc()


def test_mcp_stdio_kills_proc_on_request_timeout():
    from okami.integrations.mcp import McpError, McpStdioClient
    c = McpStdioClient("dummy", timeout=0.15)
    killed = {"v": False}
    c.proc = _fake_proc(killed)                 # _q vazio → _request estoura no prazo
    with pytest.raises(McpError):
        c._request("ping", {})
    assert killed["v"] is True                   # matou o subprocesso → não vaza proc/thread bloqueada


def test_mcp_stdio_kills_proc_when_server_closes():
    from okami.integrations.mcp import McpError, McpStdioClient
    c = McpStdioClient("dummy", timeout=2.0)
    killed = {"v": False}
    c.proc = _fake_proc(killed)
    c._q.put(None)                               # servidor fechou (EOF)
    with pytest.raises(McpError):
        c._request("ping", {})
    assert killed["v"] is True


# ── browse: action≠read sem Playwright → mensagem CLARA, não fetch silencioso ──
def _ctx():
    from okami.core.tools.base import ToolContext
    return ToolContext(workspace=".")


def test_browse_action_needs_playwright_is_explicit(monkeypatch):
    import okami.core.tools.agentic as ag
    monkeypatch.setattr(ag, "_has_playwright", lambda: False)
    res = ag.Browse().run({"url": "https://example.com", "action": "screenshot"}, _ctx())
    assert res.ok is False and "playwright" in res.output.lower()   # não finge que tirou screenshot


def test_browse_read_still_works_without_playwright(monkeypatch):
    import okami.core.tools.agentic as ag
    import okami.integrations.browser as br
    monkeypatch.setattr(ag, "_has_playwright", lambda: False)
    monkeypatch.setattr(br, "browse", lambda *a, **k: "TEXTO DA PÁGINA")
    res = ag.Browse().run({"url": "https://example.com", "action": "read"}, _ctx())
    assert res.ok and "TEXTO" in res.output                         # read degrada p/ fetch normalmente
