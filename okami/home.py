"""Casa do Okami — onde skills/agents/sessões moram, SEM espalhar no diretório do usuário.

Como OpenClaw (~/.openclaw) e Hermes: por padrão tudo vive numa casa única, `~/.okami/` (ou
`$OKAMI_HOME`). Um PROJETO de verdade (okami.yaml numa pasta que NÃO seja a home) vira a base — aí
skills/agents/.okami ficam no projeto, como você espera de um repositório. O que NÃO acontece mais:
largar `~/skills` e `~/agents` soltos na home só porque você rodou o `okami` de lá.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def okami_home() -> Path:
    """A casa GLOBAL do Okami: `$OKAMI_HOME` (se setado) ou `~/.okami`."""
    env = os.environ.get("OKAMI_HOME")
    return Path(env).expanduser() if env else Path.home() / ".okami"


def project_root(start: Path | None = None) -> Path | None:
    """Pasta do okami.yaml (CWD ou ancestral), ou None se não houver projeto."""
    from okami.config import find_config
    try:
        return find_config(start).parent
    except FileNotFoundError:
        return None


def base_dir() -> Path:
    """Base efetiva p/ skills/agents/sessões: a raiz do PROJETO (okami.yaml fora da home) se houver;
    senão a casa global (`~/.okami`/`$OKAMI_HOME`). NUNCA a home crua — é isso que evita o espalhamento.

    'projeto = home' (okami.yaml na própria home) também cai na casa global: a config pode morar na
    home, mas os dados vão pra `~/.okami/`, não soltos na sua pasta de usuário."""
    root = project_root()
    if root is not None and root != Path.home():
        return root
    return okami_home()


def skills_dir() -> Path:
    return base_dir() / "skills"


def agents_dir() -> Path:
    return base_dir() / "agents"


def agent_locations() -> dict:
    """Diagnóstico de DIVERGÊNCIA de config de agente. `effective` = base_dir()/agents (onde os comandos
    de config gravam AGORA, dependente do CWD); `global` = ~/.okami/agents (o que o gateway lê quando
    rodado de fora de um projeto, ex.: serviço/home). `diverges`=True quando as duas existem, são
    DIFERENTES, e a global tem agentes que a efetiva não tem → a config 'some' da vista do usuário
    (escreveu numa, o gateway lê a outra). Causa do 'sistema não está salvando'."""
    eff = agents_dir()
    glob = okami_home() / "agents"

    def _agents(d: Path) -> list[str]:
        if not d.exists():
            return []
        return sorted(p.name for p in d.iterdir() if (p / "agent.yaml").exists())

    ea, ga = _agents(eff), _agents(glob)
    diverges = eff != glob and bool(ga) and set(ea) != set(ga)
    # str (não Path) → o dict é JSON-serializável (entra no `okami doctor --json`).
    return {"effective": str(eff), "global": str(glob), "diverges": diverges,
            "effective_agents": ea, "global_agents": ga}


# ── caminhos GLOBAIS (segredos/credenciais) — sempre dentro da casa, nunca Path.home()/".okami" cru ──
def home_path(*parts: str) -> Path:
    """Caminho dentro da casa do Okami (okami_home()/...). Use SEMPRE isto — é a fonte única."""
    return okami_home().joinpath(*parts)


def read_path(*parts: str) -> Path:
    """Caminho p/ LER: a casa ATUAL se existir; senão a LEGADA (~/.okami) se existir; senão a atual.
    Migração suave: se você muda OKAMI_HOME, credenciais/segredos antigos seguem encontráveis."""
    cur = home_path(*parts)
    if cur.exists():
        return cur
    legacy = (Path.home() / ".okami").joinpath(*parts)
    return legacy if legacy.exists() else cur


def env_path() -> Path:
    """O `.env` GLOBAL de segredos (canônico p/ ESCRITA): okami_home()/.env."""
    return home_path(".env")


def credentials_dir() -> Path:
    """Pasta de credenciais OAuth (canônica p/ ESCRITA): okami_home()/credentials."""
    return home_path("credentials")


# Arquivo-marcador que PROVA que a pasta é do Okami (não uma pasta genérica da sua home).
# Sem ele, não tocamos: um `~/skills` ou `~/agents` qualquer fica onde está.
_STRAY_MARKERS = {"skills": "SKILL.md", "agents": "agent.yaml"}


def _looks_like_okami(folder: Path, marker: str) -> bool:
    """True só se houver ≥1 arquivo-marcador (em qualquer profundidade) — ex.: SKILL.md / agent.yaml."""
    try:
        return next(folder.rglob(marker), None) is not None
    except OSError:
        return False


def migrate_stray(*, emit=lambda m: None) -> list[str]:
    """Move os FILHOS do Okami de `~/skills`/`~/agents` pra dentro de `~/.okami/` — só os subdiretórios
    que têm o arquivo-marcador (SKILL.md / agent.yaml). Idempotente, não-clobbera, registra manifesto.

    POR-FILHO de propósito: se `~/skills` tem 20 coisas genéricas suas e UMA subpasta com SKILL.md, só
    essa subpasta vai — o resto fica onde está (nunca sequestra a pasta inteira). Respeita home-como-
    projeto (okami.yaml na home → não mexe). Limpa `~/skills`/`~/agents` se ficarem vazios depois."""
    home = okami_home()
    if (Path.home() / "okami.yaml").exists() or (Path.home() / "okami.yml").exists():
        return []                                    # home É um projeto explícito → respeita, não mexe
    moved: list[str] = []
    for sub, marker in _STRAY_MARKERS.items():
        stray = Path.home() / sub
        target = home / sub
        if not (stray.is_dir() and not stray.is_symlink()) or stray.resolve() == target.resolve():
            continue
        children = []                                # move só os FILHOS com marcador (não a pasta inteira)
        for child in sorted(p for p in stray.iterdir() if p.is_dir() and not p.is_symlink()):
            if next(child.rglob(marker), None) is None:
                continue                             # subpasta genérica (sem SKILL.md/agent.yaml) → fica
            dst = target / child.name
            if dst.exists():
                continue                             # não clobbera o que já está na casa
            try:
                target.mkdir(parents=True, exist_ok=True)
                shutil.move(str(child), str(dst))
                children.append(child.name)
            except OSError:
                pass
        if children:
            moved.append(sub)
            emit(f"📦 movi {len(children)} do Okami: ~/{sub}/* → {target}/ "
                 f"({', '.join(children[:5])}{'…' if len(children) > 5 else ''})")
        try:                                         # ~/skills/~/agents vazio depois → remove o resíduo
            if stray.is_dir() and not any(stray.iterdir()):
                stray.rmdir()
        except OSError:
            pass
    if moved:
        _record_migration(home, moved)
    return moved


def _record_migration(home: Path, moved: list[str]) -> None:
    """Anexa um manifesto JSON (`<home>/migrations.json`) — prova auditável do que foi movido e
    de onde, pra quando/se você quiser reverter. Best-effort: nunca derruba o boot por causa disso."""
    import json
    from datetime import datetime, timezone

    path = home / "migrations.json"
    try:
        log = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        if not isinstance(log, list):
            log = []
    except (OSError, ValueError):
        log = []
    log.append({
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "moved": list(moved),
        "from": str(Path.home()),
        "to": str(home),
    })
    try:
        path.write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass
