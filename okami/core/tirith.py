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

import hashlib
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


# ─────────────────────────────────────────────────── #14: auto-install (opt-in, download + SHA-256)
_REPO = "sheeki03/tirith"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _platform_asset(version: str = "") -> tuple[str, str, str]:
    """(os, arch, nome do asset .tar.gz) p/ a plataforma atual."""
    import platform
    import sys
    if sys.platform == "darwin":
        osn = "darwin"
    elif sys.platform.startswith("win"):
        osn = "windows"
    else:
        osn = "linux"
    mach = platform.machine().lower()
    arch = "arm64" if mach in ("arm64", "aarch64") else "x86_64" if mach in ("x86_64", "amd64") else mach
    return osn, arch, f"tirith_{osn}_{arch}.tar.gz"


def _fetch_url(url: str) -> bytes:
    import urllib.request
    with urllib.request.urlopen(url, timeout=30) as r:  # noqa: S310 — release oficial do GitHub (HTTPS fixo)
        return r.read()


def _extract_tar(data: bytes, dest) -> str | None:
    import io
    import tarfile
    from pathlib import Path
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        for member in tf.getmembers():
            if Path(member.name).name == "tirith" and member.isfile():
                member.name = "tirith"                  # achata: extrai só o binário, sem path do tar
                tf.extract(member, dest)                # noqa: S202 — nome forçado p/ basename (anti path-traversal)
                p = dest / "tirith"
                p.chmod(0o755)
                return str(p)
    return None


def install_tirith(*, version: str, dest, asset_name: str = "", _fetch=_fetch_url, _extract=_extract_tar) -> str | None:
    """Baixa o release `version` do tirith, VERIFICA o SHA-256 contra checksums.txt e extrai p/ `dest`.
    Devolve o caminho do binário, ou None se o checksum não bate / falhou. Nunca levanta a chamada externa."""
    if not asset_name:
        _osn, _arch, asset_name = _platform_asset(version)
    base = f"https://github.com/{_REPO}/releases/download/{version}"
    try:
        checks = _fetch(f"{base}/checksums.txt").decode("utf-8", "replace")
        blob = _fetch(f"{base}/{asset_name}")
    except Exception:  # noqa: BLE001
        return None
    expected = ""
    from pathlib import Path as _P
    for line in checks.splitlines():
        parts = line.split()
        if len(parts) >= 2 and _P(parts[-1]).name == asset_name:   # basename EXATO (não endswith de path)
            expected = parts[0].lower()
            break
    if not expected or _sha256(blob).lower() != expected:   # SHA-256 OBRIGATÓRIO
        logger.warning("tirith: checksum não confere (esperado=%s) — install RECUSADO", expected[:12])
        return None
    try:
        return _extract(blob, dest)
    except Exception:  # noqa: BLE001
        return None


def ensure_tirith_binary(cfg=None, *, version: str = "latest", background: bool = True,
                         _which=shutil.which, _install=None) -> str | None:
    """Se `security.tirith_auto_install` está ON e o binário falta, baixa-o (opt-in, default OFF). Devolve
    o caminho instalado, ou None (desligado / já presente / em background). Best-effort, nunca derruba o boot."""
    sec = {}
    if isinstance(cfg, dict):
        sec = cfg.get("security") or {}
    elif cfg is not None:
        sec = getattr(cfg, "security", None) or {}
    if not _env_bool("TIRITH_AUTO_INSTALL", sec.get("tirith_auto_install", False)):
        return None
    if _which("tirith") or (sec.get("tirith_path") and os.path.exists(sec.get("tirith_path"))):
        return None                                     # já presente
    install = _install or (lambda **k: install_tirith(version=sec.get("tirith_version", "latest"),
                                                       dest=_default_bin_dir(), **k))
    if background:
        import threading
        threading.Thread(target=lambda: install(), daemon=True).start()  # noqa: PLW0108
        return None
    return install()


def _default_bin_dir():
    from okami.home import okami_home
    return okami_home() / "bin"


__all__ = ["scan_command", "install_tirith", "ensure_tirith_binary"]
