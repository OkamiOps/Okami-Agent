"""Resolução de ${ENV} (okami/core/envref) — Honcho/MCP não vazam mais o literal ${VAR}."""

from __future__ import annotations

from okami.core.envref import resolve_env, resolve_env_map


def test_resolve_brace_form(monkeypatch):
    monkeypatch.setenv("TOK", "abc123")
    assert resolve_env("${TOK}") == "abc123"
    assert resolve_env("https://${TOK}.example/v1") == "https://abc123.example/v1"


def test_resolve_bare_form(monkeypatch):
    monkeypatch.setenv("TOK", "xyz")
    assert resolve_env("$TOK/path") == "xyz/path"


def test_undefined_becomes_empty(monkeypatch):
    monkeypatch.delenv("NOPE", raising=False)
    assert resolve_env("${NOPE}") == ""                  # nunca devolve o literal ${NOPE}


def test_non_string_passthrough():
    assert resolve_env(None) is None
    assert resolve_env(42) == 42
    assert resolve_env(["a"]) == ["a"]


def test_resolve_map(monkeypatch):
    monkeypatch.setenv("AUTH", "Bearer-tok")
    out = resolve_env_map({"Authorization": "${AUTH}", "X-Plain": "ok", "n": 1})
    assert out == {"Authorization": "Bearer-tok", "X-Plain": "ok", "n": 1}


def test_mcp_headers_resolve_env(monkeypatch):
    """O header ${TOKEN} de um servidor MCP é resolvido (antes ia o literal pro servidor)."""
    monkeypatch.setenv("MCP_TOKEN", "real-token-99")
    captured = {}

    class FakeHttp:
        def __init__(self, url, headers, timeout):
            captured["url"], captured["headers"] = url, headers

        def start(self):
            return []

        def close(self):
            pass

    monkeypatch.setattr("okami.integrations.mcp.McpHttpClient", FakeHttp)
    from okami.integrations.mcp import load_mcp_tools
    load_mcp_tools({"docs": {"url": "https://mcp.example/", "headers": {"Authorization": "${MCP_TOKEN}"}}})
    assert captured["headers"]["Authorization"] == "real-token-99"
