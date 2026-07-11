from dataclasses import FrozenInstanceError

import pytest

from okami.config import build_config
from okami.llm.runtime import BillingRoute, RuntimeTarget, TargetRef
from okami.llm.target_resolver import TargetResolver


def test_runtime_target_is_hashable_and_immutable():
    target = RuntimeTarget(
        "openrouter",
        "anthropic/claude",
        "https://openrouter.ai/api/v1",
        "chat_completions",
        "litellm",
        "env:OPENROUTER_API_KEY",
        frozenset({"tools"}),
        BillingRoute("openrouter", "anthropic/claude", "metered"),
    )
    assert hash(target)
    with pytest.raises(FrozenInstanceError):
        target.model = "other"


def test_runtime_values_redact_resolved_secret(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret-value")
    cfg = build_config({
        "default_provider": "openrouter",
        "providers": {"openrouter": {
            "model": "openrouter/auto",
            "api_key_env": "OPENROUTER_API_KEY",
        }},
    })
    target = TargetResolver().resolve(cfg)
    assert target.credential_ref == "env:OPENROUTER_API_KEY"
    assert "secret-value" not in repr(target)
    assert "secret-value" not in repr(TargetRef("openrouter", credential_ref=target.credential_ref))


def test_runtime_target_redacts_literal_credential_identity():
    cfg = build_config({
        "default_provider": "p",
        "providers": {"p": {"model": "openai/gpt-4o", "api_key": "literal-secret"}},
    })
    target = TargetResolver().resolve(cfg)
    assert target.credential_ref != "literal-secret"
    assert "literal-secret" not in repr(target)


def test_runtime_target_accepts_qualified_litellm_model_id():
    cfg = build_config({
        "default_provider": "p",
        "providers": {"p": {"model": "openai/gpt-4o"}},
    })
    assert TargetResolver().resolve(cfg, model="anthropic/claude-sonnet").model == "anthropic/claude-sonnet"

