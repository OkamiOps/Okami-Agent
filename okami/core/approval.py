"""Go/No-Go — aprovação de ações sensíveis (§12), no estilo Hermes.

O agente PODE modificar qualquer arquivo quando solicitado; ações sensíveis param e pedem
go/no-go. Modelo de aprovação:
- Modos: `manual` (pede sempre), `smart` (auto-aprova risco baixo, pergunta o resto),
  `off` (sem prompts), e `yolo` (bypass na sessão — flag/`/yolo`).
- 4 opções no prompt: allow once · allow session · always allow (persiste) · deny.
- Sem responder/sem prompt disponível = **fail-closed** (nega) — importante via Telegram.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

# (regex, categoria, risco) por tipo de ação.
_FILE_RULES = [
    (re.compile(r"(^|/)(SOUL|VOICE|PERSONA|PROFILE)\.md$", re.I), "identity_file", "high"),
    (re.compile(r"(^|/)\.env(\.|$)", re.I), "env_file", "high"),
    (re.compile(r"secret|credential|password|/\.okami/credentials|\.codex/auth|\.claude/\.credentials", re.I), "secret_file", "high"),
    (re.compile(r"\.(key|pem|p12|pfx)$", re.I), "secret_file", "high"),
]
_SHELL_RULES = [
    (re.compile(r"\brm\s+-[rf]|\bmkfs\b|dd\s+if=\S+\s+of=/dev/", re.I), "destructive_shell", "critical"),
    (re.compile(r"\bsudo\b", re.I), "sudo", "high"),
    (re.compile(r"\bgit\s+push\b", re.I), "git_push", "medium"),
    (re.compile(r"\b(npm|pip|cargo)\s+publish\b", re.I), "publish", "high"),
    (re.compile(r"\bcurl\b[^\n]*-X\s*(POST|PUT|DELETE)|\bwget\b[^\n]*--post", re.I), "network_write", "medium"),
    (re.compile(r"\bchmod\b|\bdocker\s+(rm|rmi|system\s+prune)", re.I), "system_change", "medium"),
]


@dataclass
class Sensitive:
    reason: str
    category: str
    risk: str  # low | medium | high | critical


def classify(tool: str, args: dict) -> Sensitive | None:
    """None se não-sensível; senão (razão, categoria, risco)."""
    if tool in ("write_file", "edit_file"):              # edit_file também escreve → mesma trava
        path = str(args.get("path", "")).replace("\\", "/")
        for rx, cat, risk in _FILE_RULES:
            if rx.search(path):
                return Sensitive(f"escrever em {cat}: {path}", cat, risk)
    if tool == "run_shell":
        cmd = str(args.get("cmd", ""))
        for rx, cat, risk in _SHELL_RULES:
            if rx.search(cmd):
                return Sensitive(f"{cat}: {cmd[:100]}", cat, risk)
    return None


def requires_approval(tool: str, args: dict, workspace=None) -> str | None:
    s = classify(tool, args)
    return s.reason if s else None


# prompt_fn(request) -> "once" | "session" | "always" | "deny"
PromptFn = Callable[[dict], str]


class Approver:
    """Decide go/no-go com modos + memória de sessão + allowlist persistente."""

    def __init__(self, mode: str = "manual", session_allow=None, persistent_allow=None,
                 prompt: PromptFn | None = None, on_persist: Callable[[str], None] | None = None):
        self.mode = mode
        self.session_allow: set[str] = set(session_allow or [])
        self.persistent_allow: set[str] = set(persistent_allow or [])
        self.prompt = prompt
        self.on_persist = on_persist

    def __call__(self, request: dict) -> bool:
        cat = request.get("category", "")
        risk = request.get("risk", "high")
        if self.mode == "yolo":            # YOLO = explícito → autoaprova TUDO na sessão
            return True
        if cat and (cat in self.session_allow or cat in self.persistent_allow):
            return True
        if self.mode == "smart" and risk == "low":
            return True
        # "off" = SEM prompt ≠ "permita tudo": sem prompt p/ ação sensível → NEGA (fail-closed).
        # (Antes off≡yolo: alguém desligava interação achando que silenciava, mas liberava o perigoso.)
        if self.mode == "off" or self.prompt is None:
            return False
        decision = self.prompt(request)
        if decision == "session":
            self.session_allow.add(cat)
            return True
        if decision == "always":
            self.session_allow.add(cat)
            if self.on_persist:
                self.on_persist(cat)
            return True
        return decision == "once"
