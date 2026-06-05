"""Manutenção / gestão de disco — limpa lock órfão, conserta permissões, poda temporários e aplica QUOTA.

Funções puras-testáveis que `okami clean` e `doctor --fix`/`status` usam. Conservador de propósito: NÃO
apaga transcript/checkpoint ATIVO nem o journal de rollback; mexe em lock órfão, perms do .env,
temporários (áudio/.tmp), e — no modo `--deep` — aplica a RETENÇÃO declarada (sessions/checkpoints/
process logs/tool_outputs) por idade+contagem. Tudo aceita `dry_run` (lista sem apagar).

Por que isto vira P1 num gateway long-running: tool_outputs/checkpoints/process logs CRESCEM sem teto.
Sem poda, o agente "morre em disco". A retenção é VERSIONADA no okami.yaml (bloco `retention:`); o cron
roda `okami clean --deep` e o `status`/`doctor` mostram o uso por área (com aviso de quota estourada).
"""

from __future__ import annotations

import os
import stat
import time
from pathlib import Path

_SKIP = {".git", "node_modules", ".venv", "__pycache__"}


# ── retenção declarada (versionada no okami.yaml) ──────────────────────────────
# Defaults conservadores: mantêm bastante coisa, podam só o que envelheceu MUITO. Cada área pode
# sobrepor days/keep; `quota_mb` (0 = sem teto) é só p/ AVISO no status/doctor (não apaga sozinho).
_RETENTION_DEFAULTS = {
    "sessions":     {"days": 30.0, "keep": 10},     # transcripts ARQUIVADOS (*.reset.jsonl)
    "checkpoints":  {"days": 14.0, "keep": 50},     # snapshots (journal.jsonl é sagrado)
    "tool_outputs": {"days": 7.0,  "keep": 200},    # step_*.txt de output grande (cresce rápido)
    "processes":    {"ttl_hours": 24.0},            # processos JÁ TERMINADOS
    "audio":        {"enabled": True},              # voz/TTS temporário
    "quota_mb":     {},                             # ex.: {tool_outputs: 200, checkpoints: 100} → aviso
}


def resolve_retention(cfg_retention: dict | None) -> dict:
    """Mescla o bloco `retention:` do okami.yaml sobre os defaults (campos ausentes = default)."""
    out = {k: dict(v) for k, v in _RETENTION_DEFAULTS.items()}
    for area, conf in (cfg_retention or {}).items():
        if isinstance(conf, dict):
            out.setdefault(area, {}).update(conf)
        else:
            out[area] = conf
    return out


# ── faxina conservadora (sempre segura) ────────────────────────────────────────
def clean_stale_locks(root, *, stale: float = 300.0, dry_run: bool = False) -> list[str]:
    """Remove arquivos `.lock` órfãos (mtime > `stale`s) sob `root`. Devolve os caminhos removidos."""
    removed = []
    now = time.time()
    for lk in Path(root).rglob("*.lock"):
        if any(part in _SKIP for part in lk.parts):
            continue
        try:
            if now - lk.stat().st_mtime > stale:
                if not dry_run:
                    lk.unlink()
                removed.append(str(lk))
        except OSError:
            pass
    return removed


def fix_env_perms(env_path) -> bool:
    """Garante 0600 no .env de segredos. True se PRECISOU corrigir."""
    p = Path(env_path)
    if not p.exists():
        return False
    try:
        if stat.S_IMODE(p.stat().st_mode) != 0o600:
            os.chmod(p, 0o600)
            return True
    except OSError:
        pass
    return False


def prune_temp(root, *, patterns=("*.tmp", ".env.*.tmp"), dry_run: bool = False) -> tuple[list[str], int]:
    """Remove temporários deixados pra trás (tmp de escrita atômica). Devolve (removidos, bytes)."""
    removed, freed = [], 0
    for pat in patterns:
        for f in Path(root).rglob(pat):
            if not f.is_file() or any(part in _SKIP for part in f.parts):
                continue
            try:
                sz = f.stat().st_size
                if not dry_run:
                    f.unlink()
                removed.append(str(f))
                freed += sz
            except OSError:
                pass
    return removed, freed


