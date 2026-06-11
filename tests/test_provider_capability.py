"""tool_mode derivado da CAPACIDADE (tier), não no chute (paridade Hermes models.dev).

Footgun antigo: tool_mode default 'json_text' (SEM enforcement) → modelo fraco/local respondia em
texto e NUNCA chamava tool, a menos que o preset setasse json_constrained na mão. Agora 'auto'
(default) deriva do tier: weak/local → json_constrained; strong → json_text; native_tools → native."""

from __future__ import annotations

from okami.config import ProviderConfig
from okami.llm.providers import _response_format


def _pc(**kw) -> ProviderConfig:
    kw.setdefault("name", "p")
    kw.setdefault("model", "openai/x")
    return ProviderConfig(**kw)


def test_default_tool_mode_is_auto():
    assert _pc().capability.tool_mode == "auto"


def test_local_tier_derives_json_constrained():
    assert _pc(tier="local").effective_tool_mode() == "json_constrained"


def test_weak_tier_derives_json_constrained():
    assert _pc(tier="weak").effective_tool_mode() == "json_constrained"


def test_strong_tier_derives_json_text():
    assert _pc(tier="strong").effective_tool_mode() == "json_text"


def test_unknown_tier_derives_json_text():
    assert _pc(tier="unknown").effective_tool_mode() == "json_text"


def test_native_tools_derives_native():
    assert _pc(tier="strong", native_tools=True).effective_tool_mode() == "native"


def test_explicit_tool_mode_wins_over_tier():
    # preset que fixou json_text num tier local → respeita o explícito (não re-deriva)
    pc = _pc(tier="local", capability={"tool_mode": "json_text"})
    assert pc.effective_tool_mode() == "json_text"


def test_explicit_constrained_on_strong_kept():
    pc = _pc(tier="strong", capability={"tool_mode": "json_constrained"})
    assert pc.effective_tool_mode() == "json_constrained"


def test_response_format_triggers_for_local_without_explicit():
    # o conserto de ponta: provider LOCAL sem tool_mode explícito JÁ entra no constrained decoding
    schema = {"type": "object", "properties": {"tool": {"type": "string"}}}
    rf = _response_format(_pc(tier="local"), schema)
    assert rf and rf["type"] == "json_schema"


def test_response_format_off_for_strong():
    schema = {"type": "object"}
    assert _response_format(_pc(tier="strong"), schema) is None


def test_catalog_local_providers_get_constrained():
    # presets locais do catálogo (lmstudio/ollama/vllm/llamacpp) caem em json_constrained sem precisar
    # declarar — antes ficavam no json_text mudo se o preset esquecesse de marcar.
    from okami.provider_catalog import PRESETS
    by_key = {p.key: p for p in PRESETS}
    for key in ("lmstudio", "ollama"):
        if key in by_key:
            base = dict(by_key[key].base)
            base.setdefault("name", key)
            base.setdefault("model", "openai/local")
            pc = ProviderConfig(**base)
            assert pc.effective_tool_mode() in ("json_constrained", "native"), key
