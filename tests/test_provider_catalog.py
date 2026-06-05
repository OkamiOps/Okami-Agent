"""Catálogo de providers (§3.5): presets bem-formados + cobertura estilo Hermes/OpenClaw."""

from __future__ import annotations

from okami.provider_catalog import PRESETS, menu_choices, preset


def test_keys_unique():
    keys = [p.key for p in PRESETS]
    assert len(keys) == len(set(keys))


def test_every_preset_is_well_formed():
    for p in PRESETS:
        assert p.key and p.label and p.model_prefix, p.key
        for f in p.fields:
            if f.kind == "secret":
                assert f.env, f"{p.key}: campo secret sem env var"   # segredo → .env, nunca YAML


def test_subscription_providers_use_oauth_or_cli():
    # restrição dura: codex/claude SEMPRE assinatura via OAuth/CLI — NUNCA pay-as-you-go (ToS).
    for key in ("codex", "claude"):
        p = preset(key)
        assert p.base.get("auth") == "oauth_subscription" and p.login, key


def test_minimax_uses_token_plan_subscription_key_not_payg():
    # MiniMax Token Plan (assinatura) = Subscription Key em Bearer (OpenAI-compat), conforme a doc oficial.
    # NÃO é pay-as-you-go: a chave vem do Token Plan e mora SÓ no .env (MINIMAX_API_KEY).
    p = preset("minimax")
    assert p.base.get("auth") == "api_key"
    secrets = [f for f in p.fields if f.kind == "secret"]
    assert secrets and secrets[0].env == "MINIMAX_API_KEY"
    assert "subscription" in p.hint.lower() or "token plan" in (secrets[0].q or "").lower()


def test_catalog_has_broad_coverage():
    keys = {p.key for p in PRESETS}
    # locais
    assert {"lmstudio", "ollama", "vllm", "llamacpp"} <= keys
    # APIs comuns (estilo Hermes/OpenClaw)
    assert {"openai", "openrouter", "deepseek", "gemini", "groq", "xai", "mistral",
            "qwen", "zai", "moonshot", "nvidia", "cerebras", "fireworks", "together"} <= keys
    assert len(PRESETS) >= 20


def test_api_presets_have_https_base():
    for p in PRESETS:
        base = p.base.get("api_base", "")
        if p.base.get("auth") == "api_key" and base and "localhost" not in base:
            assert base.startswith("https://"), f"{p.key}: API remota deve ser https"


def test_menu_choices_matches_presets():
    assert len(menu_choices()) == len(PRESETS)
    assert all(len(c) == 3 for c in menu_choices())          # (key, label, hint)
