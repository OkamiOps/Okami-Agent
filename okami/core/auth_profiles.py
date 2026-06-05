"""Perfis de AUTH com metadata (#12 — auth profiles, estilo OpenClaw).

Visão estruturada de COMO cada provider autentica — sem NUNCA expor o segredo. Mostra tipo
(oauth/cli/api_key), ONDE mora a credencial (caminho do auth.json, nome da env var — não o valor),
status (ready/missing/expired), e se é ASSINATURA (codex/claude/minimax — a restrição dura: nunca
pay-as-you-go). Powering `okami auth list` / `okami auth status --json`.

INVARIANTE: o dict de perfil só carrega METADADO. Nada de chave/token. (Teste garante.)
"""

from __future__ import annotations

import json
import time
from pathlib import Path

_SUBSCRIPTION_TRANSPORTS = ("codex_oauth", "claude_cli", "minimax_oauth")


def _kind(pc) -> str:
    t = getattr(pc, "transport", "")
    if t == "claude_cli":
        return "cli"                                     # CLI oficial 'claude' (antes do catch de oauth)
    if t in ("codex_oauth", "minimax_oauth") or getattr(pc, "auth", "") == "oauth_subscription":
        return "oauth"
    if getattr(pc, "api_key_env", None) or getattr(pc, "api_key", None):
        return "api_key"
    return "none"


def _is_subscription(pc) -> bool:
    return getattr(pc, "transport", "") in _SUBSCRIPTION_TRANSPORTS \
        or getattr(pc, "auth", "") == "oauth_subscription"


def _location(pc) -> str:
    """ONDE mora a credencial — caminho ou NOME da env var, jamais o valor."""
    t = getattr(pc, "transport", "")
    if t == "codex_oauth":
        for p in (Path.home() / ".codex" / "auth.json", Path.home() / ".okami" / "credentials" / "codex.json"):
            if p.exists():
                return str(p)
        return "~/.codex/auth.json"
    if t == "claude_cli":
        return "CLI oficial 'claude' (~/.claude)"
    if t == "minimax_oauth":
        p = Path.home() / ".okami" / "credentials" / "minimax.json"
        return str(p) if p.exists() else "~/.okami/credentials/minimax.json"
    if getattr(pc, "api_key_env", None):
        return f"env:{pc.api_key_env}"                    # NOME da var, não o valor
    if getattr(pc, "api_key", None):
        return "literal/dummy (okami.yaml)"
    return "—"


def _oauth_expiry(pc):
    """Timestamp de expiração do token OAuth (best-effort, SÓ o número — nunca o token). None se n/d."""
    if getattr(pc, "transport", "") != "codex_oauth":
        return None
    for p in (Path.home() / ".codex" / "auth.json", Path.home() / ".okami" / "credentials" / "codex.json"):
        if not p.exists():
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None
        for scope in (d, d.get("tokens", {}) if isinstance(d, dict) else {}):
            if isinstance(scope, dict):
                for key in ("expires_at", "expiry", "expire", "exp"):
                    v = scope.get(key)
                    if isinstance(v, (int, float)):
                        return v
    return None


def build_auth_profiles(cfg, *, now: float | None = None) -> list[dict]:
    """Lista de perfis de auth (metadata) p/ cada provider. `cfg.default_provider` marca o default."""
    now = now if now is not None else time.time()
    default = getattr(cfg, "default_provider", None)
    out = []
    for name, pc in (getattr(cfg, "providers", None) or {}).items():
        ready = bool(getattr(pc, "ready", False))
        expires = _oauth_expiry(pc)
        if ready and isinstance(expires, (int, float)) and expires < now:
            status = "expired"
        elif ready:
            status = "ready"
        else:
            status = "missing"
        out.append({
            "name": name,
            "default": name == default,
            "kind": _kind(pc),
            "transport": getattr(pc, "transport", ""),
            "tier": getattr(pc, "tier", "unknown"),
            "model": getattr(pc, "model", ""),
            "subscription": _is_subscription(pc),
            "location": _location(pc),
            "status": status,
            "expires_at": expires,
            "checked_at": round(now, 3),
        })
    return out
