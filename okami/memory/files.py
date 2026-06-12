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


def _read_first(workspace: Path, names: list[str], cap: int) -> tuple[str, str]:
    """(nome_do_arquivo_lido, texto) — o 1º dos `names` que existir; ('', '') se nenhum."""
    for n in names:
        txt = read_capped(workspace, n, cap)
        if txt:
            return n, txt
    return "", ""


def sanitize_for_prompt(name: str, text: str) -> str:
    """Neutraliza injeção que JÁ está em disco antes de injetar no prompt (pesquisa #6 item 8).

    Cada linha com finding HIGH+ do scanner de skills (`ignore previous instructions`, exfil,
    stealth, RCE…) vira `[BLOCKED: <regra> …]` — o usuário ainda vê que havia algo e pode remover,
    mas a instrução envenenada não chega ao modelo. Defende poisoning de arquivo (edição por fora,
    skill/sessão hostil) que a recusa no WRITE não pega."""
    if not text:
        return text
    from okami.skills.skill_security import Severity, scan_text
    bad = {f.line: f for f in scan_text(name, text) if f.severity >= Severity.HIGH and f.line > 0}
    if not bad:
        return text
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        if i in bad:
            out.append(f"[BLOCKED: {bad[i].rule} — conteúdo de {name} neutralizado por segurança; "
                       "remova essa linha do arquivo se foi você quem escreveu]")
        else:
            out.append(line)
    return "\n".join(out)


def core_block(workspace: Path, limits: dict | None = None) -> str:
    """Bloco SEMPRE injetado: identidade (SOUL/VOICE/PERSONA) + core (AGENTS/USER/MEMORY).

    Cada camada passa pelo scan de injeção no LOAD (item 8): linha envenenada em disco → [BLOCKED:…]."""
    limits = limits or {}
    parts = []
    for names, key, label, default_cap in _LAYERS:
        cap = int(limits.get(key, default_cap))
        name, txt = _read_first(workspace, names, cap)
        txt = sanitize_for_prompt(name, txt).strip()
        if txt:
            parts.append(f"### {label}\n{txt}")
    return "\n\n".join(parts)


def memory_md(workspace: Path) -> Path:
    return _path(workspace, "MEMORY.md")


def read_memory_md(workspace: Path, cap: int = DEFAULT_CAP) -> str:
    return read_capped(workspace, "MEMORY.md", cap)


def _sha(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()


def _drift_guard(workspace: Path, name: str, content: str) -> None:
    """Drift externo (pesquisa #6 item 9): se o arquivo mudou desde a ÚLTIMA escrita NOSSA (patch/
    shell/manual/sessão concorrente o editaram), tira um .bak ANTES de tocar — recuperável, sem
    recusar (o append é aditivo, não clobbera). Sidecar de hash em .okami/memory_state.json."""
    import json
    state_p = Path(workspace) / ".okami" / "memory_state.json"
    try:
        state = json.loads(state_p.read_text(encoding="utf-8")) if state_p.exists() else {}
    except (OSError, ValueError):
        state = {}
    last = state.get(name)
    if last and last != _sha(content):                   # editado por fora desde nossa última escrita
        try:
            import time
            bak_dir = Path(workspace) / ".okami" / "memory_bak"
            bak_dir.mkdir(parents=True, exist_ok=True)
            (bak_dir / f"{name}.{int(time.time() * 1000)}.bak").write_text(content, encoding="utf-8")
            for old in sorted(bak_dir.glob(f"{name}.*.bak"))[:-5]:   # mantém 5 mais recentes
                old.unlink(missing_ok=True)
            from okami import log
            log.warn(f"memory: {name} foi editado por fora — .bak salvo antes de anexar.")
        except OSError:
            pass


def _record_hash(workspace: Path, name: str, content: str) -> None:
    import json
    state_p = Path(workspace) / ".okami" / "memory_state.json"
    try:
        state = json.loads(state_p.read_text(encoding="utf-8")) if state_p.exists() else {}
    except (OSError, ValueError):
        state = {}
    state[name] = _sha(content)
    try:
        state_p.parent.mkdir(parents=True, exist_ok=True)
        state_p.write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        pass


def _append_bullet(workspace: Path, name: str, text: str, title: str, header: str) -> bool:
    from okami.core.redact import looks_secret
    if looks_secret(text):                           # P1: USER.md/MEMORY.md vão SEMPRE pro prompt → sem segredo
        from okami import log
        log.warn(f"memory: recusei escrever conteúdo com cara de segredo em {name}.")
        return False
    # WRITE side do item 8: padrão de injeção (ignore instructions/exfil/stealth/RCE) → recusa.
    from okami.skills.skill_security import Severity, scan_text
    inj = [f for f in scan_text(name, text) if f.severity >= Severity.HIGH]
    if inj:
        from okami import log
        log.warn(f"memory: recusei escrever em {name} — padrão de injeção ({inj[0].rule}).")
        return False
    p = _path(workspace, name)
    line = f"- {text.strip()}"
    if not p.exists():
        new = f"# {title}\n\n{header}\n{line}\n"
        p.write_text(new, encoding="utf-8", newline="\n")
        _record_hash(workspace, name, new)
        return True
    content = p.read_text(encoding="utf-8", errors="ignore")
    _drift_guard(workspace, name, content)           # editado por fora desde nossa última escrita → .bak
    if line in content:  # dedup simples
        _record_hash(workspace, name, content)       # re-sincroniza o hash mesmo sem mudança
        return True
    if header not in content:
        content += f"\n{header}\n"
    new = content.rstrip() + f"\n{line}\n"
    p.write_text(new, encoding="utf-8", newline="\n")
    _record_hash(workspace, name, new)
    return True


def append_fact(workspace: Path, text: str) -> bool:
    return _append_bullet(workspace, "MEMORY.md", text, "MEMORY", _FACTS_HEADER)


def append_user(workspace: Path, text: str) -> bool:
    return _append_bullet(workspace, "USER.md", text, "USER", "## Sobre o usuário")
