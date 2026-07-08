"""GPT Image via assinatura Codex (Responses API `image_generation`) — payload, SSE, fallback.

Substitui o caminho antigo (REST `/v1/images/generations|edits` — 401 com token OAuth de assinatura).
Ambos os fluxos (texto→imagem e imagem→imagem/edição) batem no MESMO endpoint
(`chatgpt.com/backend-api/codex/responses`); a diferença é só `input_image` no `input`.
"""
from __future__ import annotations

import base64
import json
from types import SimpleNamespace


def _cfg(media=None):
    return SimpleNamespace(media=media or {})


def _sse_bytes(*events: dict) -> list[bytes]:
    return [f"data: {json.dumps(e)}\n".encode() for e in events]


# --------------------------------------------------------------------- payload
def test_build_payload_text_to_image_has_no_input_image():
    from okami.llm.imagegen import _build_payload
    pay = _build_payload("um lobo", None, "gpt-image-2", "1024x1024", "medium", "gpt-5.5")
    content = pay["input"][0]["content"]
    assert content == [{"type": "input_text", "text": "um lobo"}]
    assert pay["store"] is False and pay["stream"] is True
    assert pay["tools"] == [{"type": "image_generation", "model": "gpt-image-2", "size": "1024x1024",
                             "quality": "medium", "output_format": "png", "background": "opaque",
                             "partial_images": 1}]
    assert pay["tool_choice"] == {"type": "allowed_tools", "mode": "required",
                                  "tools": [{"type": "image_generation"}]}


def test_build_payload_image_to_image_adds_input_image_parts(tmp_path):
    from okami.llm.imagegen import _build_payload
    ref = tmp_path / "foto.png"
    ref.write_bytes(b"\x89PNG\r\n")
    pay = _build_payload("vire um infográfico", [str(ref)], "gpt-image-2", "1024x1024", "high", "gpt-5.5")
    content = pay["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": "vire um infográfico"}
    assert len(content) == 2
    part = content[1]
    assert part["type"] == "input_image"
    assert part["image_url"].startswith("data:image/png;base64,")
    b64 = part["image_url"].split(",", 1)[1]
    assert base64.b64decode(b64) == b"\x89PNG\r\n"
    assert pay["tools"][0]["quality"] == "high"


# --------------------------------------------------------------------- SSE parse
def test_parse_sse_image_extracts_terminal_result():
    from okami.llm.imagegen import _parse_sse_image
    lines = _sse_bytes({"type": "image_generation_call", "result": "QUJD"},
                       {"type": "response.completed", "response": {}})
    assert _parse_sse_image(lines) == "QUJD"


def test_parse_sse_image_prefers_latest_partial_then_final():
    from okami.llm.imagegen import _parse_sse_image
    lines = _sse_bytes({"type": "response.image_generation_call.partial_image",
                        "partial_image_b64": "PARTIAL1"},
                       {"type": "response.image_generation_call.partial_image",
                        "partial_image_b64": "PARTIAL2"},
                       {"type": "image_generation_call", "result": "FINAL"})
    assert _parse_sse_image(lines) == "FINAL"


def test_parse_sse_image_raises_on_failed_event():
    import pytest
    from okami.llm.imagegen import _parse_sse_image
    lines = _sse_bytes({"type": "response.failed", "response": {"error": {"message": "boom"}}})
    with pytest.raises(RuntimeError, match="boom"):
        _parse_sse_image(lines)


def test_parse_sse_image_raises_when_no_image_found():
    import pytest
    from okami.llm.imagegen import _parse_sse_image
    lines = _sse_bytes({"type": "response.completed", "response": {}})
    with pytest.raises(RuntimeError, match="sem imagem"):
        _parse_sse_image(lines)


def test_parse_sse_image_ignores_done_and_malformed_lines():
    from okami.llm.imagegen import _parse_sse_image
    lines = [b"data: [DONE]\n", b"data: not-json\n",
            f'data: {json.dumps({"type": "image_generation_call", "result": "OK"})}\n'.encode()]
    assert _parse_sse_image(lines) == "OK"


# --------------------------------------------------------------------- generate_image (codex, mocked _send)
def test_generate_image_codex_writes_file(monkeypatch, tmp_path):
    from okami.llm import imagegen as ig
    monkeypatch.setattr(ig, "_codex_token_or_none", lambda: "tok")
    monkeypatch.setattr("okami.llm.oauth.codex_account_id", lambda: "acct-1")
    b64 = base64.b64encode(b"IMGBYTES").decode()
    sent = {}

    def fake_send(url, payload, headers, timeout):
        sent["url"], sent["headers"], sent["payload"] = url, headers, payload
        return _sse_bytes({"type": "image_generation_call", "result": b64},
                          {"type": "response.completed", "response": {}})

    out = tmp_path / "out.png"
    res = ig.generate_image("um lobo", str(out), _send=fake_send)
    assert res == str(out)
    assert out.read_bytes() == b"IMGBYTES"
    assert sent["url"].endswith("/codex/responses")
    assert sent["headers"]["Authorization"] == "Bearer tok"
    assert sent["headers"]["originator"] == "codex_cli_rs"
    assert sent["headers"]["ChatGPT-Account-Id"] == "acct-1"


