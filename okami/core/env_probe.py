"""Sonda do ambiente Python (#10) — injeta UMA linha no system prompt SÓ quando algo está torto.

Dev em macOS bate em paredes evitáveis: `pip install` que falha por PEP-668 (externally-managed),
`pip` ausente (só `python -m pip`), python vs python3. Esta sonda barata (~50ms, cacheada por processo,
silenciosa quando saudável) avisa o MODELO em runtime — diferente do `okami doctor`, que é p/ o humano
no CLI. Best-effort: nunca levanta; em dúvida, fica calada (não inventa problema).
"""
from __future__ import annotations

import subprocess
import sys

_CACHE: dict = {}


def _default_run(argv) -> tuple[int, str]:
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=5)  # noqa: S603
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def _default_externally_managed() -> bool:
    """True se o Python está marcado externally-managed (PEP-668) — `pip install` global é bloqueado."""
    import sysconfig
    from pathlib import Path
    for key in ("stdlib", "platstdlib"):
        try:
            d = sysconfig.get_path(key)
        except (KeyError, OSError):
            continue
        if d and (Path(d) / "EXTERNALLY-MANAGED").exists():
            return True
    return False


def probe_python_env(*, _run=None, _externally_managed=None, _cache=None) -> str:
    """Linha de aviso p/ o system prompt, ou "" se o ambiente está saudável. Cacheada por processo."""
    cache = _CACHE if _cache is None else _cache
    if "line" in cache:
        return cache["line"]
    run = _run or _default_run
    ext = _externally_managed or _default_externally_managed
    issues = []
    try:
        rc, out = run([sys.executable, "-m", "pip", "--version"])
        if rc != 0 or "no module named pip" in out.lower():
            issues.append("`pip` não está disponível (use `python -m pip` ou instale pip)")
        if ext():
            issues.append("ambiente externally-managed (PEP-668) — instale em venv/uv, NÃO global")
    except Exception:  # noqa: BLE001 — sonda nunca derruba nada; em erro, fica calada
        issues = []
    line = ("⚠ AMBIENTE PYTHON: " + "; ".join(issues) + ". Prefira `uv pip`/venv p/ instalar pacotes."
            if issues else "")
    cache["line"] = line
    return line
