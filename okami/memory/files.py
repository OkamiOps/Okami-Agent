"""Camada de arquivos da memória (sempre on): identidade + core .md.

Tier "core" (estilo Hermes): o que é frequente/durável fica nos .md e é SEMPRE injetado no
prompt — o agente não precisa consultar a memória (tier "archival") toda hora. Limite por
arquivo em chars (default 4000; maiores que os do Hermes). Ordem de injeção (PromptBuilder §8):
- IDENTIDADE (evolui só pelo learning loop §6/§8, protegida de drift):
  SOUL.md (valores) → VOICE.md (tom) → PERSONA.md/PROFILE.md (self-model).
- CORE: AGENTS.md (projeto) → USER.md (modelo do usuário) → MEMORY.md (fatos).
O agente ATUALIZA USER.md (remember_user) e MEMORY.md (remember/extract) → evolui com o tempo.
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_CAP = 4000
_FACTS_HEADER = "## Fatos"

# (nomes-de-arquivo[fallbacks], chave-de-limite, rótulo, default_cap) — ORDEM = ordem de injeção.
_LAYERS = [
    (["SOUL.md"], "soul", "IDENTIDADE / VALORES (SOUL.md)", 6000),
    (["VOICE.md"], "voice", "VOZ / TOM (VOICE.md)", 6000),
    (["PERSONA.md", "PROFILE.md"], "persona", "PERSONA / SELF (PERSONA.md)", 6000),
    # auto-descobre convenções do projeto (estilo Hermes/Claude Code): 1º que existir.
    (["AGENTS.md", "CLAUDE.md", ".cursorrules", ".hermes.md"], "agents", "INSTRUÇÕES DO PROJETO", 4000),
    (["USER.md"], "user", "SOBRE O USUÁRIO (USER.md)", 4000),
    (["MEMORY.md"], "memory", "MEMÓRIA DURÁVEL (MEMORY.md)", 4000),
]


def _path(workspace: Path, name: str) -> Path:
    return Path(workspace) / name


def read_capped(workspace: Path, name: str, cap: int = DEFAULT_CAP) -> str:
    p = _path(workspace, name)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8", errors="ignore")[:cap]


def _read_first(workspace: Path, names: list[str], cap: int) -> str:
    for n in names:
        txt = read_capped(workspace, n, cap)
        if txt:
            return txt
    return ""


def core_block(workspace: Path, limits: dict | None = None) -> str:
    """Bloco SEMPRE injetado: identidade (SOUL/VOICE/PERSONA) + core (AGENTS/USER/MEMORY)."""
    limits = limits or {}
    parts = []
    for names, key, label, default_cap in _LAYERS:
        cap = int(limits.get(key, default_cap))
        txt = _read_first(workspace, names, cap).strip()
        if txt:
            parts.append(f"### {label}\n{txt}")
    return "\n\n".join(parts)


def memory_md(workspace: Path) -> Path:
    return _path(workspace, "MEMORY.md")


def read_memory_md(workspace: Path, cap: int = DEFAULT_CAP) -> str:
    return read_capped(workspace, "MEMORY.md", cap)


def _append_bullet(workspace: Path, name: str, text: str, title: str, header: str) -> bool:
    from okami.core.redact import looks_secret
    if looks_secret(text):                           # P1: USER.md/MEMORY.md vão SEMPRE pro prompt → sem segredo
        from okami import log
        log.warn(f"memory: recusei escrever conteúdo com cara de segredo em {name}.")
        return False
    p = _path(workspace, name)
    line = f"- {text.strip()}"
    if not p.exists():
        p.write_text(f"# {title}\n\n{header}\n{line}\n", encoding="utf-8", newline="\n")
        return True
    content = p.read_text(encoding="utf-8", errors="ignore")
    if line in content:  # dedup simples
        return True
    if header not in content:
        content += f"\n{header}\n"
    p.write_text(content.rstrip() + f"\n{line}\n", encoding="utf-8", newline="\n")
    return True


def append_fact(workspace: Path, text: str) -> bool:
    return _append_bullet(workspace, "MEMORY.md", text, "MEMORY", _FACTS_HEADER)


def append_user(workspace: Path, text: str) -> bool:
    return _append_bullet(workspace, "USER.md", text, "USER", "## Sobre o usuário")
