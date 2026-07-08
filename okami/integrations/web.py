"""Pesquisa na web (pesquisa #6 item 1) — backend DDGS zero-key, plugável.

O Okami já tem `browse(url)` (abre URL CONHECIDA). Isto é o que faltava: PESQUISAR. Backend grátis
sem chave (DDGS / DuckDuckGo). Sem o pacote → SearchUnavailable com hint de instalação (lazy-deps).
Backends com chave (Tavily/Exa/Firecrawl) podem ser somados depois sob a mesma `web_search`.
"""
from __future__ import annotations

import hashlib as _hashlib
import re as _re
from pathlib import Path as _Path
from urllib.parse import urlparse as _urlparse


class SearchUnavailable(RuntimeError):
    """Nenhum backend de busca disponível (ex.: pacote ddgs não instalado)."""


def _ddgs_search(query: str, limit: int) -> list[dict]:
    """Backend DDGS (zero-key). Devolve [{title, href, body}]. Levanta SearchUnavailable se o pacote
    não está instalado. Isolável p/ teste."""
    try:
        from ddgs import DDGS                         # pacote novo
    except ImportError:
        try:
            from duckduckgo_search import DDGS        # nome antigo (compat)
        except ImportError:
            raise SearchUnavailable("pacote de busca ausente") from None
    with DDGS() as ddgs:
        return list(ddgs.text(query, max_results=limit))


_EXTRACT_SUMMARIZE_PROMPT = (
    "Resuma o trecho de página web abaixo PRESERVANDO fatos, números, nomes e trechos de código "
    "relevantes; corte navegação/boilerplate/repetição. Seja denso e fiel — não invente.")


_B64_IMG = _re.compile(r"data:image/[^;,\s]+;base64,[A-Za-z0-9+/=\s]+")


def _strip_base64(text: str) -> str:
    """Tira blobs base64 de imagem (data:image/...;base64,...) do conteúdo extraído — são lixo enorme que
    estoura o contexto sem informação útil. Op de string pura."""
    return _B64_IMG.sub("[imagem base64 removida]", text or "")


def _slug_for_url(url: str) -> str:
    """Nome de arquivo estável e legível a partir da URL: host-curto + hash da URL inteira (evita
    colisão entre paths diferentes do mesmo host)."""
    host = (_urlparse(url).hostname or "page").replace(":", "_")
    slug = _re.sub(r"[^A-Za-z0-9._-]", "-", host)[:60].strip("-") or "page"
    digest = _hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
    return f"{slug}-{digest}"


def _store_full_text(workspace: str, url: str, content: str) -> str | None:
    """Grava o texto COMPLETO extraído em `<workspace>/.okami/webcache/<slug>-<hash>.md` antes de
    truncar/resumir — sem isso, se o resumo derrubar um fato, ele está PERDIDO (mirror Hermes
    web_tools.py:461-570 _store_full_text). Best-effort: falha na gravação não derruba o extract."""
    try:
        cache_dir = _Path(workspace or ".") / ".okami" / "webcache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = cache_dir / f"{_slug_for_url(url)}.md"
        path.write_text(content, encoding="utf-8")
        return str(path)
    except Exception:  # noqa: BLE001 — cache é best-effort, nunca derruba o extract
        return None


def _truncate_head_tail(content: str, limit: int) -> str:
    """Head+tail truncation (~75%/25%) com marcador no meio — página grande sem sumarizador auxiliar
    perdia SÓ a cauda (conclusão, últimas entradas) no truncamento antigo (`raw[:max_chars]`). Mirror
    Hermes web_tools.py:497-570 `_truncate_with_footer`; corta em fronteira de linha quando dá."""
    if len(content) <= limit:
        return content
    head_budget = max(1, int(limit * 0.75))
    tail_budget = max(1, limit - head_budget)
    head = content[:head_budget]
    tail = content[-tail_budget:]
    nl = head.rfind("\n")
    if nl > head_budget * 0.5:
        head = head[:nl]
    nl = tail.find("\n")
    if 0 <= nl < tail_budget * 0.5:
        tail = tail[nl + 1:]
    omitted = len(content) - len(head) - len(tail)
    marker = f"\n\n[... {omitted:,} chars omitidos ...]\n\n"
    return head + marker + tail


def web_extract(url: str, *, max_chars: int = 8000, chunk: int = 8000, fetch=None, summarize=None,
                 workspace: str = ".") -> str:
    """Lê uma página e, se for grande, CHUNKA + resume via modelo auxiliar (preserva fato/código, corta
    tokens). Página pequena passa direto. `fetch(url)->texto` e `summarize(txt)->resumo` injetáveis.
    Antes de truncar/resumir, o texto COMPLETO é gravado em cache (`<workspace>/.okami/webcache/`) —
    o resumo/truncamento pode perder fato, o cache não (mirror Hermes cache-before-truncate)."""
    from okami.core.net_guard import BlockedURL, validate_public_url
    try:
        validate_public_url(url)                      # #6 anti-SSRF (reusa do browse)
    except BlockedURL as e:
        return f"(URL recusada: {e})"
    fetch = fetch or (lambda u: _fetch_full(u))
    try:
        raw = fetch(url)
    except Exception as e:  # noqa: BLE001
        return f"(erro ao buscar {url}: {e})"
    raw = _strip_base64(raw)                          # blob base64 de imagem = lixo enorme no contexto → remove
    if len(raw) <= max_chars:
        return raw                                    # página pequena: sem cache, sem truncamento
    cache_path = _store_full_text(workspace, url, raw)   # FIX: full text salvo ANTES de resumir/truncar
    if summarize is None:
        out = _truncate_head_tail(raw, max_chars)
        if cache_path:
            out += f"\n\n[texto completo salvo em: {cache_path}]"
        return out
    parts = []
    for i in range(0, len(raw), chunk):
        try:
            parts.append(summarize(raw[i:i + chunk]))
        except Exception:  # noqa: BLE001 — chunk que falhou → pula (best-effort)
            continue
    out = "\n\n".join(p for p in parts if p) or _truncate_head_tail(raw, max_chars)
    if cache_path:
        out += f"\n\n[texto completo salvo em: {cache_path}]"
    return out


def _fetch_full(url: str, cap: int = 200_000) -> str:
    """Texto completo da página (sem o teto de 6000 do browse) — entrada do sumarizador. smart_fetch:
    estático com auto-fallback p/ browser real (Playwright) quando vem bloqueado/casca-de-JS."""
    from okami.integrations.browser import smart_fetch
    return smart_fetch(url, cap)


def web_search(query: str, limit: int = 5) -> list[dict]:
    """Pesquisa na web → lista normalizada [{title, url, snippet}]. Levanta SearchUnavailable se não
    há backend. Erros do backend (rede/parse) sobem como RuntimeError."""
    raw = _ddgs_search(query, max(1, min(int(limit), 20)))
    out = []
    for r in raw:
        out.append({"title": (r.get("title") or "").strip(),
                    "url": (r.get("href") or r.get("url") or "").strip(),
                    "snippet": (r.get("body") or r.get("snippet") or "").strip()})
    return out
