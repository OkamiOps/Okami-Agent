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


def migrate_stray(*, emit=lambda m: None) -> list[str]:
    """Move `~/skills` e `~/agents` SOLTOS na home pra dentro de `~/.okami/` (uma vez, idempotente).

    Só age quando a home NÃO é um projeto (sem okami.yaml na home) e o destino ainda não existe —
    nunca clobbera nem mexe num projeto de verdade. Retorna o que moveu."""
    home = okami_home()
    if (Path.home() / "okami.yaml").exists() or (Path.home() / "okami.yml").exists():
        return []                                    # home É um projeto explícito → respeita, não mexe
    moved: list[str] = []
    for sub in ("skills", "agents"):
        stray = Path.home() / sub
        target = home / sub
        if stray.is_dir() and not stray.is_symlink() and not target.exists() and stray.resolve() != target.resolve():
            try:
                home.mkdir(parents=True, exist_ok=True)
                shutil.move(str(stray), str(target))
                moved.append(sub)
                emit(f"📦 movido ~/{sub} → {target} (Okami agora guarda tudo em {home})")
            except OSError:
                pass
    return moved
