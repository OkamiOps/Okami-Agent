"""Immutable values carried by the provider pipeline.

These values deliberately contain credential *identities* only.  A runtime target
is safe to put in retry state, diagnostics and structured fallback metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib


def _credential_identity(value: str | None) -> str | None:
    if value is None or value.startswith(("env:", "oauth:", "pool:", "literal-sha256:")):
        return value
    digest = hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:16]
    return f"literal-sha256:{digest}"


@dataclass(frozen=True, slots=True)
class BillingRoute:
    provider: str
    model: str
    mode: str
    base_url: str | None = None


@dataclass(frozen=True, slots=True)
class TargetRef:
    provider: str
    model: str | None = None
    base_url: str | None = None
    api_mode: str | None = None
    credential_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "credential_ref", _credential_identity(self.credential_ref))


@dataclass(frozen=True, slots=True)
class RuntimeTarget:
    provider: str
    model: str
    base_url: str | None
    api_mode: str
    transport: str
    credential_ref: str | None
    capabilities: frozenset[str]
    billing_route: BillingRoute

    def __post_init__(self) -> None:
        # A caller may provide a normal set for convenience; keep the stored
        # value immutable and hashable regardless.
        if not isinstance(self.capabilities, frozenset):
            object.__setattr__(self, "capabilities", frozenset(self.capabilities))
        object.__setattr__(self, "credential_ref", _credential_identity(self.credential_ref))


__all__ = ["BillingRoute", "RuntimeTarget", "TargetRef"]
