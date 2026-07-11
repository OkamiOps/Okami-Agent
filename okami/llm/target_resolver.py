"""The single provider/model-to-runtime-target resolver."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from okami.config import FallbackTargetConfig, OkamiConfig, ProviderConfig
from okami.llm import model_aliases
from okami.llm.runtime import BillingRoute, RuntimeTarget, TargetRef

logger = logging.getLogger(__name__)


class TargetResolutionError(ValueError):
    """A provider/model reference could not be converted into a runtime target."""


_API_MODES = {
    "codex_oauth": "responses",
    "claude_cli": "cli",
    "copilot_cli": "cli",
    "gemini_native": "generate_content",
    "bedrock_native": "converse",
    "gemini_cloudcode": "cloudcode",
    "minimax_oauth": "chat_completions",
    "litellm": "chat_completions",
}


def _credential_ref(pc: ProviderConfig) -> str | None:
    """Return a stable credential identity without reading the credential value."""
    api_key_env = getattr(pc, "api_key_env", None)
    transport = getattr(pc, "transport", "litellm")
    name = getattr(pc, "name", "")
    if api_key_env:
        return f"env:{api_key_env}"
    if getattr(pc, "auth", "api_key") == "oauth_subscription" or transport in {"codex_oauth", "minimax_oauth"}:
        return f"oauth:{name}"
    if getattr(pc, "api_keys", None):
        return f"pool:{name}"
    api_key = getattr(pc, "api_key", None)
    if api_key:
        digest = hashlib.sha256(api_key.encode("utf-8", "replace")).hexdigest()[:16]
        return f"literal-sha256:{digest}"
    return None


def _capabilities(pc: ProviderConfig) -> frozenset[str]:
    values: set[str] = set()
    mode = pc.effective_tool_mode() if hasattr(pc, "effective_tool_mode") else ""
    if mode in {"native", "json_text", "json_constrained"}:
        values.add("tools")
    if getattr(pc, "native_tools", False):
        values.add("native_tools")
    if getattr(getattr(pc, "capability", None), "vision", False):
        values.add("vision")
    return frozenset(values)


def _destination_key(target: RuntimeTarget) -> tuple[str, str, str | None, str, str]:
    return (target.provider, target.model, target.base_url, target.api_mode, target.transport)


class TargetResolver:
    """Resolve aliases and config entries into immutable runtime targets."""

    def resolve(
        self,
        cfg: OkamiConfig,
        *,
        provider: str | None = None,
        model: str | None = None,
        token: str | None = None,
        ref: TargetRef | FallbackTargetConfig | dict[str, Any] | str | None = None,
    ) -> RuntimeTarget:
        target_ref = self._coerce_ref(ref)
        if target_ref is not None:
            provider = target_ref.provider
            model = target_ref.model if target_ref.model is not None else model
        if token is not None:
            try:
                provider, alias_model = model_aliases.resolve(cfg, token)
            except model_aliases.ModelAliasError as exc:
                raise TargetResolutionError(str(exc)) from None
            if model is None:
                model = alias_model
        elif provider is None:
            provider = cfg.default_provider
        elif provider not in cfg.providers and model is None:
            # A provider argument is also allowed to be an existing model alias.
            try:
                provider, model = model_aliases.resolve(cfg, provider)
            except model_aliases.ModelAliasError:
                pass

        if provider not in cfg.providers:
            available = ", ".join(cfg.providers) or "(nenhum)"
            raise TargetResolutionError(
                f"provider desconhecido: '{provider}' — disponíveis: {available}"
            )
        pc = cfg.providers[provider]
        return self._from_provider(
            cfg,
            pc,
            model=model,
            base_url=target_ref.base_url if target_ref else None,
            api_mode=(target_ref.api_mode if target_ref else None),
            credential_ref=(target_ref.credential_ref if target_ref else None),
        )

    def resolve_provider(
        self,
        pc: ProviderConfig,
        *,
        model: str | None = None,
        base_url: str | None = None,
        api_mode: str | None = None,
    ) -> RuntimeTarget:
        """Resolve an already selected config object for compatibility adapters."""
        effective_model = model or getattr(pc, "model", "")
        if model and "/" not in model and "/" in getattr(pc, "model", ""):
            effective_model = f"{pc.model.split('/', 1)[0]}/{model}"
        return self._from_provider(
            None,
            pc,
            model=effective_model,
            base_url=base_url,
            api_mode=api_mode,
        )

    def fallback_targets(self, cfg: OkamiConfig, primary: RuntimeTarget) -> tuple[RuntimeTarget, ...]:
        """Flatten the configured fallback graph once, preserving effective destinations."""
        out: list[RuntimeTarget] = []
        seen = {_destination_key(primary)}

        def visit(provider_name: str, stack: set[str]) -> None:
            if provider_name in stack or provider_name not in cfg.providers:
                return
            pc = cfg.providers[provider_name]
            if pc.experimental or not self._available(pc):
                return
            next_stack = stack | {provider_name}
            for entry in pc.fallback:
                ref = self._coerce_ref(entry)
                if ref is None:
                    continue
                if ref.provider in next_stack:
                    continue
                try:
                    target = self.resolve(cfg, ref=ref)
                except TargetResolutionError:
                    continue
                target_pc = cfg.providers[target.provider]
                if target_pc.experimental or not self._available(target_pc):
                    continue
                key = _destination_key(target)
                if key not in seen:
                    seen.add(key)
                    out.append(target)
                visit(target.provider, next_stack)

        visit(primary.provider, set())
        return tuple(out)

    def _from_provider(
        self,
        cfg: OkamiConfig | None,
        pc: ProviderConfig,
        *,
        model: str | None,
        base_url: str | None,
        api_mode: str | None,
        credential_ref: str | None = None,
    ) -> RuntimeTarget:
        if model is None:
            effective_model = pc.model
        elif "/" in model:
            effective_model = model
        elif cfg is not None:
            effective_model = model_aliases.full_model_string(cfg, pc.name, model)
        elif "/" in getattr(pc, "model", ""):
            effective_model = f"{pc.model.split('/', 1)[0]}/{model}"
        else:
            effective_model = model
        transport = getattr(pc, "transport", "litellm") or "litellm"
        resolved_base = base_url if base_url is not None else getattr(pc, "api_base", None)
        mode = api_mode or _API_MODES.get(transport, "chat_completions")
        route_mode = "included" if getattr(pc, "auth", "api_key") == "oauth_subscription" else "metered"
        billing = BillingRoute(getattr(pc, "name", ""), effective_model, route_mode, resolved_base)
        safe_credential = (
            credential_ref if credential_ref is not None and self._safe_credential_ref(credential_ref)
            else _credential_ref(pc)
        )
        return RuntimeTarget(
            provider=getattr(pc, "name", ""),
            model=effective_model,
            base_url=resolved_base,
            api_mode=mode,
            transport=transport,
            credential_ref=safe_credential,
            capabilities=_capabilities(pc),
            billing_route=billing,
        )

    @staticmethod
    def _safe_credential_ref(value: str | None) -> bool:
        return value is None or value.startswith(("env:", "oauth:", "pool:", "literal-sha256:"))

    @staticmethod
    def _coerce_ref(value: TargetRef | FallbackTargetConfig | dict[str, Any] | str | None) -> TargetRef | None:
        if value is None:
            return None
        if isinstance(value, TargetRef):
            return value
        if isinstance(value, FallbackTargetConfig):
            return TargetRef(value.provider, value.model, value.base_url, value.api_mode)
        if isinstance(value, str):
            return TargetRef(provider=value)
        if isinstance(value, dict):
            return TargetRef(
                provider=str(value.get("provider", "")),
                model=value.get("model"),
                base_url=value.get("base_url", value.get("api_base")),
                api_mode=value.get("api_mode"),
            )
        return None

    @staticmethod
    def _available(pc: ProviderConfig) -> bool:
        # Bare LiteLLM providers intentionally remain eligible: LiteLLM may
        # resolve credentials from its own environment/configuration. Explicit
        # native/OAuth routes, however, should not become fallback black holes.
        if pc.transport in {"codex_oauth", "minimax_oauth", "claude_cli", "copilot_cli"}:
            return pc.ready
        if pc.auth == "oauth_subscription":
            return pc.ready
        if pc.api_key_env and not pc.resolved_key():
            return False
        return True


__all__ = ["TargetResolutionError", "TargetResolver"]
