"""Caça de bugs dos resíduos #14 (subagentes) — defeitos confirmados. RED→GREEN."""
from __future__ import annotations

import hashlib

from types import SimpleNamespace


# ── 1: tirith checksum casava por SUFIXO de path (endswith) → linha errada ──
def test_tirith_checksum_normal_install(tmp_path):
    from okami.core.tirith import install_tirith
    payload = b"REAL-BINARY"
    checks = f"{hashlib.sha256(payload).hexdigest()}  tirith_test.tar.gz\n"

    def _fetch(url):
        return checks.encode() if url.endswith("checksums.txt") else payload

    path = install_tirith(version="v1", dest=tmp_path, asset_name="tirith_test.tar.gz",
                          _fetch=_fetch, _extract=lambda d, p: str(p) + "/tirith")
    assert path is not None


def test_tirith_checksum_rejects_wrong_basename_match(tmp_path):
    from okami.core.tirith import install_tirith
    payload = b"REAL-BINARY"
    # SÓ uma linha, de um arquivo cujo basename DIFERE — não pode casar por endswith parcial
    checks = f"{hashlib.sha256(payload).hexdigest()}  evil-tirith_test.tar.gz\n"

    def _fetch(url):
        return checks.encode() if url.endswith("checksums.txt") else payload

    path = install_tirith(version="v1", dest=tmp_path, asset_name="tirith_test.tar.gz",
                          _fetch=_fetch, _extract=lambda d, p: "x")
    assert path is None                       # 'evil-tirith_test.tar.gz' ≠ 'tirith_test.tar.gz' → recusa


# ── 2: run_swarm não forçava string do run_fn (None propagava) ──
def test_run_swarm_coerces_non_string(tmp_path):
    from okami.automation.swarm import blackboard_read, run_swarm
    bb = tmp_path / "s.json"
    res = run_swarm("m", [{"title": "a", "body": "x"}], run_fn=lambda p: None, blackboard=str(bb))
    assert isinstance(res["synthesis"], str)          # None coagido p/ string
    for e in blackboard_read(bb):
        assert isinstance(e["data"].get("output", e["data"].get("synthesis", e["data"].get("verdict", ""))), str)


# ── 3: .envrc (direnv, guarda segredo) não era barrado pelo _SENSITIVE_PATH ──
def test_sensitive_path_blocks_envrc():
    from okami.core.tools.base import _SENSITIVE_PATH
    assert _SENSITIVE_PATH.search("cat .envrc")        # direnv → BARRADO
    assert _SENSITIVE_PATH.search("/proj/.envrc")
    # sem regressão: .env barrado, .env.example liberado
    assert _SENSITIVE_PATH.search("cat .env")
    assert not _SENSITIVE_PATH.search("cat .env.example")


# ── 4: as_completion deixava tool_calls=None passar → len() crashava ──
def test_as_completion_normalizes_none_tool_calls():
    from okami.llm.usage import Completion, as_completion
    c = as_completion(Completion(text="oi", tool_calls=None))
    assert c.tool_calls == [] and len(c.tool_calls) == 0


# ── 5: gemini_native sem api_key dava ValueError opaco do SDK ──
def test_gemini_native_missing_key_clear_error():
    from okami.llm.gemini_native import gemini_native_complete
    pc = SimpleNamespace(name="g", model="gemini-3", api_key="", params={})
    try:
        gemini_native_complete(pc, [{"role": "user", "content": "x"}], "gemini-3")
        raise AssertionError("deveria ter levantado")
    except RuntimeError as e:
        assert "g" in str(e) and ("api" in str(e).lower() or "key" in str(e).lower())


# ── 6 (capability): tradução de IMAGEM nos transportes nativos (data-uri) ──
def test_gemini_translates_inline_image():
    from okami.llm.gemini_native import to_gemini_request
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": "o que é isto?"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}}]}]
    parts = to_gemini_request(msgs)["contents"][0]["parts"]
    assert any(p.get("inlineData", {}).get("data") == "QUJD" for p in parts)
    assert any("text" in p for p in parts)            # texto preservado


def test_bedrock_translates_inline_image():
    from okami.llm.bedrock_native import to_converse_request
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": "veja"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,QUJD"}}]}]
    blocks = to_converse_request(msgs)["messages"][0]["content"]
    assert any("image" in b for b in blocks) and any("text" in b for b in blocks)


# ── 7 (CRÍTICO): XSS — chat_id ia cru num onclick inline (esc não escapa aspas) ──
def test_dashboard_no_inline_onclick_with_raw_id():
    from okami.gateway.web import render_dashboard_html
    html = render_dashboard_html()
    # a linha de sessão NÃO pode injetar o chat_id num onclick inline; usa data-attribute + listener delegado
    assert "onclick=\"showSession(" not in html and "onclick='showSession(" not in html
    assert "data-sid" in html or "data-chat" in html


# ── 8: data-uri malformado (sem ;base64,) não pode virar fileData/bloco quebrado ──
def test_gemini_malformed_data_uri_skipped():
    from okami.llm.gemini_native import _content_parts
    parts = _content_parts([{"type": "text", "text": "x"},
                            {"type": "image_url", "image_url": {"url": "data:image/png,QUJD"}}])
    assert not any("fileData" in p and p["fileData"]["fileUri"].startswith("data:") for p in parts)
    assert any("text" in p for p in parts)            # texto preservado


def test_bedrock_malformed_data_uri_skipped():
    from okami.llm.bedrock_native import _content_blocks
    blocks = _content_blocks([{"type": "text", "text": "x"},
                              {"type": "image_url", "image_url": {"url": "data:image/png,naoehbase64"}}])
    assert all("image" not in b or b.get("image", {}).get("source") for b in blocks)
    assert any("text" in b for b in blocks)
