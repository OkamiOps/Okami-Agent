"""Instalador HEADLESS de skill externa — MESMA pipeline do `okami learn`, mas chamável por código/tool.

Motivo (bugfix): o agente NÃO tinha como instalar uma skill externa (use_skill só carrega, manage_skill só
AUTORA; instalar era `okami learn`, CLI-only) → improvisava `npx skills add` (CLI de terceiro que pede
Docker), travava e perguntava ao dono p/ abrir o Docker. Aqui o caminho NATIVO e seguro vira reusável.

NUNCA usa Docker: github/url → git clone; caminho local → copytree; clawhub/npx só com allow_exec (rodam
código ANTES do scan). Quarentena → load_skills → scan de segurança → matriz confiança×verdict → instala
+ lockfile (proveniência sha256). HIGH/CRITICAL bloqueia (segurança vence confiança), salvo force.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class InstallResult:
    ok: bool
    installed: list[str] = field(default_factory=list)
    reason: str = ""
    kind: str = ""
    trust: str = ""
    verdict: str = "INFO"
    decision: str = ""
    deps: list[str] = field(default_factory=list)   # deps externas a instalar À MÃO (npm/pip) — antes era
    #   silêncio: instalava 'ok' e o script estourava em runtime (puppeteer/chromium → travamento de 300s)


def detect_dependencies(skill_dir) -> list[str]:
    """Olha a pasta da skill por manifestos de dependência externa e devolve instruções ACIONÁVEIS. Skill de
    terceiros (ex.: html-to-pdf via puppeteer) não roda sem `npm install`/`pip install` — sem este aviso o
    erro só aparecia em runtime (módulo não encontrado / Chromium baixando → estourava o anti-travamento)."""
    d = Path(skill_dir)
    out: list[str] = []
    if (d / "package.json").exists():
        out.append("npm install (Node: esta skill tem package.json — ex.: puppeteer baixa ~170MB de Chromium)")
    for req in ("requirements.txt", "pyproject.toml"):
        if (d / req).exists():
            out.append(f"pip install -r {req}" if req == "requirements.txt" else "pip install . (pyproject.toml)")
            break
    if (d / "Gemfile").exists():
        out.append("bundle install (Ruby)")
    if (d / "go.mod").exists():
        out.append("go mod download (Go)")
    return out


def install_from_source(source, skills_root, lock_root, *, allow_exec: bool = False,
                        force: bool = False, only: str = "", fetch=None, quarantine=None) -> InstallResult:
    """Baixa (fetch injetável → testável offline), valida e instala skill(s) da `source` em `skills_root`,
    registrando proveniência no lockfile em `lock_root`. `only` instala só a skill com esse nome (repo
    com várias). Devolve InstallResult (nunca lança por fonte malformada)."""
    from okami.skills import load_skills
    from okami.skills.skill_security import SEV_NAME, scan_path
    from okami.skills.sources import classify_source, install_decision

    src = classify_source(source)
    # clawhub/npx EXECUTAM código no fetch ANTES do scan validar → exige opt-in explícito (mesmo gate do
    # `okami learn --allow-exec`). NUNCA roda o fetch desses sem permissão (e jamais toca em Docker).
    if src.exec_on_fetch and not allow_exec:
        return InstallResult(False, kind=src.kind, trust=src.trust,
                             reason="esta fonte EXECUTA código no fetch (clawhub/npx) ANTES do scan; "
                                    "passe allow_exec=true só se confiar na origem (prefira git/caminho local).")

    if quarantine is None:
        from okami.home import okami_home
        quarantine = okami_home() / "quarantine"
    quarantine = Path(quarantine)
    shutil.rmtree(quarantine, ignore_errors=True)
    quarantine.mkdir(parents=True, exist_ok=True)

    if fetch is None:                                  # default real: git clone / copytree (sem Docker)
        from okami.cli._shared import _fetch_skill_source as fetch
    try:
        fetch(source, quarantine)
    except FileNotFoundError as e:
        return InstallResult(False, kind=src.kind, trust=src.trust,
                             reason=f"ferramenta de fetch ausente ({e}); precisa de git (ou npx p/ clawhub).")
    except Exception as e:  # noqa: BLE001 — fetch de fonte externa nunca derruba o chamador
        return InstallResult(False, kind=src.kind, trust=src.trust, reason=f"falha ao buscar a fonte: {e}")

    found = load_skills(quarantine)
    if not found:
        shutil.rmtree(quarantine, ignore_errors=True)
        return InstallResult(False, kind=src.kind, trust=src.trust,
                             reason="nenhuma SKILL.md encontrada na fonte.")
    if only:                                           # repo-biblioteca: instala só a skill pedida
        sel = [s for s in found if only in (s.name, s.path.parent.name)]
        if not sel:
            avail = ", ".join(sorted(s.name for s in found))
            shutil.rmtree(quarantine, ignore_errors=True)
            return InstallResult(False, kind=src.kind, trust=src.trust,
                                 reason=f"skill '{only}' não encontrada na fonte. Disponíveis: {avail}")
        found = sel

    report = scan_path(quarantine)                     # scan do repo INTEIRO (não instala de repo com payload)
    verdict = SEV_NAME[report.max_severity]
    decision = install_decision(src.trust, verdict)
    if decision == "block" and not force:
        shutil.rmtree(quarantine, ignore_errors=True)
        return InstallResult(False, kind=src.kind, trust=src.trust, verdict=verdict, decision=decision,
                             reason=f"BLOQUEADO: scan {verdict} (segurança vence confiança). "
                                    "Ficou fora do catálogo.")

    from okami.skills.lockfile import record
    skills_root = Path(skills_root)
    skills_root.mkdir(parents=True, exist_ok=True)
    installed: list[str] = []
    deps: list[str] = []
    for s in found:
        target = skills_root / s.path.parent.name
        shutil.copytree(s.path.parent, target, dirs_exist_ok=True)
        try:
            target.chmod(0o700)                        # skill privada do dono (hooks/config) em VPS multi-user:
        except OSError:                                # 0700 no dir bloqueia outro usuário SEM mexer no +x dos files
            pass
        for _sh in target.rglob("*.sh"):               # scripts da skill com bit de execução (SKILL.md manda ./run.sh)
            try:
                _sh.chmod(0o700)
            except OSError:
                pass
        deps += [f"{s.name}: {d}" for d in detect_dependencies(target)]   # avisa deps externas (npm/pip) — não trava em runtime
        record(Path(lock_root), s.name, source=str(source), skill_dir=target)   # proveniência + sha256
        installed.append(s.name)
    shutil.rmtree(quarantine, ignore_errors=True)
    reason = ("instalada, mas precisa instalar deps externas À MÃO: " + "; ".join(deps)) if deps else ""
    return InstallResult(True, installed=installed, kind=src.kind, trust=src.trust,
                         verdict=verdict, decision=decision, deps=deps, reason=reason)