def prune_audio(root, *, dry_run: bool = False) -> tuple[list[str], int]:
    """Limpa áudio temporário (voz/TTS): .okami/voice/* e okami_say*.mp3. Devolve (removidos, bytes)."""
    removed, freed = [], 0
    targets = list((Path(root) / ".okami" / "voice").glob("*")) + list(Path(root).glob("okami_say*.mp3"))
    for f in targets:
        try:
            if f.is_file():
                sz = f.stat().st_size
                if not dry_run:
                    f.unlink()
                removed.append(str(f))
                freed += sz
        except OSError:
            pass
    return removed, freed


# ── quota por idade+contagem (poda real) ───────────────────────────────────────
def prune_by_age_and_count(directory, *, pattern: str = "*", days: float = 30.0,
                           keep: int = 20, exclude=(), dry_run: bool = False) -> tuple[list[str], int]:
    """Poda arquivos: MANTÉM os `keep` mais recentes; remove o resto que for mais velho que `days`.
    Devolve (removidos, bytes). `exclude` protege nomes (ex.: journal.jsonl). `dry_run` não apaga."""
    d = Path(directory)
    if not d.exists():
        return [], 0
    files = sorted((f for f in d.glob(pattern) if f.is_file() and f.name not in set(exclude)),
                   key=lambda f: f.stat().st_mtime, reverse=True)
    cutoff = time.time() - days * 86400
    removed, freed = [], 0
    for f in files[keep:]:                          # além dos `keep` mais novos
        try:
            if f.stat().st_mtime < cutoff:
                sz = f.stat().st_size
                if not dry_run:
                    f.unlink()
                removed.append(str(f))
                freed += sz
        except OSError:
            pass
    return removed, freed


def prune_sessions(root, *, days: float = 30.0, keep: int = 10, dry_run: bool = False) -> tuple[list[str], int]:
    """Poda transcripts ARQUIVADOS (`*.reset.jsonl`) de sessions/groups — quota por idade+contagem."""
    removed, freed = [], 0
    for sub in ("sessions", "groups"):
        r, fr = prune_by_age_and_count(Path(root) / ".okami" / sub,
                                       pattern="*.reset.jsonl", days=days, keep=keep, dry_run=dry_run)
        removed += r
        freed += fr
    return removed, freed


def prune_checkpoints(root, *, days: float = 14.0, keep: int = 50, dry_run: bool = False) -> tuple[list[str], int]:
    """Poda snapshots antigos de checkpoints — MANTÉM o journal.jsonl (rollback) sempre."""
    return prune_by_age_and_count(Path(root) / ".okami" / "checkpoints",
                                  days=days, keep=keep, exclude={"journal.jsonl"}, dry_run=dry_run)


def prune_tool_outputs(root, *, days: float = 7.0, keep: int = 200, dry_run: bool = False) -> tuple[list[str], int]:
    """Poda os step_*.txt de output grande (.okami/tool_outputs) — cresce rápido no gateway."""
    return prune_by_age_and_count(Path(root) / ".okami" / "tool_outputs",
                                  pattern="*.txt", days=days, keep=keep, dry_run=dry_run)


def prune_processes(root, *, ttl_hours: float = 24.0, dry_run: bool = False) -> list[str]:
    """Remove processos em background JÁ TERMINADOS há mais de `ttl_hours` (cleanup TTL #1/#8)."""
    from okami.core.processes import ProcessManager
    try:
        return ProcessManager(root).prune(ttl_seconds=ttl_hours * 3600.0, dry_run=dry_run)
    except Exception:  # noqa: BLE001
        return []


# ── uso de disco (relatório p/ status/doctor) ──────────────────────────────────
def dir_usage(path) -> tuple[int, int]:
    """(bytes, nº de arquivos) de uma árvore — segue subdirs, ignora links quebrados."""
    p = Path(path)
    total, count = 0, 0
    if not p.exists():
        return 0, 0
    if p.is_file():
        try:
            return p.stat().st_size, 1
        except OSError:
            return 0, 0
    for f in p.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
                count += 1
        except OSError:
            pass
    return total, count


# área → (rótulo, caminho relativo sob o workspace, é poda no --deep?)
_DISK_AREAS = [
    ("processes",    ".okami/processes",    True),
    ("checkpoints",  ".okami/checkpoints",  True),
    ("tool_outputs", ".okami/tool_outputs", True),
    ("sessions",     ".okami/sessions",     True),
    ("groups",       ".okami/groups",       True),
    ("memory",       ".okami/memory.db",    False),   # durável — só reporta
    ("memory_holo",  ".okami/memory-holo.db", False),
    ("audit",        ".okami/audit.jsonl",  False),
    ("events",       ".okami/events.jsonl", False),
    ("voice",        ".okami/voice",        True),
]


