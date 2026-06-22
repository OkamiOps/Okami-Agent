"""Monitoramento da MÁQUINA (host) onde o agente roda — disco/RAM/CPU/load/uptime. Pra o agente se virar
sozinho numa VPS: checar recurso antes de tarefa pesada, diagnosticar lentidão, throttle proativo.

Stdlib primeiro (disco via shutil.disk_usage funciona em Win/Mac/Linux SEMPRE); psutil é auto-instalado
(lazy) p/ RAM/CPU/uptime ricos nas 3 plataformas, com fallback POSIX (/proc, getloadavg) se faltar.
"""
from __future__ import annotations

import os
import shutil
import time


def _try_psutil():
    """psutil (auto-instala na 1ª vez). None se offline/sem suporte → cai no fallback stdlib."""
    try:
        from okami.core.lazy_deps import ensure
        ensure("monitor.psutil")
        import psutil
        return psutil
    except Exception:  # noqa: BLE001
        return None


def _gb(n: float) -> float:
    return round(n / 1_000_000_000, 2)


def _mem_from_proc() -> dict | None:
    """Fallback de RAM no Linux (sem psutil): /proc/meminfo."""
    try:
        info = {}
        with open("/proc/meminfo", encoding="utf-8") as f:
            for ln in f:
                k, _, v = ln.partition(":")
                info[k.strip()] = int(v.strip().split()[0]) * 1024   # kB → bytes
        total, avail = info.get("MemTotal", 0), info.get("MemAvailable", 0)
        if not total:
            return None
        return {"total_gb": _gb(total), "available_gb": _gb(avail),
                "used_pct": round((total - avail) / total * 100, 1)}
    except (OSError, ValueError, KeyError):
        return None


def host_stats(path: str = ".") -> dict:
    """Saúde do host. Sempre traz disco (stdlib); RAM/CPU/load/uptime quando dá. Nunca levanta."""
    out: dict = {}
    try:
        du = shutil.disk_usage(str(path) or os.getcwd())
        out["disk"] = {"total_gb": _gb(du.total), "free_gb": _gb(du.free),
                       "used_pct": round(du.used / du.total * 100, 1) if du.total else 0.0}
    except OSError:
        pass

    ps = _try_psutil()
    if ps is not None:
        try:
            vm = ps.virtual_memory()
            out["memory"] = {"total_gb": _gb(vm.total), "available_gb": _gb(vm.available), "used_pct": vm.percent}
        except Exception:  # noqa: BLE001
            pass
        try:
            out["cpu"] = {"percent": ps.cpu_percent(interval=0.15), "cores": ps.cpu_count()}
        except Exception:  # noqa: BLE001
            pass
        try:
            out["uptime_h"] = round((time.time() - ps.boot_time()) / 3600, 1)
        except Exception:  # noqa: BLE001
            pass
        try:
            out["processes"] = len(ps.pids())
        except Exception:  # noqa: BLE001
            pass
    else:                                                  # fallback stdlib (POSIX)
        m = _mem_from_proc()
        if m:
            out["memory"] = m
    if hasattr(os, "getloadavg") and "load" not in out:    # load avg (POSIX): 1/5/15 min
        try:
            out["load"] = [round(x, 2) for x in os.getloadavg()]
        except OSError:
            pass
    return out


def health_flags(stats: dict) -> list[str]:
    """Alertas acionáveis a partir das stats — o agente decide adiar/limpar antes de uma tarefa pesada."""
    flags = []
    disk = stats.get("disk") or {}
    if disk.get("free_gb") is not None and disk["free_gb"] < 1.0:
        flags.append(f"⚠ disco quase cheio: {disk['free_gb']} GB livres")
    elif disk.get("used_pct", 0) >= 95:
        flags.append(f"⚠ disco em {disk['used_pct']}%")
    mem = stats.get("memory") or {}
    if mem.get("used_pct", 0) >= 92:
        flags.append(f"⚠ RAM em {mem['used_pct']}%")
    load = stats.get("load") or []
    cpu = stats.get("cpu") or {}
    cores = cpu.get("cores") or 1
    if load and cores and load[0] > cores * 2:
        flags.append(f"⚠ load alto: {load[0]} (≈{cores} cores)")
    return flags


__all__ = ["host_stats", "health_flags"]
