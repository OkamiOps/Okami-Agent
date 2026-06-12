"""web_extract com sumarização auxiliar (pesquisa #6 item 3, paridade Hermes web_tools).

Página grande → chunk + resume via modelo AUXILIAR barato (preserva fato/código, corta tokens), em
vez do truncamento burro do browse (cap 6000 chars). Página pequena passa direto. SSRF guard reusado.
"""
from __future__ import annotations

import okami.integrations.web as web
from okami.core.tools import ToolContext
from okami.core.tools.webextract import WebExtract


def test_small_page_passes_through():
    out = web.web_extract("https://x.com", max_chars=1000,
                          fetch=lambda u: "página curta", summarize=lambda txt: "RESUMO")
    assert out == "página curta"                      # menor que o teto → sem sumarização


def test_large_page_is_summarized():
    big = "linha de conteúdo. " * 2000               # ~38k chars
    calls = {"n": 0}

    def summ(txt):
        calls["n"] += 1
        return f"resumo-de-{len(txt)}-chars"
    out = web.web_extract("https://x.com", max_chars=4000, chunk=8000,
                          fetch=lambda u: big, summarize=summ)
    assert calls["n"] >= 2                             # quebrou em chunks
    assert "resumo-de-" in out


def test_extract_blocks_bad_url():
    out = web.web_extract("file:///etc/passwd", fetch=lambda u: "x", summarize=lambda t: "y")
    assert "recus" in out.lower() or "bloque" in out.lower()


# ------------------------------------------------------------------ tool
def test_tool_wraps_untrusted(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "web_extract", lambda url, **kw: "conteúdo resumido da página")
    ctx = ToolContext(workspace=tmp_path, cfg=object())
    res = WebExtract().run({"url": "https://example.com"}, ctx)
    assert res.ok and res.effect is False
    assert "untrusted_tool_result" in res.output      # página externa = dado, não instrução
    assert "conteúdo resumido" in res.output


def test_tool_empty_url(tmp_path):
    res = WebExtract().run({"url": ""}, ToolContext(workspace=tmp_path))
    assert not res.ok


def test_registered_and_remote_allowed():
    from okami.core.tools import default_registry
    from okami.core.tool_policy import denied
    assert "web_extract" in default_registry()
    assert not denied("telegram", "web_extract")
