"""Tools do harness (Fase 1).

Tools nativas (read/write/list/shell) + tools terminais (complete/blocked/need_input).
A `ToolContext` carrega o workspace e o conjunto de arquivos lidos — base do grounding
anti-alucinação (§3.7): não se sobrescreve um arquivo existente que não foi lido.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

# Variáveis de ambiente sensíveis são REMOVIDAS dos subprocessos do agente (run_shell,
# shell_ok), para que prompt injection / código gerado não consiga exfiltrar credenciais
# (padrão do Hermes). Estamos protegendo chaves de provider, tokens OAuth, AWS, etc.
_SENSITIVE_ENV = re.compile(
    r"(API[_-]?KEY|ACCESS[_-]?KEY|SECRET|PASSWORD|PASSWD|TOKEN|CREDENTIAL|PRIVATE[_-]?KEY"
    r"|AUTH|SESSION|COOKIE|_PAT$)",   # +AUTH/SESSION/COOKIE (igual ao _SECRET_ENV_NAMES do Hermes)
    re.IGNORECASE,
)


def sanitized_env() -> dict[str, str]:
    """Cópia do ambiente sem variáveis sensíveis (chaves/segredos/tokens)."""
    return {k: v for k, v in os.environ.items() if not _SENSITIVE_ENV.search(k)}


# #2 do self-review do Okami: shell read-only NÃO conta como progresso (não engana o watchdog §3.3).
_SHELL_MUTATES = re.compile(
    r"\b(rm|rmdir|mv|cp|mkdir|touch|ln|dd|chmod|chown|tee|truncate|install|make|cmake|npm|pnpm|yarn|"
    r"pip|pip3|uv|cargo|go|gradle|mvn|docker|kubectl|terraform|apt|brew|systemctl|kill|pkill)\b"
    r"|>>?|sed\s+-i|git\s+(commit|push|add|merge|rebase|reset|checkout|clean|stash|tag|init|rm|mv|apply)",
    re.IGNORECASE,
)
_SHELL_READONLY = {"ls", "find", "grep", "rg", "cat", "head", "tail", "pwd", "echo", "which", "wc",
                   "file", "stat", "tree", "awk", "du", "df", "ps", "env", "printenv", "date",
                   "whoami", "uname", "hostname", "sort", "uniq", "cut", "diff", "sed"}


# Política de leitura sensível (P0.1): o shell NÃO confina o FS de verdade (cwd=workspace, mas
# `cat ~/.ssh/id_rsa` escapa via expansão). Bloqueia comando que toca segredo conhecido — defesa em
# profundidade (yolo/docker liberam). Não é à prova de ofuscação, mas mata o `cat .env`/exfil óbvio.
_SENSITIVE_PATH = re.compile(
    r"\.env\b|\.okami/credentials|\.codex/auth|[/~.]ssh\b|[/~.]aws\b|\.gnupg|id_rsa|id_ed25519|"
    r"\.pem\b|\.key\b|/etc/(passwd|shadow)|credentials\.json|\.netrc|\.npmrc|\.pypirc|"
    r"secrets?\.(env|json|ya?ml)",
    re.IGNORECASE,
)


def shell_has_effect(cmd: str) -> bool:
    """True se o comando MUTA estado (= progresso real); False se for só leitura/inspeção."""
    if _SHELL_MUTATES.search(cmd):
        return True
    for part in re.split(r"[|&;]+", cmd):              # cada subcomando (pipe/and/seq)
        tok = part.strip().split()
        if not tok:
            continue
        head = tok[0].lstrip("(").lower()
        if head == "git" and len(tok) > 1 and tok[1] in (
                "status", "log", "diff", "show", "branch", "ls-files", "rev-parse", "blame"):
            continue
        if head in _SHELL_READONLY:
            continue
        return True                                    # comando desconhecido → assume efeito (conservador)
    return False


@dataclass
class ToolContext:
    workspace: Path
    read_files: set[str] = field(default_factory=set)
    memory: object | None = None  # backend de memória (duck-typed: write/recall)
    skills: dict = field(default_factory=dict)  # nome -> corpo da SKILL.md (progressive disclosure)
    checkpoints: object | None = None  # snapshot antes de escrever → rollback (duck-typed: snapshot)
    spawn: object | None = None  # delega um subtask a um subagente isolado (Callable(goal, agent, model)->str)
    sandbox: object | None = None  # SandboxPolicy do run_shell (None → default_policy()); §P0 #2
    skills_dir: object | None = None  # raiz das skills (p/ manage_skill criar/editar) — review/genesis


@dataclass
class ToolResult:
    ok: bool
    output: str
    effect: bool = False  # houve efeito colateral observável? (alimenta o watchdog §3.3)


class Tool:
    name: str = ""
    description: str = ""
    args_schema: dict[str, str] = {}
    required: tuple[str, ...] = ()   # args obrigatórios (validados pelo harness antes de rodar)
    terminal: bool = False

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:  # pragma: no cover
        raise NotImplementedError

    def to_openai_schema(self) -> dict:
        """Schema function-calling (OpenAI) desta tool — p/ tool-calls NATIVO (§3.5). O protocolo
        JSON-em-texto continua de pé; isto é a forma nativa equivalente, mesma `name`/args."""
        props = {k: {"type": "string", "description": v} for k, v in (self.args_schema or {}).items()}
        return {"type": "function", "function": {
            "name": self.name, "description": self.description,
            "parameters": {"type": "object", "properties": props, "required": list(self.required)}}}


def openai_tools(registry: dict) -> list[dict]:
    """Schemas OpenAI das tools (p/ enviar no payload quando o provider faz function-calling nativo)."""
    return [t.to_openai_schema() for t in registry.values()]


def _safe_path(ctx: ToolContext, rel: str) -> Path:
    """Jail de workspace + bloqueio de symlink-escape (centralizado em core.file_safety)."""
    from okami.core.file_safety import safe_path
    return safe_path(ctx.workspace, rel)  # PathEscape é ValueError → callers `except ValueError` seguem
