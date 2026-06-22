"""WebFetch auto-fallback p/ browser real: o fetch estático (urllib) não renderiza JS nem passa
bloqueio brando (Cloudflare/casca-de-JS). smart_fetch tenta estático e, se vier bloqueado/vazio/casca,
re-tenta no Playwright (browser de verdade). Sem Playwright → devolve o estático. fetch/_render_js
injetados → testável sem rede nem browser real."""
from __future__ import annotations


def test_smart_fetch_keeps_static_when_good(monkeypatch):
    import okami.integrations.browser as br
    monkeypatch.setattr(br, "fetch", lambda url, mc=br._MAX: "conteúdo bom " * 50)
    monkeypatch.setattr(br, "_render_js", lambda url, mc=br._MAX: "NÃO DEVIA RENDERIZAR")
    assert "conteúdo bom" in br.smart_fetch("https://x.com")
    assert "RENDERIZAR" not in br.smart_fetch("https://x.com")   # estático bom → não chama o browser


def test_smart_fetch_renders_on_fetch_error(monkeypatch):
    import okami.integrations.browser as br
    monkeypatch.setattr(br, "fetch", lambda url, mc=br._MAX: "(erro ao buscar https://x.com: HTTP 403)")
    monkeypatch.setattr(br, "_render_js", lambda url, mc=br._MAX: "CONTEÚDO RENDERIZADO " + "y" * 300)
    assert "RENDERIZADO" in br.smart_fetch("https://x.com")      # 403 estático → browser real


def test_smart_fetch_renders_on_js_shell(monkeypatch):
    import okami.integrations.browser as br
    monkeypatch.setattr(br, "fetch", lambda url, mc=br._MAX: "Just a moment... Checking your browser")
    monkeypatch.setattr(br, "_render_js", lambda url, mc=br._MAX: "preço real R$ 12.345 " * 30)
    assert "preço real" in br.smart_fetch("https://x.com")       # desafio Cloudflare → renderiza


def test_smart_fetch_renders_on_tiny_body(monkeypatch):
    import okami.integrations.browser as br
    monkeypatch.setattr(br, "fetch", lambda url, mc=br._MAX: "ok")    # casca minúscula
    monkeypatch.setattr(br, "_render_js", lambda url, mc=br._MAX: "corpo renderizado " * 40)
    assert "renderizado" in br.smart_fetch("https://x.com")


def test_smart_fetch_no_playwright_returns_static(monkeypatch):
    import okami.integrations.browser as br
    monkeypatch.setattr(br, "fetch", lambda url, mc=br._MAX: "(erro ao buscar x: 403)")
    monkeypatch.setattr(br, "_render_js", lambda url, mc=br._MAX: None)   # Playwright ausente
    assert br.smart_fetch("https://x.com").startswith("(erro")


def test_smart_fetch_ssrf_block_never_renders(monkeypatch):
    import okami.integrations.browser as br
    called = []
    monkeypatch.setattr(br, "fetch", lambda url, mc=br._MAX: "(URL recusada: host interno)")
    monkeypatch.setattr(br, "_render_js", lambda url, mc=br._MAX: called.append(1) or "X")
    assert br.smart_fetch("https://x.com").startswith("(URL recusada")
    assert not called                                            # bloqueio SSRF → browser tb barraria


def test_web_extract_full_uses_smart_fetch(monkeypatch):
    import okami.integrations.browser as br
    import okami.integrations.web as web
    monkeypatch.setattr(br, "smart_fetch", lambda url, mc=200_000: "VIA_SMART_FETCH")
    assert web._fetch_full("https://x.com") == "VIA_SMART_FETCH"
