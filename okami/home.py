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
    """Move `~/skills` e `~/agents` SOLTOS na home pra dentro de `~/.okami/` — mas SÓ quando são
    comprovadamente do Okami (têm o arquivo-marcador). Idempotente, não-clobbera, registra manifesto.

    Não invasivo de propósito: um `~/skills` genérico (sem nenhum SKILL.md) ou `~/agents` sem nenhum
    agent.yaml NÃO é tocado — só avisa. Assim o primeiro `okami` num PC alheio nunca sequestra uma
    pasta que não é nossa. Também respeita a home-como-projeto (okami.yaml na home → não mexe)."""
    home = okami_home()
    if (Path.home() / "okami.yaml").exists() or (Path.home() / "okami.yml").exists():
        return []                                    # home É um projeto explícito → respeita, não mexe
    moved: list[str] = []
    for sub, marker in _STRAY_MARKERS.items():
        stray = Path.home() / sub
        target = home / sub
        if not (stray.is_dir() and not stray.is_symlink()) or target.exists():
            continue
        if stray.resolve() == target.resolve():
            continue
        if not _looks_like_okami(stray, marker):
            emit(f"… ~/{sub} existe mas sem {marker} — não parece do Okami; deixei como está.")
            continue
        try:
            home.mkdir(parents=True, exist_ok=True)
            shutil.move(str(stray), str(target))
            moved.append(sub)
            emit(f"📦 movido ~/{sub} → {target} (Okami agora guarda tudo em {home})")
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
