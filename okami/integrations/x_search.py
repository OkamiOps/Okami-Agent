"""Busca no X/Twitter via xAI Grok (#19, paridade Hermes tools/x_search_tool.py).

Config-driven (`integrations.x.{api_key_env, model, base_url}`); sem chave → erro claro. Usa o live-search
do Grok (chat/completions com search ligado). A rede é injetável (`_post`) p/ teste offline.
"""
from __future__ import annotations

import json
import os
import urllib.request

DEFAULT_BASE_URL = "https://api.x.ai/v1"
DEFAULT_MODEL = "grok-4"


def x_config(cfg) -> dict | None:
    ig = (getattr(cfg, "integrations", None) or {}) if not isinstance(cfg, dict) else (cfg.get("integrations") or {})
    x = ig.get("x") or {}
    if not x.get("api_key_env"):
        return None
    return {"api_key_env": x["api_key_env"], "model": x.get("model") or DEFAULT_MODEL,
            "base_url": (x.get("base_url") or DEFAULT_BASE_URL).rstrip("/")}


def _default_post(url, body, headers):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)  # noqa: S310 — endpoint xAI do config
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
        return json.loads(r.read().decode("utf-8"))


def x_search(cfg, query: str, *, handles: list | None = None, _post=None) -> dict:
    """Pergunta ao Grok com live-search no X. Devolve {answer, citations}. Sem chave → RuntimeError."""
    xc = x_config(cfg)
    if xc is None:
        raise RuntimeError("X search não configurado — configure integrations.x.{api_key_env, model}.")
    key = os.environ.get(xc["api_key_env"], "")
    if not key:
        raise RuntimeError(f"sem a chave xAI: defina {xc['api_key_env']} no .env.")
    sources: dict = {"type": "x"}
    if handles:
        sources["x_handles"] = list(handles)
    body = {"model": xc["model"], "messages": [{"role": "user", "content": query}],
            "search_parameters": {"mode": "on", "sources": [sources]}}
    post = _post or _default_post
    resp = post(f"{xc['base_url']}/chat/completions", body,
                {"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    msg = (((resp.get("choices") or [{}])[0]).get("message") or {})
    citations = msg.get("citations") or resp.get("citations") or []
    return {"answer": msg.get("content") or "", "citations": list(citations)}


__all__ = ["x_config", "x_search"]
