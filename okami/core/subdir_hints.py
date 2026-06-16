"""Subdirectory hints (#8 item 7) — convenções de SUBPASTA descobertas ao navegar.

Quando o agente lê/navega numa subpasta do workspace (ex.: `packages/x/`), descobrimos o arquivo de
convenção daquela pasta (AGENTS.md / CLAUDE.md / .cursorrules / .hermes.md) e o injetamos no RESULTADO
da tool — NÃO no system prompt. Isso (a) preserva o prompt cache (o system prompt não muda) e (b) faz
o agente ver, just-in-time, a regra local que o `core_block` (que carrega só a RAIZ) nunca veria num
monorepo. Walk-up da pasta acessada até a RAIZ do workspace (exclusive — a raiz já está no core_block),
dedup por pasta via um `seen` set (uma vez por turno), cap por arquivo.
"""
from __future__ import annotations

from pathlib import Path

# mesma ordem de precedência do core_block (memory/files.py): o 1º que existir por pasta.
_HINT_FILES = ("AGENTS.md", "CLAUDE.md", ".cursorrules", ".hermes.md")
_CAP = 8000


def subdir_hint(workspace, accessed, seen: set[str]) -> str:
    """Bloco de convenção das subpastas no caminho de `accessed`, ou "" se não houver nada novo.

    `seen` é mutado: cada pasta já anunciada entra no set p/ não repetir no mesmo turno."""
    try:
        ws = Path(workspace).resolve()
        target = Path(accessed).resolve()
    except (OSError, ValueError, RuntimeError):
        return ""
    d = target if target.is_dir() else target.parent
    try:
        d.relative_to(ws)                              # tem que estar DENTRO do workspace
    except ValueError:
        return ""
    parts = []
    cur = d
    while cur != ws and ws in cur.parents:             # sobe até a raiz (exclusive)
        key = str(cur)
        if key not in seen:
            seen.add(key)
            block = _read_convention(cur, ws)
            if block:
                parts.append(block)
        cur = cur.parent
    if not parts:
        return ""
    return ("\n\n--- CONVENÇÕES DO PROJETO (da subpasta que você acessou — trate como instrução do "
            "projeto p/ arquivos dessa pasta) ---\n" + "\n\n".join(parts))


def _read_convention(folder: Path, ws: Path) -> str:
    """Primeiro arquivo de convenção existente em `folder`, rotulado pelo caminho relativo, capado."""
    for fn in _HINT_FILES:
        f = folder / fn
        if f.is_file():
            try:
                txt = f.read_text(encoding="utf-8", errors="ignore")[:_CAP].strip()
            except OSError:
                return ""
            if txt:
                rel = folder.relative_to(ws).as_posix()
                # #11: arquivo de convenção de um repo clonado pode carregar injeção/promptware. Escaneia
                # ANTES de injetar no resultado da tool (o agente trata isto como instrução do projeto).
                from okami.core.threat_patterns import scan_for_threats
                threats = scan_for_threats(txt, scope="context")
                if threats:
                    return (f"[BLOCKED: {rel}/{fn} contém possível injeção de prompt "
                            f"({', '.join(threats[:3])}). Conteúdo não carregado.]")
                return f"[convenção de {rel}/{fn}]\n{txt}"
            return ""
    return ""
