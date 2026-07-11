"""Explicit LiteLLM compatibility adapter.

No provider import changes LiteLLM globals.  The adapter applies compatibility
policy to each request and then calls LiteLLM through this module only.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

from okami.llm.usage import Completion, normalize_usage

logger = logging.getLogger(__name__)

# Public for old tests/integrations that monkeypatch the dependency.  It is an
# alias only; this module never writes process-global policy on it.
litellm = importlib.import_module("litellm")


class UnsupportedProviderParameter(ValueError):
    """A strict request contained parameters unsupported by the selected model."""


def _lite_module():
    # Resolving lazily also keeps test doubles and optional dependency loading
    # compatible with the pre-registry code.
    return importlib.import_module("litellm")


def completion(**kwargs):
    return _lite_module().completion(**kwargs)


def supported_params(**kwargs):
    function = getattr(_lite_module(), "get_supported_openai_params", None)
    if function is None:
        return None
    return function(**kwargs)


_TRANSPORT_KEYS = {
    "model", "messages", "stream", "api_key", "api_base", "timeout",
    "response_format", "tools", "tool_choice", "extra_body",
}


def _provider_kwargs(provider_config, target, request, *, stream: bool) -> dict[str, Any]:
    from okami.llm import providers

    overrides = dict(request.overrides)
    overrides.pop("_drop_policy", None)
    return providers._kwargs(
        provider_config,
        request.messages,
        stream=stream,
        model=target.model,
        **overrides,
    )


def _unsupported(kw: dict[str, Any], provider_config, target, request) -> list[str]:
    candidates = set(getattr(provider_config, "params", {}) or {})
    candidates.update(request.overrides)
    candidates.difference_update({"_api_key", "request", "drop_policy"})
    candidates &= set(kw)
    if not candidates:
        return []
    try:
        supported = supported_params(
            model=target.model,
            api_base=getattr(provider_config, "api_base", None),
        )
    except Exception:  # provider metadata is best-effort; preserve effective behavior
        return []
    if not supported:
        return []
    return sorted(key for key in candidates if key not in set(supported))


def _apply_drop_policy(kw: dict[str, Any], provider_config, target, request, policy: str) -> None:
    unsupported = _unsupported(kw, provider_config, target, request)
    if not unsupported:
        return
    names = ", ".join(unsupported)
    if policy == "error":
        raise UnsupportedProviderParameter(f"unsupported provider parameters: {names}")
    if policy != "warn":
        raise ValueError("drop_policy must be 'warn' or 'error'")
    logger.warning("LiteLLM compatibility dropped unsupported parameters: %s", names)
    for name in unsupported:
        kw.pop(name, None)


def _message_text(message) -> str:
    from okami.llm.providers import _message_text as provider_message_text

    return provider_message_text(message)


def _tool_calls(message) -> list:
    from okami.llm.providers import _extract_tool_calls

    return _extract_tool_calls(message)


class LiteLLMCompatTransport:
    def __init__(self, *, drop_policy: str = "warn") -> None:
        if drop_policy not in {"warn", "error"}:
            raise ValueError("drop_policy must be 'warn' or 'error'")
        self.drop_policy = drop_policy

    def _policy(self, request: Any) -> str:
        return str(request.overrides.get("_drop_policy", self.drop_policy))

    def complete(self, target, provider_config, request):
        kw = _provider_kwargs(provider_config, target, request, stream=False)
        _apply_drop_policy(kw, provider_config, target, request, self._policy(request))
        response = completion(**kw)
        choice = response.choices[0]
        message = choice.message
        return Completion(
            text=_message_text(message),
            tool_calls=_tool_calls(message),
            finish_reason=getattr(choice, "finish_reason", "") or "stop",
            usage=normalize_usage(getattr(response, "usage", None), transport="litellm"),
            provider=target.provider,
            model=target.model,
        )

    def stream(self, target, provider_config, request):
        kw = _provider_kwargs(provider_config, target, request, stream=True)
        _apply_drop_policy(kw, provider_config, target, request, self._policy(request))
        source = completion(**kw)
        close = getattr(source, "close", None)
        if request.request is not None and callable(close):
            request.request.register_abort(lambda reason: close())
        yield from source


__all__ = [
    "LiteLLMCompatTransport", "UnsupportedProviderParameter", "completion",
    "litellm", "supported_params",
]
