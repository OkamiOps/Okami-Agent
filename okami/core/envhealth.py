"""Auto-diagnóstico de AMBIENTE — pra o agente se virar sozinho numa VPS: descobrir o que está quebrado/
faltando (binário, pip, venv não-gravável, feature lazy indisponível) e então CONSERTAR (run_shell apt
install, lazy_deps, restart_gateway). Sem isso, problema de ambiente vira falha silenciosa e downtime.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys

# binários que o agente USA; ausência de alguns é crítica (git), de outros só limita um recurso.
_BINARIES = ("git", "ssh", "ssh-keygen", "rg", "ffmpeg", "node", "docker", "tailscale", "uv")
_CRITICAL_BINS = ("git",)


def binaries_status() -> dict:
    """{nome: bool presente} (which/where, .exe no Windows tratado por shutil.which)."""
    return {b: bool(shutil.which(b)) for b in _BINARIES}


def python_status() -> dict:
    """Saúde do interpretador/venv: pip presente? site-packages gravável (lazy-install precisa)? é venv?"""
    pip = importlib.util.find_spec("pip") is not None
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    writable = False
    try:
        import sysconfig
        sp = sysconfig.get_paths().get("purelib")
        writable = bool(sp) and os.access(sp, os.W_OK)
    except Exception:  # noqa: BLE001
        pass
    return {"executable": sys.executable, "pip": pip, "in_venv": in_venv, "site_writable": writable,
            "version": sys.version.split()[0]}


def report(workspace: str = ".") -> dict:
    """Diagnóstico consolidado + issues ACIONÁVEIS (com a sugestão de conserto). Nunca levanta."""
    py = python_status()
    bins = binaries_status()
    issues: list[str] = []
    if not py["pip"] and not shutil.which("uv"):
        issues.append("pip e uv ausentes — auto-install (lazy_deps) não vai funcionar; instale python3-pip")
    if py["in_venv"] and not py["site_writable"]:
        issues.append("site-packages do venv não é gravável — lazy-install vai falhar (permissão)")
    for b in _CRITICAL_BINS:
        if not bins.get(b):
            mgr = "apt install" if sys.platform.startswith("linux") else "instale"
            issues.append(f"binário crítico '{b}' ausente — `{mgr} {b}`")
    # disco baixo bloqueia install/escrita
    try:
        from okami.core import sysmon
        flags = sysmon.health_flags(sysmon.host_stats(workspace))
        issues.extend(flags)
    except Exception:  # noqa: BLE001
        pass
    return {"ok": not issues, "python": py, "binaries": bins, "issues": issues}


def persist(workspace: str, rep: dict) -> None:
    """Grava o último diagnóstico em .okami/env-health.json (o gateway lê no boot p/ avisar o dono)."""
    import json
    from pathlib import Path
    try:
        d = Path(workspace) / ".okami"
        d.mkdir(parents=True, exist_ok=True)
        (d / "env-health.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


__all__ = ["binaries_status", "python_status", "report", "persist"]
