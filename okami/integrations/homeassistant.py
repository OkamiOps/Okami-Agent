"""Home Assistant via REST API (#19, paridade Hermes tools/homeassistant_tool.py).

Config-driven (`integrations.homeassistant.{url, token_env}`). Lista entidades, lê estado e chama serviços
(turn_on/off, set_temperature…). SEGURANÇA: domínios que rodam código arbitrário (shell_command,
python_script…) são BLOQUEADOS — o HA não tem ACL por serviço, a segurança mora aqui. entity_id/domain
validados por regex (anti path-traversal no /api/services/{domain}/{service}). Rede injetável p/ teste.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

_ENTITY_RE = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")
_NAME_RE = re.compile(r"^[a-z0-9_]+$")
_BLOCKED_DOMAINS = frozenset({"shell_command", "python_script", "hassio", "command_line"})


def ha_config(cfg) -> dict | None:
    ig = (getattr(cfg, "integrations", None) or {}) if not isinstance(cfg, dict) else (cfg.get("integrations") or {})
    ha = ig.get("homeassistant") or {}
    if not ha.get("url"):
        return None
    return {"url": ha["url"].rstrip("/"), "token_env": ha.get("token_env", "")}


def _auth(cfg) -> tuple[dict, dict]:
    hc = ha_config(cfg)
    if hc is None:
        raise RuntimeError("Home Assistant não configurado — configure integrations.homeassistant.{url, token_env}.")
    token = os.environ.get(hc["token_env"], "") if hc["token_env"] else ""
    if hc["token_env"] and not token:
        raise RuntimeError(f"sem o token do Home Assistant: defina {hc['token_env']} no .env.")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return hc, headers


def _default_get(url, headers):
    req = urllib.request.Request(url, method="GET", headers=headers)  # noqa: S310 — URL do HA do dono
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
        raw = r.read().decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:                  # 200 com corpo truncado/HTML não derruba a tool
        raise RuntimeError(f"resposta não-JSON do Home Assistant: {raw[:160]}") from e


def _default_post(url, body, headers):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)  # noqa: S310
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
        raw = r.read().decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:                  # 200 com corpo truncado/HTML não derruba a tool
        raise RuntimeError(f"resposta não-JSON do Home Assistant: {raw[:160]}") from e


def list_entities(cfg, *, domain: str | None = None, _get=None) -> list:
    hc, headers = _auth(cfg)
    get = _get or _default_get
    states = get(f"{hc['url']}/api/states", headers) or []
    if domain:
        states = [s for s in states if str(s.get("entity_id", "")).startswith(f"{domain}.")]
    return states


def get_state(cfg, entity_id: str, *, _get=None) -> dict:
    if not _ENTITY_RE.match(entity_id or ""):
        raise ValueError(f"entity_id inválido: {entity_id!r} (esperado dominio.objeto, ex.: light.sala).")
    hc, headers = _auth(cfg)
    get = _get or _default_get
    return get(f"{hc['url']}/api/states/{entity_id}", headers)


def call_service(cfg, domain: str, service: str, data: dict | None = None, *, _post=None):
    if not _NAME_RE.match(domain or "") or not _NAME_RE.match(service or ""):
        raise ValueError(f"domain/service inválido: {domain!r}/{service!r}.")
    if domain in _BLOCKED_DOMAINS:
        raise ValueError(f"domínio {domain!r} bloqueado (executa código arbitrário) — recusado por segurança.")
    hc, headers = _auth(cfg)
    post = _post or _default_post
    return post(f"{hc['url']}/api/services/{domain}/{service}", data or {}, headers)


__all__ = ["ha_config", "list_entities", "get_state", "call_service"]
