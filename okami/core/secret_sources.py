"""Fontes de segredo plugáveis (pesquisa #6 item 19, porta do secret_sources do Hermes).

Uma FONTE injeta env-vars no boot DEPOIS do `.env`: NÃO-DESTRUTIVA (só seta o que falta, então
`.env`/exports do shell continuam vencendo) e FAIL-NEVER-BLOCK (qualquer falha → 1 aviso e segue).
Casa com o hard-constraint do Okami "secrets nunca em texto": com Bitwarden Secrets Manager (BSM),
só `BWS_ACCESS_TOKEN` fica no ambiente; TODO o resto vive no cofre e é puxado via `bws`.

Hoje shippa só Bitwarden, mas o contrato (`fetch() -> {NOME: valor}`) é genérico (1Password/Vault/etc.
entram como novas fontes sem tocar no resto).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess


def parse_bws_secrets(raw: str) -> dict[str, str]:
    """`bws secret list -o json` → {key: value}. JSON ruim/forma inesperada → {} (fail-open)."""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    out: dict[str, str] = {}
    for item in data if isinstance(data, list) else []:
        if isinstance(item, dict) and item.get("key"):
            out[str(item["key"])] = str(item.get("value", ""))
    return out


def bitwarden_available() -> bool:
    """BSM utilizável? Precisa do token de bootstrap no ambiente (o único segredo em texto)."""
    return bool(os.environ.get("BWS_ACCESS_TOKEN"))


def _fetch_bitwarden() -> dict[str, str]:
    """Puxa os segredos do cofre via `bws`. Levanta se o binário falta / comando falha (o caller trata)."""
    if not bitwarden_available():
        return {}
    bws = shutil.which("bws")
    if not bws:
        raise RuntimeError("bws (Bitwarden Secrets CLI) não está no PATH")
    r = subprocess.run([bws, "secret", "list", "-o", "json"],  # noqa: S603 — argv fixo, sem shell
                       capture_output=True, text=True, timeout=20)
    if r.returncode != 0:
        raise RuntimeError(f"bws falhou (exit {r.returncode}): {r.stderr.strip()[:200]}")
    return parse_bws_secrets(r.stdout)


def apply_secrets(*, fetch=None, override: bool = False) -> dict:
    """Aplica a fonte de segredo ao ambiente. NÃO-DESTRUTIVO por padrão (só seta o que falta; `.env`
    e exports do shell vencem). `override=True` força o cofre a ganhar. FAIL-NEVER-BLOCK: erro do
    fetch → {'applied': 0, 'error': ...}, nunca exceção. Retorna {applied, skipped, error}."""
    fetch = fetch or _fetch_bitwarden
    try:
        secrets = fetch() or {}
    except Exception as e:  # noqa: BLE001 — fonte indisponível NUNCA bloqueia o boot
        return {"applied": 0, "skipped": 0, "error": str(e)}
    applied = skipped = 0
    for key, val in secrets.items():
        if not key or val == "":
            continue
        if not override and os.environ.get(key):
            skipped += 1                             # .env/shell já tem → não sobrescreve
            continue
        os.environ[key] = val
        applied += 1
    return {"applied": applied, "skipped": skipped, "error": ""}


def apply_configured_sources(cfg=None) -> dict:
    """Aplica as fontes habilitadas (hoje: Bitwarden se BWS_ACCESS_TOKEN presente). Best-effort —
    chamado no boot. Devolve o resultado agregado p/ log."""
    if bitwarden_available():
        return apply_secrets()
    return {"applied": 0, "skipped": 0, "error": ""}
