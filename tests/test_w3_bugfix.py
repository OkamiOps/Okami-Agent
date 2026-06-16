"""#16 caça de bugs (ondas 1–3): correções achadas pelos subagentes de auditoria."""
from __future__ import annotations

import pytest


# ── BUG: on_token (camada de DISPLAY) que levanta NÃO pode truncar/corromper a saída do modelo ──
def test_streaming_on_token_error_is_best_effort():
    from okami.llm.streaming import streaming_generate
    deltas = ["a", "b", "c"]
    seen = []

    def _boom(t):
        seen.append(t)
        if t == "b":
            raise RuntimeError("display crashou")     # erro de DISPLAY, não do provider

    comp = streaming_generate(None, [], on_token=_boom, _stream=iter(deltas),
                              _fallback=lambda: (_ for _ in ()).throw(AssertionError("não deve cair no fallback")))
    assert comp.text == "abc"                          # texto COMPLETO, não truncado em "a"
    assert seen == ["a", "b", "c"]                     # seguiu emitindo apesar do erro no "b"


# ── BUG: erro do provider na validação ao vivo pode conter a credencial → REDIGIR antes de reportar ──
def test_live_check_redacts_secret_in_error():
    from types import SimpleNamespace

    from okami.llm import provider_check
    pc = SimpleNamespace(name="g", api_key="AIza-FAKE", model="m")
    leaked = "sk-" + "ABCDEF1234567890ABCDEF1234567890"   # fake secret (concat p/ não tropeçar no scanner)

    def _boom(msgs):
        raise RuntimeError(f"403 invalid key {leaked} denied")

    rep = provider_check.live_check_transport("gemini_native", pc=pc, _caller=_boom)
    assert rep["ok"] is False
    assert leaked not in rep["error"]                  # credencial NÃO vaza no erro reportado
    assert "403" in rep["error"]                       # mas o diagnóstico útil permanece


# ── BUG: served_by malformado começando com "/" criava vendor "" (string vazia) ──
def test_summarize_by_vendor_guards_empty_vendor():
    from okami.llm.usage import summarize_by_vendor
    by = summarize_by_vendor({"s": {"usage": {"input": 5, "output": 1}, "served_by": "/modelo-sem-vendor"}})
    assert "" not in by                                # nunca um bucket de string vazia
    assert by["—"].input_tokens == 5                   # cai no não-atribuído


# ── BUG: passar só --tls-cert (sem --tls-key) servia HTTP silenciosamente (footgun) ──
def test_serve_dashboard_rejects_half_tls_config():
    from okami.gateway import web
    with pytest.raises(ValueError):
        web.serve_dashboard(host="127.0.0.1", token=None, certfile="/tmp/c.pem", keyfile=None)
    with pytest.raises(ValueError):
        web.serve_dashboard(host="127.0.0.1", token=None, certfile=None, keyfile="/tmp/k.pem")
