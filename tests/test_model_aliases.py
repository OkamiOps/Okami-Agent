"""Resolver único de provider/modelo (okami/llm/model_aliases.py) — alias semântico, tier dinâmico,
passthrough provider/modelo, erro claro de typo, e a precedência -p/-m > sessão > local > default."""

from __future__ import annotations

import pytest
from okami.config import build_config
from okami.llm.model_aliases import ModelAliasError, effective, full_model_string, known_aliases, resolve


def _cfg(**extra):
    raw = {
        "default_provider": "claude",
        "providers": {
            "claude": {
                "model": "claude-subscription/claude-opus-4-8",
                "auth": "oauth_subscription", "transport": "claude_cli", "tier": "strong",
                "models": ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
            },
            "codex": {
                "model": "openai-codex/gpt-5.5",
                "auth": "oauth_subscription", "transport": "codex_oauth", "tier": "strong",
                "models": ["gpt-5.5", "gpt-5.4"],
            },
            "lmstudio": {
                "model": "openai/qwen3.5-4b-mtp", "api_base": "http://localhost:1234/v1",
                "api_key": "lm-studio", "tier": "local",
                "models": ["qwen3.5-4b-mtp", "qwen3.5-9b-mtp"],
            },
        },
        **extra,
    }
    return build_config(raw)


# --- alias semântico -------------------------------------------------------

def test_semantic_alias_resolves_provider_and_keyword_model():
    cfg = _cfg()
    assert resolve(cfg, "sonnet") == ("claude", "claude-sonnet-4-6")
    assert resolve(cfg, "opus") == ("claude", "claude-opus-4-8")
    assert resolve(cfg, "haiku") == ("claude", "claude-haiku-4-5-20251001")
    assert resolve(cfg, "codex") == ("codex", None)
    assert resolve(cfg, "gpt") == ("codex", None)


def test_alias_case_insensitive():
    cfg = _cfg()
    assert resolve(cfg, "SONNET") == resolve(cfg, "sonnet")


# --- tier dinâmico -----------------------------------------------------------

def test_tier_alias_fast_resolves_to_local_provider():
    cfg = _cfg()
    assert resolve(cfg, "fast") == ("lmstudio", None)


def test_tier_alias_smart_resolves_to_strong_provider_preferring_default():
    cfg = _cfg()   # default_provider=claude é strong → smart deve preferir o default já ativo
    assert resolve(cfg, "smart") == ("claude", None)


def test_tier_alias_never_hardcoded_switches_with_config():
    # o MESMO alias 'smart' muda de provider quando o default_provider muda — prova que não é hardcoded.
    raw = {
        "default_provider": "codex",
        "providers": {
            "claude": {"model": "claude-subscription/claude-opus-4-8", "auth": "oauth_subscription",
                       "transport": "claude_cli", "tier": "strong", "models": ["claude-opus-4-8"]},
            "codex": {"model": "openai-codex/gpt-5.5", "auth": "oauth_subscription",
                     "transport": "codex_oauth", "tier": "strong", "models": ["gpt-5.5"]},
        },
    }
    cfg = build_config(raw)
    assert resolve(cfg, "smart") == ("codex", None)


def test_tier_alias_missing_tier_raises_clear_error():
    raw = {
        "default_provider": "codex",
        "providers": {"codex": {"model": "openai-codex/gpt-5.5", "auth": "oauth_subscription",
                                "transport": "codex_oauth", "tier": "strong"}},
    }
    cfg = build_config(raw)
    with pytest.raises(ModelAliasError, match="tier='local'"):
        resolve(cfg, "fast")


# --- passthrough provider / provider/modelo ---------------------------------

def test_bare_provider_id_passthrough():
    cfg = _cfg()
    assert resolve(cfg, "lmstudio") == ("lmstudio", None)


def test_provider_slash_model_validated_against_catalog():
    cfg = _cfg()
    assert resolve(cfg, "claude/claude-sonnet-4-6") == ("claude", "claude-sonnet-4-6")


def test_provider_space_model_form():
    cfg = _cfg()
    assert resolve(cfg, "claude claude-sonnet-4-6") == ("claude", "claude-sonnet-4-6")


# --- typo/erro claro (sem silent pass-through) -------------------------------

def test_unknown_provider_raises_clear_error():
    cfg = _cfg()
    with pytest.raises(ModelAliasError, match="provider desconhecido"):
        resolve(cfg, "clawd")   # typo de 'claude'


def test_model_not_in_catalog_raises_clear_error():
    cfg = _cfg()
    with pytest.raises(ModelAliasError, match="não está no catálogo"):
        resolve(cfg, "claude/claude-opus-9000")


def test_empty_token_raises():
    cfg = _cfg()
    with pytest.raises(ModelAliasError):
        resolve(cfg, "")
    with pytest.raises(ModelAliasError):
        resolve(cfg, "   ")


# --- extensão via yaml model_aliases -----------------------------------------

def test_yaml_model_aliases_extend_table():
    cfg = _cfg(model_aliases={"barato": "lmstudio", "top": "claude/claude-opus-4-8"})
    assert resolve(cfg, "barato") == ("lmstudio", None)
    assert resolve(cfg, "top") == ("claude", "claude-opus-4-8")


def test_known_aliases_includes_tier_and_static():
    cfg = _cfg()
    names = {a for a, _, _ in known_aliases(cfg)}
    assert {"fast", "smart", "sonnet", "opus", "haiku", "codex"} <= names


# --- full_model_string (reaplica prefixo litellm) ----------------------------

def test_full_model_string_reapplies_provider_prefix():
    cfg = _cfg()
    assert full_model_string(cfg, "claude", "claude-sonnet-4-6") == "claude-subscription/claude-sonnet-4-6"


def test_full_model_string_passthrough_when_already_qualified():
    cfg = _cfg()
    assert full_model_string(cfg, "claude", "openai/gpt-5.5") == "openai/gpt-5.5"


def test_full_model_string_empty_model():
    cfg = _cfg()
    assert full_model_string(cfg, "claude", None) == ""


# --- precedência única (e): flag > sessão > local.yaml > default ------------

def test_precedence_flag_wins_over_session():
    cfg = _cfg()
    provider, model = effective(cfg, flag="opus", session_provider="codex", session_model="gpt-5.4")
    assert (provider, model) == ("claude", "claude-opus-4-8")


def test_precedence_session_wins_over_default_when_no_flag():
    cfg = _cfg()
    provider, model = effective(cfg, session_provider="codex", session_model="gpt-5.4")
    assert (provider, model) == ("codex", "gpt-5.4")


def test_precedence_default_when_nothing_set():
    cfg = _cfg()
    provider, model = effective(cfg)
    assert provider == cfg.default_provider
    assert model is None


def test_precedence_local_yaml_already_folded_into_default_provider():
    # okami.local.yaml é fundido ANTES do build_config (load_raw) — o "default" já reflete o override
    # local; o resolver não precisa saber da existência do arquivo.
    cfg = _cfg()
    cfg.default_provider = "codex"   # simula default_provider já sobrescrito pelo merge de local.yaml
    provider, model = effective(cfg)
    assert provider == "codex"
