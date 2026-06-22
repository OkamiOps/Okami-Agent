"""WebFetch: identificar-se como NAVEGADOR REAL, não 'okami/1.0' (que levava 403 na cara em muitos
sites por bloqueio de User-Agent). Não vence Cloudflare/JS — isso precisa de browser de verdade — mas
resolve a classe grande de '403 só porque o UA é robô'."""
from __future__ import annotations


def _fake_resp(body=b"<html>oi</html>"):
    class R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n=-1):
            return body
    return R()


def _capture_headers(monkeypatch):
    import okami.core.net_guard as ng
    cap: dict = {}

    def fake(url, timeout=20, headers=None):
        cap["headers"] = headers
        return _fake_resp()
    monkeypatch.setattr(ng, "guarded_urlopen", fake)
    return cap


def test_web_fetch_uses_realistic_browser_ua(monkeypatch):
    cap = _capture_headers(monkeypatch)
    import okami.integrations.web as web
    web._fetch_full("https://example.com")
    h = cap["headers"]
    assert "Mozilla" in h["User-Agent"] and "okami/1.0" not in h["User-Agent"]
    assert "Accept-Language" in h                              # cabeçalhos de navegador real


def test_browse_fetch_uses_realistic_browser_ua(monkeypatch):
    cap = _capture_headers(monkeypatch)
    import okami.integrations.browser as br
    br.fetch("https://example.com")
    assert "Mozilla" in cap["headers"]["User-Agent"]


def test_browser_headers_constant_is_browser_like():
    from okami.core.net_guard import BROWSER_HEADERS
    assert "Mozilla" in BROWSER_HEADERS["User-Agent"]
    assert "Accept" in BROWSER_HEADERS and "Accept-Language" in BROWSER_HEADERS
