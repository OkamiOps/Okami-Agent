"""Caça de bugs #12 — defeitos no código novo das ondas A-D. RED→GREEN."""
from __future__ import annotations

import sys
from types import SimpleNamespace


# ── normalize_usage não mapeava os tokens de bedrock/gemini (mostrava 0) ──
def test_normalize_usage_bedrock_tokens():
    from okami.llm.usage import normalize_usage
    u = normalize_usage({"inputTokens": 10, "outputTokens": 5}, transport="bedrock_native")
    assert u.input_tokens == 10 and u.output_tokens == 5


def test_normalize_usage_gemini_tokens():
    from okami.llm.usage import normalize_usage
    u = normalize_usage({"usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 3}}, transport="gemini_native")
    assert u.input_tokens == 7 and u.output_tokens == 3


# ── gemini_native_complete passava systemInstruction no kwarg ERRADO (config=) e perdia o generationConfig ──
def test_gemini_complete_passes_system_instruction_correctly(monkeypatch):
    captured = {}

    class _Models:
        def generate_content(self, **kw):
            captured.update(kw)
            return {"candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}]}

    class _Client:
        def __init__(self, **kw):
            self.models = _Models()

    fake_genai = SimpleNamespace(Client=_Client)
    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(genai=fake_genai))
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setattr("okami.core.lazy_deps.ensure", lambda *a, **k: None)

    from okami.llm.gemini_native import gemini_native_complete
    pc = SimpleNamespace(name="g", model="gemini-3", api_key="k", params={})
    comp = gemini_native_complete(pc, [{"role": "system", "content": "seja conciso"},
                                       {"role": "user", "content": "oi"}], "gemini-3",
                                  {"generation_config": {"maxOutputTokens": 50}})
    assert comp.text == "ok"
    # systemInstruction NÃO pode ir no kwarg 'config' cru; deve ir como system_instruction (ou dentro do config)
    cfg = captured.get("config")
    sysi = captured.get("system_instruction")
    assert (sysi and "conciso" in str(sysi)) or (isinstance(cfg, dict) and "conciso" in str(cfg.get("system_instruction", "")))
    # generationConfig não pode sumir
    assert isinstance(cfg, dict) and cfg.get("maxOutputTokens") == 50 or "maxOutputTokens" in str(cfg)
