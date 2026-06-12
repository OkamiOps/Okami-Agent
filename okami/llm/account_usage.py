"""Janelas de uso de ASSINATURA (pesquisa #6 item 14, porta do account_usage do Hermes).

Responde "quanto sobrou do meu plano" — direto relevante porque o Okami é subscription-only. Bate no
endpoint de usage da assinatura e modela janelas (used_percent + resets_at):
- Codex/ChatGPT: …/wham/usage → rate_limit.primary_window (sessão) / secondary_window (semana).
- Anthropic: api/oauth/usage (só p/ conta OAuth-backed; com claude_cli não há token cru → indisponível).

FAIL-OPEN por princípio: sem token, sem rede, erro de parse → lista vazia. NUNCA quebra o /usage.
"""
from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass

_CODEX_BASE = "https://chatgpt.com/backend-api/codex"


@dataclass
class UsageWindow:
    label: str
    used_percent: float
    resets_at: float | str | None = None     # epoch secs (até o reset OU absoluto) ou ISO; tolerante


def _http_get_json(url: str, headers: dict, timeout: float = 12.0) -> dict:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — endpoint de provider conhecido
        return json.loads(r.read().decode("utf-8", "ignore")) or {}


def _codex_usage_url(base_url: str) -> str:
    """Resolve a URL de usage a partir do base (igual ao Hermes _resolve_codex_usage_url)."""
    n = (base_url or "").strip().rstrip("/") or _CODEX_BASE
    if n.endswith("/codex"):
        n = n[: -len("/codex")]
    return n + ("/wham/usage" if "/backend-api" in n else "/api/codex/usage")


def fetch_codex_usage(*, token=None, account_id=None, base_url: str = "", http=None) -> list[UsageWindow]:
    """Janelas do plano ChatGPT/Codex. Token resolvido do store se não passado. http injetável."""
    if token is None:
        from okami.llm.oauth import codex_access_token
        token = codex_access_token()
    if not token:
        return []
    if account_id is None:
        from okami.llm.oauth import codex_account_id
        account_id = codex_account_id()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json", "User-Agent": "codex-cli"}
    if account_id:
        headers["ChatGPT-Account-Id"] = account_id
    try:
        payload = (http or _http_get_json)(_codex_usage_url(base_url), headers)
    except Exception:  # noqa: BLE001 — fail-open
        return []
    rate = (payload or {}).get("rate_limit") or {}
    out: list[UsageWindow] = []
    for key, label in (("primary_window", "Sessão"), ("secondary_window", "Semana")):
        w = rate.get(key) or {}
        used = w.get("used_percent")
        if used is None:
            continue
        try:
            out.append(UsageWindow(label, float(used), w.get("reset_at")))
        except (TypeError, ValueError):
            continue
    return out


def fetch_anthropic_usage(*, token=None, http=None) -> list[UsageWindow]:
    """Janelas do plano Anthropic (só conta OAuth-backed). Com claude_cli o Okami não tem token cru →
    devolve vazio (o CLI cuida da auth). Mantido p/ quando houver login OAuth Claude."""
    if not token:
        return []
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json",
               "anthropic-beta": "oauth-2025-04-20", "User-Agent": "okami"}
    try:
        payload = (http or _http_get_json)("https://api.anthropic.com/api/oauth/usage", headers)
    except Exception:  # noqa: BLE001 — fail-open
        return []
    out: list[UsageWindow] = []
    for key, label in (("five_hour", "Sessão (5h)"), ("seven_day", "Semana"),
                       ("seven_day_opus", "Opus (semana)"), ("seven_day_sonnet", "Sonnet (semana)")):
        w = (payload or {}).get(key) or {}
        util = w.get("utilization")
        if util is None:
            continue
        try:
            pct = float(util) * 100 if float(util) <= 1 else float(util)
            out.append(UsageWindow(label, pct, w.get("resets_at")))
        except (TypeError, ValueError):
            continue
    return out


def account_usage(cfg, *, http=None) -> list[UsageWindow]:
    """Agrega as janelas de todos os provedores de assinatura disponíveis. Fail-open por provedor."""
    out: list[UsageWindow] = []
    for fetch in (lambda: fetch_codex_usage(http=http),):
        try:
            out += fetch()
        except Exception:  # noqa: BLE001
            continue
    return out


def _reset_in(resets_at, now: float) -> str:
    """'reseta em ~2h10' a partir de epoch (absoluto ou relativo) / ISO. '' se indeterminável."""
    if resets_at is None:
        return ""
    secs = None
    if isinstance(resets_at, (int, float)):
        secs = float(resets_at) - now if resets_at > now + 1 else float(resets_at)  # absoluto vs relativo
    else:
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(str(resets_at).replace("Z", "+00:00"))
            secs = dt.timestamp() - now
        except (ValueError, TypeError):
            return ""
    if secs is None or secs <= 0:
        return "agora"
    h, m = int(secs // 3600), int((secs % 3600) // 60)
    return f"reseta em {h}h{m:02d}" if h else f"reseta em {m}min"


def render_usage_lines(windows: list[UsageWindow], *, now=time.time) -> list[str]:
    """Linhas humanas: 'Sessão (5h): 58% restante (42% usado) · reseta em 2h10'. ⚠ quando ≥80% usado."""
    _now = now()
    lines = []
    for w in windows:
        used = max(0.0, min(100.0, w.used_percent))
        left = 100 - used
        warn = "⚠ " if used >= 80 else ""
        reset = _reset_in(w.resets_at, _now)
        tail = f" · {reset}" if reset else ""
        lines.append(f"{warn}{w.label}: {left:.0f}% restante ({used:.0f}% usado){tail}")
    return lines
