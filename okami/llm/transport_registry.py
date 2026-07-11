"""Named transport boundary for provider completion and streaming."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Protocol

from okami.llm.request import RequestContext
from okami.llm.runtime import RuntimeTarget


@dataclass(slots=True)
class CompletionRequest:
    messages: list[dict]
    response_schema: dict | None = None
    overrides: dict[str, Any] = field(default_factory=dict)
    raw_messages: list[dict] | None = None
    request: RequestContext | None = None


class LLMTransport(Protocol):
    def complete(self, target: RuntimeTarget, provider_config, request: CompletionRequest): ...

    def stream(self, target: RuntimeTarget, provider_config, request: CompletionRequest): ...


class UnknownTransportError(ValueError):
    """The runtime target names a transport not present in the registry."""


class TransportRegistry:
    def __init__(self) -> None:
        self._transports: dict[str, LLMTransport] = {}

    def register(self, name: str, transport: LLMTransport) -> None:
        key = str(name).strip()
        if not key:
            raise ValueError("transport name cannot be empty")
        self._transports[key] = transport

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._transports))

    def _get(self, name: str) -> LLMTransport:
        try:
            return self._transports[name]
        except KeyError:
            names = ", ".join(self.names()) or "(nenhum)"
            raise UnknownTransportError(
                f"transport desconhecido: '{name}' — registrados: {names}"
            ) from None

    def complete(self, target: RuntimeTarget, provider_config, request: CompletionRequest):
        return self._get(target.transport).complete(target, provider_config, request)

    def stream(self, target: RuntimeTarget, provider_config, request: CompletionRequest):
        return self._get(target.transport).stream(target, provider_config, request)


class _LegacyTransport:
    """Small adapter retaining the already-tested native transport functions."""

    def __init__(self, function_name: str) -> None:
        self.function_name = function_name

    def _function(self):
        from okami.llm import transports

        return getattr(transports, self.function_name)

    def complete(self, target, provider_config, request):
        fn = self._function()
        overrides = dict(request.overrides)
        kwargs = {}
        if request.raw_messages is not None and _accepts_keyword(fn, "raw_messages"):
            kwargs["raw_messages"] = request.raw_messages
        return fn(provider_config, request.messages, target.model, overrides, **kwargs)

    def stream(self, target, provider_config, request):
        result = self.complete(target, provider_config, request)
        yield result


def _accepts_keyword(fn, name: str) -> bool:
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(p.name == name or p.kind is inspect.Parameter.VAR_KEYWORD for p in params)


def default_transport_registry() -> TransportRegistry:
    from okami.llm.litellm_compat import LiteLLMCompatTransport

    registry = TransportRegistry()
    registry.register("litellm", LiteLLMCompatTransport())
    for name in (
        "claude_cli", "codex_oauth", "minimax_oauth", "gemini_native",
        "bedrock_native", "gemini_cloudcode", "copilot_cli",
    ):
        registry.register(name, _LegacyTransport(f"{name}_complete"))
    return registry


__all__ = [
    "CompletionRequest", "LLMTransport", "TransportRegistry", "UnknownTransportError",
    "default_transport_registry",
]
