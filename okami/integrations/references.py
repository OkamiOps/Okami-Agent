"""Referências @ (estilo Hermes/Claude Code) — injeta arquivos/URLs/git-diff na mensagem.

`@caminho` → conteúdo do arquivo; `@pasta/` → listagem; `@gitdiff` → diff atual; `@https://…` →
conteúdo da URL. O texto original é preservado (o modelo vê os marcadores); o conteúdo expandido
vai num bloco anexo. Resolve só o que existir/casar (refs que não batem são ignoradas — inócuo).
"""

from __future__ import annotations

import re
import subprocess
import urllib.request
from pathlib import Path

_REF_RE = re.compile(r"@([\w./:\-~]+)")
_MAX = 8000


def _git_diff(ws: Path) -> str:
    try:
        r = subprocess.run(["git", "diff"], cwd=str(ws), capture_output=True, text=True, timeout=10)
        return r.stdout[:_MAX] or "(sem diff)"
    except Exception:  # noqa: BLE001
        return ""


def _fetch_url(url: str) -> str:
    try:
        with urllib.request.urlopen(url, timeout=15) as r:  # noqa: S310
            return r.read(_MAX).decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return ""


def _resolve(ref: str, ws: Path) -> str:
    if ref in ("gitdiff", "git-diff", "diff"):
        return _git_diff(ws)
    if ref.startswith(("http://", "https://")):
        return _fetch_url(ref)
    p = (ws / ref).resolve()
    if ws.resolve() not in p.parents and p != ws.resolve():    # não escapa do workspace
        return ""
    if p.is_file():
        return p.read_text(encoding="utf-8", errors="ignore")[:_MAX]
    if p.is_dir():
        return "\n".join(sorted(c.name for c in p.iterdir()))[:2000]
    return ""


def expand_references(text: str, workspace) -> tuple[str, str]:
    """Devolve (texto_original, bloco_de_referências). Bloco vazio se nada casou."""
    ws = Path(workspace)
    blocks, seen = [], set()
    for ref in _REF_RE.findall(text or ""):
        ref = ref.rstrip(".,;:)")
        if ref in seen:
            continue
        seen.add(ref)
        content = _resolve(ref, ws)
        if content:
            blocks.append(f"### @{ref}\n{content}")
    block = "REFERÊNCIAS (@) anexadas pelo usuário:\n" + "\n\n".join(blocks) if blocks else ""
    return text, block
