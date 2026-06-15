"""#10: recuperação REATIVA de erro de provider — encolhe imagem grande + força refresh OAuth (401),
re-tentando O MESMO provider antes do failover (não perde a assinatura no turno)."""
from __future__ import annotations

import base64
import io

from types import SimpleNamespace


def _data_url_image(size, fmt="PNG"):
    from PIL import Image
    img = Image.new("RGB", size, (123, 50, 200))
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    mime = "image/png" if fmt == "PNG" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _img_dims(url):
    from PIL import Image
    b64 = url.split(",", 1)[1]
    return Image.open(io.BytesIO(base64.b64decode(b64))).size


def test_is_image_too_large():
    from okami.llm.recovery import is_image_too_large
    assert is_image_too_large("image exceeds 5 MB maximum")
    assert is_image_too_large("maximum image size is 8000px")
    assert not is_image_too_large("rate limit exceeded")


def test_shrink_images_resizes_big_native_image():
    from okami.llm.recovery import shrink_images
    big = _data_url_image((3000, 2000))
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": "olha isso"},
        {"type": "image_url", "image_url": {"url": big}}]}]
    out = shrink_images(msgs, max_dim=1568)
    new_url = out[0]["content"][1]["image_url"]["url"]
    assert max(_img_dims(new_url)) <= 1568            # encolheu
    assert out[0]["content"][0]["text"] == "olha isso"  # texto intacto


def test_shrink_images_leaves_small_and_textonly_untouched():
    from okami.llm.recovery import shrink_images
    small = _data_url_image((200, 200))
    msgs = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": small}}]},
            {"role": "user", "content": "só texto"}]
    out = shrink_images(msgs, max_dim=1568)
    assert out is msgs                                 # nada a encolher → mesma lista (sem cópia)


def test_refresh_oauth_codex(monkeypatch):
    from okami.llm import oauth, recovery
    monkeypatch.setattr(oauth, "force_refresh_codex", lambda *a, **k: "novo-token-abc")
    assert recovery.refresh_oauth(SimpleNamespace(transport="codex_oauth", name="codex")) is True
    monkeypatch.setattr(oauth, "force_refresh_codex", lambda *a, **k: None)
    assert recovery.refresh_oauth(SimpleNamespace(transport="codex_oauth", name="codex")) is False


def test_refresh_oauth_non_oauth_transport_is_noop():
    from okami.llm.recovery import refresh_oauth
    assert refresh_oauth(SimpleNamespace(transport="litellm", name="x")) is False


def test_force_refresh_codex(monkeypatch):
    from okami.llm import oauth
    monkeypatch.setattr(oauth, "load_tokens", lambda p: {"refresh_token": "rt-1"})
    monkeypatch.setattr(oauth, "_codex_refresh", lambda rt, now: {"access_token": "fresh-xyz"})
    assert oauth.force_refresh_codex() == "fresh-xyz"
    monkeypatch.setattr(oauth, "load_tokens", lambda p: {})       # sem refresh_token → None
    assert oauth.force_refresh_codex() is None