def disk_report(root, *, retention: dict | None = None) -> dict:
    """Uso de disco por área (bytes/arquivos) + total + aviso de quota_mb estourada. Não apaga nada."""
    ret = resolve_retention(retention)
    quotas = ret.get("quota_mb") or {}
    areas, total = {}, 0
    for key, rel, prunable in _DISK_AREAS:
        b, n = dir_usage(Path(root) / rel)
        if n == 0 and b == 0:
            continue                                # área inexistente → não polui o relatório
        q = float(quotas.get(key, 0) or 0)
        over = bool(q) and b > q * 1024 * 1024
        areas[key] = {"bytes": b, "files": n, "prunable": prunable,
                      "quota_mb": q, "over_quota": over}
        total += b
    return {"workspace": str(root), "areas": areas, "bytes_total": total,
            "over_quota": [k for k, v in areas.items() if v["over_quota"]]}


# ── orquestração ───────────────────────────────────────────────────────────────
def clean_workspace(root, *, lock_stale: float = 300.0, proc_ttl_hours: float = 24.0,
                    dry_run: bool = False) -> dict:
    """Faxina padrão (conservadora) — devolve um relatório com contagens e bytes liberados."""
    locks = clean_stale_locks(root, stale=lock_stale, dry_run=dry_run)
    rm_t, freed_t = prune_temp(root, dry_run=dry_run)
    rm_a, freed_a = prune_audio(root, dry_run=dry_run)
    rm_p = prune_processes(root, ttl_hours=proc_ttl_hours, dry_run=dry_run)
    return {
        "locks_removed": len(locks),
        "temp_removed": len(rm_t),
        "audio_removed": len(rm_a),
        "processes_removed": len(rm_p),
        "bytes_freed": freed_t + freed_a,
    }


def run_clean(root, *, lock_stale: float = 300.0, deep: bool = False,
              retention: dict | None = None, dry_run: bool = False) -> dict:
    """Faxina COMPLETA com relatório por ÁREA (machine-readable p/ `okami clean --json`).

    Sempre: lock órfão + temp + áudio + processos terminados (TTL).
    `--deep`: aplica a RETENÇÃO declarada (sessions/checkpoints/tool_outputs por idade+contagem).
    `dry_run`: lista o que SERIA removido (não apaga)."""
    ret = resolve_retention(retention)
    areas: dict[str, dict] = {}

    def _rec(name, removed, freed):
        areas[name] = {"removed": len(removed), "bytes": int(freed)}

    locks = clean_stale_locks(root, stale=lock_stale, dry_run=dry_run)
    _rec("locks", locks, 0)
    _rec("temp", *_pair(prune_temp(root, dry_run=dry_run)))
    if (ret.get("audio") or {}).get("enabled", True):
        _rec("audio", *_pair(prune_audio(root, dry_run=dry_run)))
    proc = prune_processes(root, ttl_hours=float((ret.get("processes") or {}).get("ttl_hours", 24.0)),
                           dry_run=dry_run)
    _rec("processes", proc, 0)

    if deep:
        s = ret.get("sessions") or {}
        _rec("sessions", *_pair(prune_sessions(root, days=float(s.get("days", 30)),
                                               keep=int(s.get("keep", 10)), dry_run=dry_run)))
        c = ret.get("checkpoints") or {}
        _rec("checkpoints", *_pair(prune_checkpoints(root, days=float(c.get("days", 14)),
                                                     keep=int(c.get("keep", 50)), dry_run=dry_run)))
        to = ret.get("tool_outputs") or {}
        _rec("tool_outputs", *_pair(prune_tool_outputs(root, days=float(to.get("days", 7)),
                                                       keep=int(to.get("keep", 200)), dry_run=dry_run)))

    total = sum(a["bytes"] for a in areas.values())
    return {"workspace": str(root), "deep": deep, "dry_run": dry_run,
            "areas": areas, "bytes_freed": total,
            "items_removed": sum(a["removed"] for a in areas.values())}


def _pair(t):
    """(removidos, bytes) → (removidos, bytes) — só p/ desempacotar em _rec sem ruído visual."""
    return t[0], t[1]


def fmt_bytes(n: float) -> str:
    """Humaniza bytes (B/KB/MB/GB) p/ exibir no terminal."""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"
