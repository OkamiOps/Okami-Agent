"""Feishu/Lark — leitura de documento via API (#19, paridade Hermes tools/feishu_doc_tool.py).

Config-driven (`integrations.feishu.{app_id, app_secret_env, base_url}`). Pega um tenant_access_token e lê
o raw_content do doc. Sem segredo → erro claro. Rede injetável (`_post`/`_get`) p/ teste offline.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

DEFAULT_BASE_URL = "https://open.feishu.cn"
_DOC_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+$")          # token de doc: só alfanum/_/- (anti path-injection)


def feishu_config(cfg) -> dict | None:
    ig = (getattr(cfg, "integrations", None) or {}) if not isinstance(cfg, dict) else (cfg.get("integrations") or {})
    f = ig.get("feishu") or {}
    if not f.get("app_id") or not f.get("app_secret_env"):
        return None
    return {"app_id": f["app_id"], "app_secret_env": f["app_secret_env"],
            "base_url": (f.get("base_url") or DEFAULT_BASE_URL).rstrip("/")}


def _default_post(url, body, headers):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)  # noqa: S310 — endpoint Feishu
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
        raw = r.read().decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:                  # resposta não-JSON do Feishu não derruba a tool
        raise RuntimeError(f"resposta não-JSON do Feishu: {raw[:160]}") from e


def _default_get(url, headers):
    req = urllib.request.Request(url, method="GET", headers=headers)  # noqa: S310
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
        raw = r.read().decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:                  # resposta não-JSON do Feishu não derruba a tool
        raise RuntimeError(f"resposta não-JSON do Feishu: {raw[:160]}") from e


def _tenant_token(cfg, *, _post) -> tuple[str, str]:
    fc = feishu_config(cfg)
    if fc is None:
        raise RuntimeError("Feishu não configurado — configure integrations.feishu.{app_id, app_secret_env}.")
    secret = os.environ.get(fc["app_secret_env"], "")
    if not secret:
        raise RuntimeError(f"sem o segredo do Feishu: defina {fc['app_secret_env']} no .env.")
    resp = _post(f"{fc['base_url']}/open-apis/auth/v3/tenant_access_token/internal",
                 {"app_id": fc["app_id"], "app_secret": secret}, {"Content-Type": "application/json"})
    tok = resp.get("tenant_access_token", "")
    if not tok:
        raise RuntimeError(f"Feishu não devolveu tenant_access_token: {str(resp)[:160]}")
    return fc["base_url"], tok


def read_doc(cfg, doc_token: str, *, _post=None, _get=None) -> str:
    """Lê o conteúdo (raw_content) de um documento Feishu como texto. Sem config/segredo → RuntimeError."""
    if not _DOC_TOKEN_RE.match(doc_token or ""):          # doc_token vai cru na URL → valida (anti-traversal)
        raise ValueError(f"doc_token inválido: {doc_token!r} (só letras/números/_/-).")
    post = _post or _default_post
    get = _get or _default_get
    base, tok = _tenant_token(cfg, _post=post)
    headers = {"Authorization": f"Bearer {tok}"}
    resp = get(f"{base}/open-apis/docx/v1/documents/{doc_token}/raw_content", headers)
    return ((resp.get("data") or {}).get("content")) or resp.get("content") or ""


__all__ = ["feishu_config", "read_doc"]
