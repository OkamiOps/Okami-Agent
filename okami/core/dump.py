"""`okami dump` (#9) — uma tela humano-colável p/ bug report. Sem ANSI, segredo REDIGIDO.

"rode `okami dump` e cole aqui" coleta de uma vez: HOME, commit git, versão, providers (só nomes +
modelo), canais configurados, contagem de skills. Tudo passa pelo redator central antes de sair.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def _git_commit() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip() or "(sem git)"
    except (OSError, subprocess.SubprocessError):
        return "(git indisponível)"


def _version() -> str:
    try:
        from okami import __version__
        return str(__version__)
    except Exception:  # noqa: BLE001
        return "(?)"


def build_dump(cfg, *, home=None, skills_dir=None) -> str:
    """Texto plano (sem segredo) com o estado essencial do agente p/ suporte/bug-report."""
    from okami.core.redact import redact
    home = Path(home) if home is not None else _default_home()
    lines = ["=== okami dump ===",
             f"versão: {_version()}   commit: {_git_commit()}",
             f"HOME: {home}",
             f"python: {_py()}"]
    provs = dict(getattr(cfg, "providers", None) or {}) if cfg is not None else {}
    lines.append(f"providers ({len(provs)}): " + (", ".join(
        f"{n}[{_model_of(p)}]" for n, p in provs.items()) or "(nenhum)"))
    chans = dict(getattr(cfg, "channels", None) or {}) if cfg is not None else {}
    lines.append("canais: " + (", ".join(sorted(map(str, chans))) or "(nenhum)"))
    lines.append(f"skills: {_count_skills(skills_dir)}")
    return redact("\n".join(lines))                       # rede de segurança: nada de segredo vaza


def _model_of(p) -> str:
    """Modelo de um provider — aceita dict OU ProviderConfig (pydantic)."""
    if isinstance(p, dict):
        return str(p.get("model", "?"))
    return str(getattr(p, "model", "?") or "?")


def _default_home():
    try:
        from okami.home import okami_home
        return okami_home()
    except Exception:  # noqa: BLE001
        return Path.home() / ".okami"


def _py() -> str:
    import platform
    return platform.python_version()


def _count_skills(skills_dir) -> int:
    if skills_dir is None:
        try:
            from okami.home import skills_dir as _sd
            skills_dir = _sd()
        except Exception:  # noqa: BLE001
            return 0
    try:
        return sum(1 for p in Path(skills_dir).glob("*/SKILL.md"))
    except OSError:
        return 0
