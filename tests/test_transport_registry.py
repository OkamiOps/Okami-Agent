from dataclasses import replace

import pytest

from okami.config import ProviderConfig
from okami.llm.runtime import BillingRoute, RuntimeTarget
from okami.llm.transport_registry import (
    CompletionRequest,
    TransportRegistry,
    UnknownTransportError,
    default_transport_registry,
)
from okami.llm.usage import Completion


@pytest.fixture
def runtime_target():
    return RuntimeTarget(
        "p", "openai/gpt-4o", None, "chat_completions", "litellm", "env:P_KEY",
        frozenset({"tools"}), BillingRoute("p", "openai/gpt-4o", "metered"),
    )


@pytest.fixture
def provider_config():
    return ProviderConfig(name="p", model="openai/gpt-4o", api_key_env="P_KEY")


class FakeTransport:
    def complete(self, target, provider_config, request):
        return Completion(text=target.model, provider=target.provider, model=target.model)


def test_registry_selects_transport_by_runtime_target(runtime_target, provider_config):
    registry = TransportRegistry()
    registry.register("litellm", FakeTransport())
    result = registry.complete(runtime_target, provider_config, CompletionRequest(messages=[]))
    assert result.model == runtime_target.model


def test_unknown_transport_fails_with_registered_names(runtime_target, provider_config):
    registry = TransportRegistry()
    registry.register("known", FakeTransport())
    with pytest.raises(UnknownTransportError, match="known"):
        registry.complete(replace(runtime_target, transport="missing"), provider_config, CompletionRequest(messages=[]))


def test_existing_transport_names_remain_registered():
    assert {
        "litellm", "claude_cli", "codex_oauth", "minimax_oauth", "gemini_native",
        "bedrock_native", "gemini_cloudcode", "copilot_cli",
    } <= set(default_transport_registry().names())

