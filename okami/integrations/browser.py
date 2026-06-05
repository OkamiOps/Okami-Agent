"""Browser automation (§13). Com Playwright (`pip install ".[browser]"`): navega, clica, preenche,
screenshot. SEM Playwright: degrada p/ fetch read-only (urllib + strip de HTML) — ainda lê páginas.
"""

from __future__ import annotations

import re

_MAX = 6000


def _strip_html(html: str) -> str:
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def fetch(url: str, max_chars: int = _MAX) -> str:
    from okami.core.net_guard import BlockedURL, guarded_urlopen
    try:
        with guarded_urlopen(url, timeout=20, headers={"User-Agent": "okami/1.0"}) as r:  # #6 anti-SSRF
            return _strip_html(r.read(300_000).decode("utf-8", "ignore"))[:max_chars]
    except BlockedURL as e:
        return f"(URL recusada: {e})"
    except Exception as e:  # noqa: BLE001
        return f"(erro ao buscar {url}: {e})"


def browse(url: str, action: str = "read", selector: str | None = None, text: str | None = None,
           screenshot: str | None = None, max_chars: int = _MAX) -> str:
    """action: read | click | fill | screenshot. click/fill/screenshot exigem Playwright."""
    from okami.core.net_guard import BlockedURL, validate_public_url
    try:
        validate_public_url(url)                      # #6: vale tb p/ o goto do Playwright
    except BlockedURL as e:
        return f"(URL recusada: {e})"
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return fetch(url, max_chars)                  # sem Playwright → read-only
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(url, timeout=30000)
            if action == "click" and selector:
                page.click(selector, timeout=10000)
            elif action == "fill" and selector:
                page.fill(selector, text or "", timeout=10000)
            elif action == "screenshot" and screenshot:
                page.screenshot(path=screenshot)
                return f"screenshot salvo: {screenshot}"
            return page.inner_text("body")[:max_chars]
        finally:
            browser.close()
