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


# ------------------------------------------------------------------ cache-before-truncate (FIX 1/2)
def test_large_page_without_summarize_caches_full_text_and_head_tail_truncates(tmp_path):
    big = "".join(f"linha {i}\n" for i in range(3000))   # bem maior que max_chars, sem sumarizador
    out = web.web_extract("https://x.com/artigo", max_chars=2000,
                          fetch=lambda u: big, workspace=str(tmp_path))
    cache_dir = tmp_path / ".okami" / "webcache"
    files = list(cache_dir.glob("*.md"))
    assert len(files) == 1                             # texto completo persistido antes de truncar
    assert files[0].read_text(encoding="utf-8") == big  # cache tem o TEXTO INTEIRO, não o truncado
    assert str(files[0]) in out                         # path do cache aparece no resultado
    assert "linha 0\n" in out                            # cabeça preservada
    assert "linha 2999" in out                           # FIX 2: cauda preservada (não só a cabeça)
    assert "omitidos" in out                             # marcador explícito no meio


def test_large_page_with_summarize_also_caches_full_text(tmp_path):
    big = "conteúdo. " * 3000
    out = web.web_extract("https://x.com/artigo2", max_chars=2000, chunk=4000,
                          fetch=lambda u: big, summarize=lambda t: f"resumo-{len(t)}",
                          workspace=str(tmp_path))
    cache_dir = tmp_path / ".okami" / "webcache"
    files = list(cache_dir.glob("*.md"))
    assert len(files) == 1
    assert files[0].read_text(encoding="utf-8") == big
    assert str(files[0]) in out


def test_small_page_does_not_write_cache(tmp_path):
    web.web_extract("https://x.com", max_chars=1000, fetch=lambda u: "página curta",
                    workspace=str(tmp_path))
    assert not (tmp_path / ".okami" / "webcache").exists()   # página pequena: sem cache desnecessário


def test_truncate_head_tail_keeps_both_ends_with_marker():
    content = "".join(f"L{i}\n" for i in range(1000))
    out = web._truncate_head_tail(content, 500)
    assert out.startswith("L0\n")
    assert "L999" in out
    assert "omitidos" in out
    marker_pos = out.index("omitidos")
    assert out.index("L0") < marker_pos < out.index("L999")


# ------------------------------------------------------------------ tool
def test_tool_wraps_untrusted(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "web_extract", lambda url, **kw: "conteúdo resumido da página")
    ctx = ToolContext(workspace=tmp_path, cfg=object())
    res = WebExtract().run({"url": "https://example.com"}, ctx)
    assert res.ok and res.effect is False
    assert "untrusted_tool_result" in res.output      # página externa = dado, não instrução
    assert "conteúdo resumido" in res.output


def test_tool_passes_workspace_through(tmp_path, monkeypatch):
    seen = {}

    def _fake(url, **kw):
        seen.update(kw)
        return "ok"
    monkeypatch.setattr(web, "web_extract", _fake)
    ctx = ToolContext(workspace=tmp_path, cfg=object())
    WebExtract().run({"url": "https://example.com"}, ctx)
    assert seen.get("workspace") == str(tmp_path)     # tool roteia o workspace real p/ o cache


def test_tool_caches_full_text_end_to_end(tmp_path, monkeypatch):
    big = "".join(f"linha {i}\n" for i in range(3000))
    monkeypatch.setattr(web, "_fetch_full", lambda url, cap=200_000: big)   # sem rede
    ctx = ToolContext(workspace=tmp_path, cfg=None)   # cfg None → sem sumarizador → head+tail + cache
    res = WebExtract().run({"url": "https://example.com/big", "max_chars": 2000}, ctx)
    assert res.ok
    files = list((tmp_path / ".okami" / "webcache").glob("*.md"))
    assert len(files) == 1 and files[0].read_text(encoding="utf-8") == big  # texto cru completo no cache
    assert str(files[0]) in res.output                                       # path no resultado da tool
    assert "linha 2999" in res.output                                        # cauda preservada (head+tail)


def test_tool_empty_url(tmp_path):
    res = WebExtract().run({"url": ""}, ToolContext(workspace=tmp_path))
    assert not res.ok


def test_registered_and_remote_allowed():
    from okami.core.tools import default_registry
    from okami.core.tool_policy import denied
    assert "web_extract" in default_registry()
    assert not denied("telegram", "web_extract")
