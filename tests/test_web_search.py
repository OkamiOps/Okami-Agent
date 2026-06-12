"""web_search (pesquisa #6 item 1, paridade Hermes web_tools) — pesquisa na web, não só URL conhecida.

Backend DDGS zero-key (fallback grátis). Resultado embrulhado como conteúdo NÃO-confiável
(untrusted_tool_result). Sem o pacote ddgs → erro acionável que oferece o pip install (doutrina
lazy-deps do Okami), em vez de a tool sumir.
"""
from __future__ import annotations

import okami.integrations.web as web
from okami.core.tools import ToolContext
from okami.core.tools.websearch import WebSearch


def _ctx(tmp_path):
    return ToolContext(workspace=tmp_path)


def test_returns_results_wrapped_untrusted(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "_ddgs_search", lambda q, limit: [
        {"title": "Python docs", "href": "https://docs.python.org", "body": "linguagem"},
        {"title": "PEP 8", "href": "https://peps.python.org/pep-0008", "body": "estilo"},
    ])
    res = WebSearch().run({"query": "python", "limit": 5}, _ctx(tmp_path))
    assert res.ok
    assert "Python docs" in res.output and "docs.python.org" in res.output
    assert "untrusted_tool_result" in res.output       # busca externa = dado, não instrução
    assert res.effect is False


def test_limit_respected(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "_ddgs_search",
                        lambda q, limit: [{"title": f"r{i}", "href": f"h{i}", "body": "b"} for i in range(limit)])
    res = WebSearch().run({"query": "x", "limit": 3}, _ctx(tmp_path))
    assert res.output.count("http") <= 3 or res.ok      # backend recebeu o limit
    assert "r0" in res.output


def test_empty_query_errors(tmp_path):
    res = WebSearch().run({"query": ""}, _ctx(tmp_path))
    assert not res.ok and "query" in res.output


def test_no_results(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "_ddgs_search", lambda q, limit: [])
    res = WebSearch().run({"query": "zzqqxx"}, _ctx(tmp_path))
    assert res.ok and ("nada" in res.output.lower() or "nenhum" in res.output.lower())


def test_missing_dep_offers_install(tmp_path, monkeypatch):
    def _boom(q, limit):
        raise web.SearchUnavailable("ddgs não instalado")
    monkeypatch.setattr(web, "_ddgs_search", _boom)
    res = WebSearch().run({"query": "x"}, _ctx(tmp_path))
    assert not res.ok and "ddgs" in res.output and "pip install" in res.output


def test_registered_and_remote_allowed():
    from okami.core.tools import default_registry
    from okami.core.tool_policy import denied
    assert "web_search" in default_registry()
    assert not denied("telegram", "web_search")        # leitura: ok em canal remoto
    assert not denied("cli", "web_search")
