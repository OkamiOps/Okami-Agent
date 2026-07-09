"""Registry ÚNICO de fluxos de auth OAuth (paridade Hermes) — o login, o menu de autenticar e os
transports consultam SÓ aqui, pra não espalhar o dispatch por provider.

Cada fluxo é (login_fn, token_fn):
  login_fn(emit) -> dict|None   — roda o fluxo interativo (device/paste-code), grava os tokens. None = pulou.
  token_fn(now=time.time) -> str|None  — devolve um access token VÁLIDO (com refresh), ou None.

Um provider declara `auth_flow: <nome>` no okami.yaml/preset. Sem auth_flow, os caminhos antigos
(codex_oauth transport / login_cmd / oauth device genérico / api_key_env) seguem valendo.
"""
from __future__ import annotations

from typing import Callable

# nome do fluxo → (módulo, login_fn, token_fn). Import lazy: um módulo quebrado não derruba o resto.
_FLOWS: dict[str, tuple[str, str, str]] = {
    "anthropic_pkce": ("okami.llm.oauth_anthropic", "anthropic_login", "anthropic_access_token"),
    "minimax_oauth":  ("okami.llm.oauth_minimax",   "minimax_oauth_login", "minimax_access_token"),
    "xai_oauth":      ("okami.llm.oauth_xai",       "xai_login", "xai_access_token"),
    "nous_device":    ("okami.llm.oauth_nous",      "nous_login", "nous_access_token"),
    "qwen_cli":       ("okami.llm.oauth_qwen",      None, "qwen_access_token"),   # Qwen: sem login próprio
    "copilot_device": ("okami.llm.oauth_copilot",   "copilot_login", "copilot_access_token"),
}


def known_flows() -> list[str]:
    return list(_FLOWS)


def _resolve(flow: str, which: int) -> Callable | None:
    spec = _FLOWS.get(flow)
    if not spec:
        return None
    mod_name, fn_name = spec[0], spec[which]
    if not fn_name:
        return None
    try:
        import importlib
        return getattr(importlib.import_module(mod_name), fn_name, None)
    except Exception:  # noqa: BLE001 — módulo indisponível → fluxo simplesmente não existe
        return None


def has_flow(flow: str) -> bool:
    return flow in _FLOWS


def run_login(flow: str, emit: Callable[[str], None]):
    """Roda o login interativo do fluxo. Levanta se o fluxo não tem login próprio (ex.: qwen_cli:
    o usuário loga pelo CLI do Qwen e a gente só lê/refresca o arquivo dele)."""
    fn = _resolve(flow, 1)
    if fn is None:
        if flow == "qwen_cli":
            emit("Qwen não tem login próprio aqui — rode o CLI do Qwen (`qwen`) pra autenticar; "
                 "o Okami lê e renova `~/.qwen/oauth_creds.json` sozinho depois.")
            return None
        raise ValueError(f"fluxo de auth desconhecido: {flow}")
    return fn(emit)


def token_for(flow: str) -> str | None:
    """Access token válido do fluxo (com refresh), ou None se não autenticado / indisponível."""
    fn = _resolve(flow, 2)
    if fn is None:
        return None
    try:
        return fn()
    except Exception:  # noqa: BLE001 — sem token / erro de rede → None (caller decide o fallback)
        return None


def is_logged_in(flow: str) -> bool:
    return bool(token_for(flow))
