"""git-context (plugin builtin) — register(ctx): contribui um provedor de contexto por-turno
(ctx.register_context, pre_llm_call) com o estado atual do repo git do workspace. Port de um padrão
comum nos plugins de "project awareness" do Hermes, adaptado ao sistema unificado do Okami.

Fail-safe por natureza: fora de repo git, `git` ausente do PATH, ou qualquer erro de subprocess →
provider devolve "" (o gateway simplesmente não injeta nada — nunca derruba o turno, nunca polui o
contexto com ruído). UMA chamada de subprocess por turno (`git status --porcelain=v2 --branch`), sem
rede, sem escrita — barato o bastante p/ rodar em todo turno.
"""
from __future__ import annotations

import os
import subprocess

_MAX_FILES_DEFAULT = 6


def _run_git_status(cwd: str) -> str:
    """`git status --porcelain=v2 --branch` num único subprocess — traz branch + upstream + ahead/behind
    + arquivos sujos numa chamada só. Timeout curto (é injetado em TODO turno; nunca pode travar o
    gateway). Devolve "" em qualquer falha (não é repo git, git ausente, timeout, etc)."""
    try:
        r = subprocess.run(  # nosec B603 B607 — comando fixo do plugin (sem input do modelo/rede)
            ["git", "status", "--porcelain=v2", "--branch"],
            cwd=cwd, capture_output=True, text=True, timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if r.returncode != 0:
        return ""
    return r.stdout or ""


def _parse_status(raw: str, *, max_files: int) -> str:
    """Monta a linha de contexto a partir do stdout do `git status --porcelain=v2 --branch`. Formato v2:
    linhas `# branch.head <nome>`, `# branch.upstream <remoto>`, `# branch.ab +N -M`, e uma linha por
    arquivo sujo (código `1`/`2`/`u`/`?` + caminho no fim)."""
    branch = ""
    upstream = ""
    ahead = behind = 0
    files: list[str] = []
    for line in raw.splitlines():
        if line.startswith("# branch.head "):
            branch = line.split(" ", 2)[2]
        elif line.startswith("# branch.upstream "):
            upstream = line.split(" ", 2)[2]
        elif line.startswith("# branch.ab "):
            parts = line.split()   # ["#", "branch.ab", "+N", "-M"]
            try:
                ahead = int(parts[2].lstrip("+"))
                behind = int(parts[3].lstrip("-"))
            except (IndexError, ValueError):
                pass
        elif line and not line.startswith("#"):
            path = line.split("\t")[-1].split(" ")[-1]
            if path:
                files.append(path)
    if not branch:
        return ""                                    # sem branch.head → status não veio no formato esperado
    if branch == "(detached)":
        head = "HEAD destacado"
    else:
        head = f"branch {branch}"
    bits = [f"[git] {head}"]
    if upstream:
        ab = []
        if ahead:
            ab.append(f"+{ahead}")
        if behind:
            ab.append(f"-{behind}")
        bits.append(f"(upstream {upstream}{' ' + '/'.join(ab) if ab else ''})")
    if files:
        shown = files[:max_files]
        extra = len(files) - len(shown)
        listed = ", ".join(shown) + (f", +{extra} mais" if extra > 0 else "")
        bits.append(f"— {len(files)} arquivo(s) sujo(s): {listed}")
    else:
        bits.append("— árvore limpa")
    return " ".join(bits)


def _max_files() -> int:
    try:
        return max(1, int(os.environ.get("OKAMI_GITCONTEXT_MAX_FILES", "") or _MAX_FILES_DEFAULT))
    except ValueError:
        return _MAX_FILES_DEFAULT


def git_context_provider() -> str:
    """Provider chamado pelo gateway a cada turno (`ctx.register_context`). Lê o cwd NO MOMENTO da
    chamada (não no boot do plugin) — segue o workspace se o processo mudar de diretório."""
    if os.environ.get("OKAMI_GITCONTEXT_DISABLE"):
        return ""
    raw = _run_git_status(os.getcwd())
    if not raw:
        return ""
    return _parse_status(raw, max_files=_max_files())


def register(ctx) -> None:
    ctx.register_context(git_context_provider, name="git-context")
