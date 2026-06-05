"""Diagnóstico estruturado do Okami (P2) — coleta um RELATÓRIO testável (e --json p/ monitoramento).

Separa COLETA de apresentação: `build_report(cfg)` devolve um dict (provider/auth/toolchain/sandbox/
memória/permissões), que o `okami doctor` rende bonito OU dumpa em JSON. `ping` é injetável (teste).
"""

from __future__ import annotations

import platform
import shutil
import sqlite3
import stat
from pathlib import Path


def build_report(cfg, *, ping=None) -> dict:
    """Coleta o diagnóstico num dict (sem imprimir). `ping(api_base) -> (ok, msg)` injetável."""
    from okami import __version__
    rep: dict = {
        "version": __version__,
        "platform": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "default_provider": cfg.default_provider,
        "providers": [],
        "memory": {},
        "toolchain": {},
        "checks": {},
        "mcp": list(getattr(cfg, "mcp", None) or {}),
    }
    for name, pc in cfg.providers.items():
        p = {"name": name, "tier": pc.tier, "model": pc.model, "transport": pc.transport,
             "ready": bool(pc.ready), "api_base": pc.api_base or ""}
        if pc.api_base and ping is not None:
            ok, msg = ping(pc.api_base)
            p["endpoint"] = {"ok": bool(ok), "msg": msg}
        rep["providers"].append(p)

    mem = cfg.memory or {}
    rep["memory"] = {"backend": mem.get("backend", "sqlite-fts5"),
                     "embedder": (mem.get("embedder") or {}).get("model", "")}

    for tool in ("git", "uv", "node", "docker", "claude", "rg"):
        rep["toolchain"][tool] = shutil.which(tool) or ""

    try:
        c = sqlite3.connect(":memory:")
        c.execute("CREATE VIRTUAL TABLE _t USING fts5(x)")
        c.close()
        rep["checks"]["sqlite_fts5"] = True
    except sqlite3.Error:
        rep["checks"]["sqlite_fts5"] = False

    from okami.home import read_path
    rep["checks"]["codex_auth"] = ((Path.home() / ".codex" / "auth.json").exists()
                                   or read_path("credentials", "codex.json").exists())

    from okami.config import global_env_path
    genv = global_env_path()
    if genv.exists():
        mode = stat.S_IMODE(genv.stat().st_mode)
        rep["checks"]["env_perms"] = oct(mode)
        rep["checks"]["env_perms_ok"] = (mode == 0o600)
    else:
        rep["checks"]["env_perms"] = None
        rep["checks"]["env_perms_ok"] = None

    from okami.core.sandbox import SandboxPolicy
    sb = SandboxPolicy.from_config(getattr(cfg, "sandbox", {}) or {})
    rep["sandbox"] = {"backend": sb.backend, "mode": sb.mode,
                      "network": sb.network_on, "timeout": sb.timeout}
    return rep


def health_ok(report: dict) -> bool:
    """Resumo binário p/ scripts: True se nada CRÍTICO está quebrado (default provider pronto, FTS5)."""
    providers = {p["name"]: p for p in report.get("providers", [])}
    dp = providers.get(report.get("default_provider"))
    return bool(dp and dp.get("ready")) and report.get("checks", {}).get("sqlite_fts5", False)
