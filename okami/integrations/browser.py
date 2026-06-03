"""Browser automation (§13). Com Playwright (`pip install ".[browser]"`): navega, clica, preenche,
screenshot. SEM Playwright: degrada p/ fetch read-only (urllib + strip de HTML) — ainda lê páginas.
"""

from __future__ import annotations

import re
import urllib.request

_MAX = 6000


def _strip_html(html: str) -> str:
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def fetch(url: str, max_chars: int = _MAX) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "okami/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310
            return _strip_html(r.read(300_000).decode("utf-8", "ignore"))[:max_chars]
    except Exception as e:  # noqa: BLE001
        return f"(erro ao buscar {url}: {e})"


def browse(url: str, action: str = "read", selector: str | None = None, text: str | None = None,
           screenshot: str | None = None, max_chars: int = _MAX) -> str:
    """action: read | click | fill | screenshot. click/fill/screenshot exigem Playwright."""
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
