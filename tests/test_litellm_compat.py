import importlib
from types import SimpleNamespace

import pytest

from okami.config import ProviderConfig
from okami.llm.litellm_compat import LiteLLMCompatTransport, UnsupportedProviderParameter
from okami.llm.request import RequestContext, RequestTimeouts
from okami.llm.runtime import BillingRoute, RuntimeTarget
from okami.llm.transport_registry import CompletionRequest


@pytest.fixture
def runtime_target():
    return RuntimeTarget(
        "p", "openai/gpt-4o", None, "chat_completions", "litellm", "env:P_KEY",
        frozenset(), BillingRoute("p", "openai/gpt-4o", "metered"),
    )


@pytest.fixture
def provider_config():
    return ProviderConfig(name="p", model="openai/gpt-4o", api_key_env="P_KEY")


def _response(text="ok"):
    message = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")], usage=None)


class FakeClosableStream:
    def __init__(self):
        self.closed = False

    def __iter__(self):
        return iter(())

    def close(self):
        self.closed = True


def test_importing_providers_does_not_mutate_litellm_globals(monkeypatch):
    import okami.llm.litellm_compat as compat

    module = compat._lite_module()
    monkeypatch.setattr(module, "drop_params", False, raising=False)
    monkeypatch.setattr(module, "suppress_debug_info", False, raising=False)
    import okami.llm.providers as providers
    importlib.reload(providers)
    assert getattr(module, "drop_params", False) is False
    assert getattr(module, "suppress_debug_info", False) is False


def test_compat_drop_policy_warns_with_parameter_names(monkeypatch, runtime_target, provider_config):
    import okami.llm.litellm_compat as compat

    warning_calls = []

    def warning(message, *args, **kwargs):
        warning_calls.append((message, args, kwargs))

    monkeypatch.setattr(compat.logger, "warning", warning)
    monkeypatch.setattr(compat, "supported_params", lambda **kwargs: ["max_tokens"])
    monkeypatch.setattr(compat, "completion", lambda **kwargs: _response())
    request = CompletionRequest(messages=[], overrides={"temperature": 0.2, "max_tokens": 10})
    LiteLLMCompatTransport(drop_policy="warn").complete(runtime_target, provider_config, request)
    assert warning_calls == [
        ("LiteLLM compatibility dropped unsupported parameters: %s", ("temperature",), {}),
    ]


def test_strict_drop_policy_rejects_unsupported_parameters(monkeypatch, runtime_target, provider_config):
    import okami.llm.litellm_compat as compat

    monkeypatch.setattr(compat, "supported_params", lambda **kwargs: ["max_tokens"])
    request = CompletionRequest(messages=[], overrides={"temperature": 0.2})
    with pytest.raises(UnsupportedProviderParameter, match="temperature"):
        LiteLLMCompatTransport(drop_policy="error").complete(runtime_target, provider_config, request)


def test_stream_registers_request_local_close_aborter(monkeypatch, runtime_target, provider_config):
    import okami.llm.litellm_compat as compat

    stream = FakeClosableStream()
    monkeypatch.setattr(compat, "completion", lambda **kwargs: stream)
    ctx = RequestContext(RequestTimeouts(total_s=10))
    list(LiteLLMCompatTransport().stream(
        runtime_target, provider_config, CompletionRequest(messages=[], request=ctx),
    ))
    ctx.cancel("user")
    assert stream.closed is True