def test_generate_image_codex_explicit_token_skips_login_lookup(monkeypatch, tmp_path):
    from okami.llm import imagegen as ig
    monkeypatch.setattr(ig, "_codex_token_or_none", lambda: (_ for _ in ()).throw(AssertionError("não devia chamar")))
    monkeypatch.setattr("okami.llm.oauth.codex_account_id", lambda: "")
    b64 = base64.b64encode(b"X").decode()

    def fake_send(url, payload, headers, timeout):
        return _sse_bytes({"type": "image_generation_call", "result": b64})

    out = tmp_path / "out.png"
    ig.generate_image("x", str(out), token="explicit-tok", _send=fake_send)
    assert out.read_bytes() == b"X"


# --------------------------------------------------------------------- fallback
def test_image_config_none_without_setup():
    from okami.llm.imagegen import image_config
    assert image_config(_cfg()) is None
    assert image_config(_cfg({"image": {}})) is None


def test_image_config_resolves_named_backend():
    from okami.llm.imagegen import image_config
    cfg = _cfg({"image": {"backend": "flux", "api_key_env": "FAL_KEY"}})
    ic = image_config(cfg)
    assert ic["url"].endswith("/flux/dev") and ic["model"] == "flux-dev" and ic["api_key_env"] == "FAL_KEY"


def test_image_config_unknown_backend_is_none():
    from okami.llm.imagegen import image_config
    assert image_config(_cfg({"image": {"backend": "nope"}})) is None


def test_image_config_direct_url():
    from okami.llm.imagegen import image_config
    cfg = _cfg({"image": {"url": "https://x/img", "model": "m", "api_key_env": "K"}})
    ic = image_config(cfg)
    assert ic == {"url": "https://x/img", "model": "m", "api_key_env": "K", "backend": ""}


def test_generate_image_falls_back_when_codex_not_logged_in(monkeypatch, tmp_path):
    from okami.llm import imagegen as ig
    monkeypatch.setattr(ig, "_codex_token_or_none", lambda: None)
    monkeypatch.setenv("FAL_KEY", "k")
    cfg = _cfg({"image": {"url": "https://x/img", "model": "m", "api_key_env": "FAL_KEY"}})
    calls = {}

    def fake_post(url, body, headers):
        calls["url"], calls["body"], calls["auth"] = url, body, headers.get("Authorization")
        return {"data": [{"b64_json": base64.b64encode(b"FBIMG").decode()}]}

    out = tmp_path / "fb.png"
    res = ig.generate_image("um gato", str(out), cfg=cfg, _post=fake_post)
    assert res == str(out) and out.read_bytes() == b"FBIMG"
    assert calls["url"] == "https://x/img" and calls["auth"] == "Bearer k"
    assert calls["body"]["prompt"] == "um gato" and calls["body"]["model"] == "m"


def test_generate_image_falls_back_when_codex_call_fails(monkeypatch, tmp_path):
    from okami.llm import imagegen as ig
    monkeypatch.setattr(ig, "_codex_token_or_none", lambda: "tok")
    monkeypatch.setattr("okami.llm.oauth.codex_account_id", lambda: "")
    monkeypatch.setenv("FAL_KEY", "k")
    cfg = _cfg({"image": {"url": "https://x/img", "model": "m", "api_key_env": "FAL_KEY"}})

    def fake_send(url, payload, headers, timeout):
        raise RuntimeError("codex image HTTP 403: cf-mitigated:challenge")

    def fake_post(url, body, headers):
        return {"data": [{"b64_json": base64.b64encode(b"FBIMG2").decode()}]}

    out = tmp_path / "fb2.png"
    res = ig.generate_image("um gato", str(out), cfg=cfg, _send=fake_send, _post=fake_post)
    assert res == str(out) and out.read_bytes() == b"FBIMG2"


def test_generate_image_no_codex_no_fallback_raises(monkeypatch, tmp_path):
    import pytest
    from okami.llm import imagegen as ig
    monkeypatch.setattr(ig, "_codex_token_or_none", lambda: None)
    out = tmp_path / "x.png"
    with pytest.raises(RuntimeError, match="Sem token Codex"):
        ig.generate_image("um gato", str(out), cfg=_cfg())


def test_generate_image_fallback_missing_api_key_raises(monkeypatch, tmp_path):
    import pytest
    from okami.llm import imagegen as ig
    monkeypatch.setattr(ig, "_codex_token_or_none", lambda: None)
    monkeypatch.delenv("FAL_KEY", raising=False)
    cfg = _cfg({"image": {"url": "https://x/img", "model": "m", "api_key_env": "FAL_KEY"}})
    out = tmp_path / "x.png"
    with pytest.raises(RuntimeError, match="FAL_KEY"):
        ig.generate_image("um gato", str(out), cfg=cfg)


def test_generate_image_fallback_blocks_ssrf_result_url(monkeypatch, tmp_path):
    import pytest
    from okami.llm import imagegen as ig
    monkeypatch.setattr(ig, "_codex_token_or_none", lambda: None)
    cfg = _cfg({"image": {"url": "https://x/img", "model": "m", "api_key_env": ""}})

    def fake_post(url, body, headers):
        return {"data": [{"url": "http://169.254.169.254/latest/meta-data/"}]}

    out = tmp_path / "x.png"
    with pytest.raises(Exception):  # BlockedURL do net_guard
        ig.generate_image("um gato", str(out), cfg=cfg, _post=fake_post)


def test_image_backends_lists_named_presets():
    from okami.llm.imagegen import image_backends
    names = {b["name"] for b in image_backends()}
    assert {"flux", "flux-pro", "openrouter"} <= names
