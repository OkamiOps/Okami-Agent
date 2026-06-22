"""Caça it.4: link com '(' não trunca a URL; MEDIA: não exfiltra segredo/arquivo de sistema; integrações
não crasham com resposta não-JSON."""
from __future__ import annotations


def test_markdown_link_with_parens_not_truncated():
    from okami.channels.markdown_telegram import to_html
    html = to_html("veja [doc](https://en.wikipedia.org/wiki/Test_(disambiguation))")
    assert "Test_(disambiguation)" in html and 'href="https://en.wikipedia.org/wiki/Test_(disambiguation)"' in html


def test_media_blocks_sensitive_and_system_paths():
    from okami.channels.media import extract_media
    _clean, items = extract_media('aqui MEDIA:"/etc/passwd" e MEDIA:"/root/.ssh/id_rsa" e MEDIA:"foto.png"')
    paths = [m.path for m in items]
    assert not any("passwd" in p or "id_rsa" in p for p in paths)     # exfil bloqueado
    assert any("foto.png" in p for p in paths)                        # mídia legítima passa


def test_integration_json_decode_raises_runtime_not_crash(monkeypatch):
    """homeassistant/feishu/x_search: resposta não-JSON vira RuntimeError claro, não JSONDecodeError cru."""
    import io
    import urllib.request
    import okami.integrations.x_search as xs

    class _R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _R(b"<html>erro 500</html>"))
    import pytest
    with pytest.raises(RuntimeError, match="não-JSON"):
        xs._default_post("https://x.test", {}, {})
