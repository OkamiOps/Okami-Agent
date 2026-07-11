import pytest

from okami.config import build_config
from okami.llm.target_resolver import TargetResolutionError, TargetResolver


def test_alias_and_model_override_resolve_through_one_resolver():
    cfg = build_config({
        "default_provider": "claude",
        "model_aliases": {"best": "claude/opus"},
        "providers": {"claude": {
            "model": "anthropic/claude-default",
            "models": ["claude-opus", "claude-sonnet"],
        }},
    })
    resolver = TargetResolver()
    assert resolver.resolve(cfg, token="best").model == "anthropic/claude-opus"
    assert resolver.resolve(cfg, provider="claude", model="claude-sonnet").model == "anthropic/claude-sonnet"


def test_api_mode_is_derived_from_transport():
    cfg = build_config({
        "default_provider": "codex",
        "providers": {"codex": {"model": "gpt-5.6", "transport": "codex_oauth"}},
    })
    assert TargetResolver().resolve(cfg).api_mode == "responses"


def test_capabilities_and_billing_route_are_derived():
    cfg = build_config({
        "default_provider": "p",
        "providers": {"p": {
            "model": "openai/gpt-4o",
            "native_tools": True,
            "capability": {"vision": True},
        }},
    })
    target = TargetResolver().resolve(cfg)
    assert {"tools", "native_tools", "vision"} <= target.capabilities
    assert target.billing_route.provider == "p"
    assert target.billing_route.model == "openai/gpt-4o"


def test_provider_typo_fails_with_available_provider_names():
    cfg = build_config({"default_provider": "p", "providers": {"p": {"model": "m"}}})
    with pytest.raises(TargetResolutionError, match=r"typo.*p"):
        TargetResolver().resolve(cfg, provider="typo")

