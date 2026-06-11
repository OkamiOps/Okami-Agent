"""Segurança de arquivos do núcleo — estilo Hermes `file_safety.py`.

Centraliza o que estava espalhado em `tools._safe_path`: jail de workspace, bloqueio de
symlink-escape, TETO de tamanho (leitura e escrita) e ESCRITA ATÔMICA (sem arquivo
meia-escrito se o processo morrer no meio). read_file/write_file/edit_file usam tudo isto.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Tetos conservadores: o agente é um executor de texto/código, não move blobs gigantes.
MAX_READ_BYTES = 5_000_000     # 5 MB — lê arquivo-texto sem estourar a memória
MAX_WRITE_BYTES = 10_000_000   # 10 MB — teto de escrita


class PathEscape(ValueError):
    """Tentativa de sair do workspace (path traversal ou symlink apontando p/ fora)."""


class FileTooLarge(ValueError):
    """Arquivo/conteúdo acima do teto — barrado p/ não estourar memória/saída."""


def safe_path(workspace: Path, rel: str, *, open_fs: bool = False, allow_paths=None) -> Path:
    """Resolve `rel` (relativo ancora em `workspace`; absoluto vale como veio) e, por padrão, BLOQUEIA
    escape do workspace.

    `.resolve()` canoniciza `..` E segue symlinks — um link apontando p/ fora do workspace resolve p/ um
    caminho fora do jail e cai no bloqueio (symlink-escape coberto de graça).

    `open_fs=True` (DONO no CLI): dispensa o jail → o agente alcança QUALQUER arquivo do computador
    (relativo no `workspace`=CWD, absoluto livre).

    `allow_paths` (config `tools.allow_paths`): pastas EXTRAS liberadas além do workspace (ex.: ~/Downloads).
    Mais seguro que open_fs — só os diretórios listados. `~` é expandido.

    As proteções que CONTINUAM valendo em qualquer caso: aprovação go/no-go, `_SENSITIVE_PATH` (segredos)
    e o hardline. NUNCA ligue `open_fs` em superfície não-confiável; prefira `allow_paths` pontual."""
    ws = workspace.resolve()
    p = (ws / rel).resolve()
    if open_fs:
        return p
    if p == ws or ws in p.parents:
        return p
    for ap in (allow_paths or []):                      # pastas extras liberadas (config)
        base = Path(str(ap)).expanduser().resolve()
        if p == base or base in p.parents:
            return p
    raise PathEscape(f"caminho fora do workspace: {rel}")


def read_text_capped(p: Path, *, limit: int = MAX_READ_BYTES) -> str:
    """Lê texto com TETO de tamanho (evita OOM ao ler um arquivo gigante para o prompt)."""
    size = p.stat().st_size
    if size > limit:
        raise FileTooLarge(
            f"arquivo grande demais ({size:,} bytes > {limit:,}); use run_shell (head/sed/grep) p/ fatiar"
        )
    return p.read_text(encoding="utf-8")


def write_text_atomic(p: Path, content: str, *, limit: int = MAX_WRITE_BYTES) -> int:
    """Escreve ATOMICAMENTE (tmp no mesmo dir + os.replace) com TETO de tamanho.

    Sem janela de arquivo corrompido se cair no meio; sem CRLF dependente de SO (escreve bytes)."""
    data = content.encode("utf-8")
    if len(data) > limit:
        raise FileTooLarge(f"conteúdo grande demais ({len(data):,} bytes > {limit:,})")
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=f".{p.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, p)   # atômico no mesmo filesystem
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return len(content)
