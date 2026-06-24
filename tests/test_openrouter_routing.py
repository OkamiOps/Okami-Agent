"""OpenRouter: hints de roteamento de provider (order/allow_fallbacks/sort/only/ignore/…) viram
extra_body.provider — SÓ quando o endpoint é OpenRouter (detectado por api_base contendo openrouter.ai, sem
hardcodar nome). Pra qualquer outra base (Ollama/OpenAI/etc.) o bloco NÃO é emitido."""
from __future__ import annotations

from okami.config import ProviderConfig
from okami.llm.providers import _kwargs


def _msgs():
    return [{"role": "user", "content": "oi"}]


def test_openrouter_routing_emitted_as_extra_body_provider():
    pc = ProviderConfig(name="or", model="x/y", api_base="https://openrouter.ai/api/v1",
                        provider_routing={"order": ["Together", "DeepInfra"], "allow_fallbacks": False})
    kw = _kwargs(pc, _msgs(), stream=False, model=None)
    assert kw["extra_body"]["provider"] == {"order": ["Together", "DeepInfra"], "allow_fallbacks": False}


def test_non_openrouter_base_does_not_emit():
    pc = ProviderConfig(name="oai", model="gpt-4o", api_base="https://api.openai.com/v1",
                        provider_routing={"order": ["X"]})
    kw = _kwargs(pc, _msgs(), stream=False, model=None)
    assert "provider" not in kw.get("extra_body", {})    # base não-OpenRouter → não emite


def test_no_routing_no_extra_body_provider():
    pc = ProviderConfig(name="or", model="x/y", api_base="https://openrouter.ai/api/v1")
    kw = _kwargs(pc, _msgs(), stream=False, model=None)
    assert "provider" not in kw.get("extra_body", {})
