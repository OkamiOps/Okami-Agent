"""Tirith pre-exec security scanner (#12, port do Hermes tools/tirith_security.py — SEM auto-install).

Roda o binário `tirith` (sheeki03/tirith) como subprocesso p/ escanear o comando por ameaça a NÍVEL DE
CONTEÚDO que o regex do approval não pega: URL homograph (g00gle.com), pipe-to-interpreter avançado,
injeção de controle de terminal. Exit code é a verdade: 0=allow, 1=block, 2=warn. JSON no stdout
enriquece findings mas não sobrescreve o veredito. Spawn/timeout respeitam fail_open.

DIFERENÇA do Hermes: NÃO auto-baixa o binário (download de release + cosign é pesado/arriscado p/ fazer
às cegas). Se o binário não está no PATH (ou no `security.tirith_path`), é GRACEFUL: verdict=allow,
available=False — o approval por regex do Okami segue valendo. O dono instala o tirith quando quiser.
Habilitado por default mas inerte sem o binário.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess

logger = logging.getLogger(__name__)


def _env_bool(key: str, default: bool) -> bool:
    v = os.getenv(key)
    if v is None:
        return default
    return v.lower() in {"1", "true", "yes", "on"}


def _config(cfg) -> dict:
    sec = {}
    if isinstance(cfg, dict):
        sec = cfg.get("security") or {}
    elif cfg is not None:
        sec = getattr(cfg, "security", None) or {}
    return {
        "enabled": _env_bool("TIRITH_ENABLED", sec.get("tirith_enabled", True)),
        "path": os.getenv("TIRITH_PATH") or sec.get("tirith_path") or "",
        "timeout": int(sec.get("tirith_timeout", 10)),
        "fail_open": _env_bool("TIRITH_FAIL_OPEN", sec.get("tirith_fail_open", True)),
    }


def scan_command(command: str, *, cfg=None, _run=subprocess.run, _which=shutil.which) -> dict:
    """Escaneia `command`. Devolve {verdict: allow|block|warn, available: bool, findings: list, exit?: int}.
    available=False = scan não rodou (desligado/binário ausente) → o caller NÃO bloqueia por isto."""
    c = _config(cfg)
    if not c["enabled"]:
        return {"verdict": "allow", "available": False, "findings": [], "reason": "disabled"}
    binpath = c["path"] or _which("tirith")
    if not binpath:
        return {"verdict": "allow", "available": False, "findings": [], "reason": "binário não instalado"}
    fail = "allow" if c["fail_open"] else "block"
    try:
        r = _run([binpath, "check", "--json", "--non-interactive", "--shell", "posix", "--", command],
                 capture_output=True, text=True, timeout=c["timeout"], stdin=subprocess.DEVNULL)  # noqa: S603
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.debug("tirith falhou ao rodar (%s) → fail_%s", e, "open" if c["fail_open"] else "closed")
        return {"verdict": fail, "available": True, "findings": [], "error": str(e)}
    findings = []
    try:
        out = json.loads(r.stdout or "{}")
        findings = out.get("findings") or []
    except (json.JSONDecodeError, AttributeError):
        pass
    verdict = {0: "allow", 1: "block", 2: "warn"}.get(r.returncode, fail)   # exit desconhecido → fail_open
    return {"verdict": verdict, "available": True, "findings": findings, "exit": r.returncode}


__all__ = ["scan_command"]
