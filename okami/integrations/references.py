"""Referências @ (estilo Hermes/Claude Code) — injeta arquivos/URLs/git-diff na mensagem.

Sintaxe suportada:
  `@caminho`                → (legado) conteúdo do arquivo/pasta, ou URL se `http(s)://`
  `@file:caminho`           → conteúdo do arquivo
  `@file:caminho:L1-L2`     → só as linhas L1..L2 do arquivo
  `@folder:caminho`         → conteúdo concatenado dos arquivos da pasta (raso, sem recursão)
  `@diff`                   → `git diff` (working tree)
  `@staged`                 → `git diff --cached`
  `@git:N`                  → `git log` das últimas N commits (oneline)
  `@https://…`              → conteúdo da URL (anti-SSRF via net_guard)

O texto original é preservado (o modelo vê os marcadores); o conteúdo expandido vai num bloco
anexo. Resolve só o que existir/casar (refs que não batem são ignoradas — inócuo).

Segurança (FIX 1): qualquer caminho que bata no deny-list de credenciais do harness
(`okami.core.tools.base._SENSITIVE_PATH` — .env, ~/.ssh, id_rsa, credentials.json, etc.) é
RECUSADO e vira um placeholder "[credencial bloqueada: X]" — o conteúdo nunca entra no contexto.
Mirror do `_ensure_reference_path_allowed` do Hermes.

Budget (FIX 2): o bloco de referências tem um teto de caracteres (mirror do guard 25%/50% do
Hermes em `context_references.py:179-198`) — uma `@folder` gigante é truncada, não estoura o
contexto silenciosamente.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from okami.core.tools.base import _SENSITIVE_PATH

_REF_RE = re.compile(
    r"@(?:"
    r"(?P<simple>diff|staged)\b"
    r"|(?P<kind>file|folder):(?P<value>[\w./\-~]+)(?::(?P<l1>\d+)-(?P<l2>\d+))?"
    r"|git:(?P<n>\d+)"
    r"|(?P<legacy>[\w./:\-~]+)"
    r")"
)

_MAX = 8000                              # cap por referência individual (chars)
_BUDGET_TOTAL = 24000                    # "limite razoável" de contexto p/ o bloco de referências (chars)
_BUDGET_SOFT = int(_BUDGET_TOTAL * 0.25)  # aviso
_BUDGET_HARD = int(_BUDGET_TOTAL * 0.50)  # corte


def _is_blocked(p: Path) -> bool:
    return bool(_SENSITIVE_PATH.search(str(p)))


def _git_diff(ws: Path, *, staged: bool = False) -> str:
    cmd = ["git", "diff"] + (["--cached"] if staged else [])
    try:
        r = subprocess.run(cmd, cwd=str(ws), capture_output=True, text=True, timeout=10)
        return r.stdout[:_MAX] or "(sem diff)"
    except Exception:  # noqa: BLE001
        return ""


def _git_log(ws: Path, n: int) -> str:
    try:
        r = subprocess.run(["git", "log", f"-{max(1, n)}", "--oneline"], cwd=str(ws),
                            capture_output=True, text=True, timeout=10)
        return r.stdout[:_MAX] or "(sem histórico)"
    except Exception:  # noqa: BLE001
        return ""


def _fetch_url(url: str) -> str:
    from okami.core.net_guard import BlockedURL, guarded_urlopen
    try:
        with guarded_urlopen(url, timeout=15) as r:     # anti-SSRF antes de buscar
            return r.read(_MAX).decode("utf-8", "ignore")
    except BlockedURL as e:
        return f"(URL recusada: {e})"                    # o modelo vê o motivo, não um silêncio
    except Exception:  # noqa: BLE001
        return ""


def _read_path(p: Path, l1: int | None, l2: int | None) -> str:
    if p.is_file():
        text = p.read_text(encoding="utf-8", errors="ignore")
        if l1 is not None:
            lines = text.splitlines()
            lo = max(1, l1)
            hi = l2 if l2 is not None else lo
            return "\n".join(lines[lo - 1:hi])[:_MAX]
        return text[:_MAX]
    if p.is_dir():
        parts = []
        for c in sorted(p.iterdir()):
            if not c.is_file():
                continue
            try:
                parts.append(f"--- {c.name} ---\n" + c.read_text(encoding="utf-8", errors="ignore")[:_MAX])
            except Exception:  # noqa: BLE001
                continue
        if parts:
            return "\n\n".join(parts)   # cada arquivo já capado em _MAX; o corte final é o budget guard
        return "\n".join(sorted(c.name for c in p.iterdir()))[:2000]
    return ""


def _resolve_fs(value: str, ws: Path, l1: int | None = None, l2: int | None = None) -> str:
    """Resolve um caminho (relativo ao workspace OU absoluto/~) — deny-list de credencial tem
    prioridade sobre o escape-check (um `@file:~/.ssh/id_rsa` é barrado, mesmo fora do workspace)."""
    raw = Path(os.path.expanduser(value))
    p = raw if raw.is_absolute() else (ws / raw)
    p = p.resolve()
    if _is_blocked(p):
        return f"[credencial bloqueada: {value}]"
    if ws.resolve() not in p.parents and p != ws.resolve():   # não escapa do workspace
        return ""
    return _read_path(p, l1, l2)


def _resolve_legacy(ref: str, ws: Path) -> str:
    if ref in ("gitdiff", "git-diff", "diff"):
        return _git_diff(ws)
    if ref == "staged":
        return _git_diff(ws, staged=True)
    if ref.startswith(("http://", "https://")):
        return _fetch_url(ref)
    return _resolve_fs(ref, ws)


def expand_references(text: str, workspace) -> tuple[str, str]:
    """Devolve (texto_original, bloco_de_referências). Bloco vazio se nada casou."""
    ws = Path(workspace)
    blocks, seen = [], set()
    total = 0
    truncated = False

    for m in _REF_RE.finditer(text or ""):
        key = m.group(0).rstrip(".,;:)")
        if key in seen:
            continue
        seen.add(key)

        if m.group("simple") == "diff":
            label, content = "diff", _git_diff(ws)
        elif m.group("simple") == "staged":
            label, content = "staged", _git_diff(ws, staged=True)
        elif m.group("kind"):
            value = (m.group("value") or "").rstrip(".,;:)")
            l1 = int(m.group("l1")) if m.group("l1") else None
            l2 = int(m.group("l2")) if m.group("l2") else None
            kind = m.group("kind")
            label = f"{kind}:{value}" + (f":{l1}-{l2}" if l1 is not None else "")
            content = _resolve_fs(value, ws, l1, l2)
        elif m.group("n") is not None:
            n = int(m.group("n"))
            label, content = f"git:{n}", _git_log(ws, n)
        else:
            legacy = (m.group("legacy") or "").rstrip(".,;:)")
            if not legacy:
                continue
            label, content = legacy, _resolve_legacy(legacy, ws)

        if not content:
            continue

        if content.startswith("[credencial bloqueada"):
            blocks.append(f"### @{label}\n{content}")
            continue

        remaining = _BUDGET_HARD - total
        if remaining <= 0:
            truncated = True
            continue
        if len(content) > remaining:
            content = content[:remaining] + "\n…(truncado — limite de contexto das referências)"
            truncated = True
        total += len(content)
        blocks.append(f"### @{label}\n{content}")

    if not blocks:
        return text, ""

    header = "REFERÊNCIAS (@) anexadas pelo usuário:"
    if truncated:
        header += f"\n(aviso: bloco de referências excedeu o limite ({_BUDGET_HARD} chars) — TRUNCADO)"
    elif total > _BUDGET_SOFT:
        header += f"\n(aviso: bloco de referências grande — {total} chars)"
    block = header + "\n" + "\n\n".join(blocks)
    return text, block
