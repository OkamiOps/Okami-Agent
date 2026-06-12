"""Go/No-Go — aprovação de ações sensíveis (§12), no estilo Hermes.

O agente PODE modificar qualquer arquivo quando solicitado; ações sensíveis param e pedem
go/no-go. Modelo de aprovação:
- Modos: `manual` (pede sempre), `smart` (auto-aprova risco baixo, pergunta o resto),
  `off` (sem prompts), e `yolo` (bypass na sessão — flag/`/yolo`).
- 4 opções no prompt: allow once · allow session · always allow (persiste) · deny.
- Sem responder/sem prompt disponível = **fail-closed** (nega) — importante via Telegram.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Callable


def args_hash(args: dict) -> str:
    """Hash canônico dos ARGS de uma ação — amarra a aprovação aos args EXATOS (#1/#7/#9).

    Mesma canonicalização no harness (pede) e no ApprovalStore (consome): muda 1 byte do arg →
    hash diferente → a aprovação daquela ação não vale p/ outra."""
    return hashlib.sha256(
        json.dumps(args or {}, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()[:16]

# (regex, categoria, risco) por tipo de ação.
_FILE_RULES = [
    (re.compile(r"(^|/)(SOUL|VOICE|PERSONA|PROFILE)\.md$", re.I), "identity_file", "high"),
    (re.compile(r"(^|/)\.env(\.|$)", re.I), "env_file", "high"),
    (re.compile(r"secret|credential|password|/\.okami/credentials|\.codex/auth|\.claude/\.credentials", re.I), "secret_file", "high"),
    (re.compile(r"\.(key|pem|p12|pfx)$", re.I), "secret_file", "high"),
]
# Posição de COMANDO (Hermes tools/approval.py _CMDPOS): início da string, ou depois de um separador
# (; && || | newline ` $( ). Ancorar o nome do comando perigoso AQUI evita o falso-positivo de auditoria
# (`grep 'mkfs'` / `echo rm -rf` NÃO disparam). MAS o anchor tem que tolerar como o comando REAL é invocado
# (audit 2026-06-08 self-probe): wrappers (nice/timeout/command/…), prefixo de PATH (/bin/rm) e backslash
# (\rm) — senão `/bin/rm -rf /`, `nice rm -rf /`, `\rm -rf /` furavam ATÉ o gate de aprovação.
_WRAP = (r"(?:(?:command|builtin|exec|nohup|setsid|time|nice|ionice|timeout|stdbuf|xargs|sudo|doas|env)"
         r"\s+(?:-[^\s]+\s+|\d+\s+|\w+=\S*\s+)*)*")   # wrappers que precedem o comando (com flags/num/VAR=val)
_BINPREFIX = r"\\?(?:[\w.\-]*/)*"                       # backslash + path do binário: \rm · /bin/rm · /usr/bin/rm
_CMDPOS = r"(?:^|[;&|\n`]|\$\()\s*" + _WRAP + r"\s*" + _BINPREFIX
_CMDSTART = r"(?:^|[;&|\n`]|\$\()\s*" + _WRAP + r"\s*" + _BINPREFIX
_SHELL_RULES = [
    # DESTRUTIVO de verdade — ancorado em posição de comando (não dispara em padrão de grep/argumento).
    # rm com flag recursive/force em QUALQUER posição/forma (-rf, -fr, -r -f, --recursive, --force) —
    # antes exigia o -rf como ÚLTIMO token → `rm --recursive --force x` e `rm -rf -v x` furavam (self-probe).
    (re.compile(_CMDPOS + r"rm\b(?=[^|&;\n`]*\s-(?:[a-z]*[rf]|-(?:recursive|force|no-preserve-root)))", re.I),
     "destructive_shell", "critical"),
    (re.compile(_CMDPOS + r"mkfs(\.[a-z0-9]+)?\b", re.I), "destructive_shell", "critical"),
    (re.compile(r"\bdd\b[^\n]*\bof=/dev/(sd|nvme|hd|mmcblk|vd|xvd)", re.I), "destructive_shell", "critical"),
    (re.compile(r">\s*/dev/(sd|nvme|hd|mmcblk|vd|xvd)[a-z0-9]*\b", re.I), "destructive_shell", "critical"),
    (re.compile(_CMDPOS + r"(shutdown|reboot|halt|poweroff)\b", re.I), "destructive_shell", "critical"),
    (re.compile(_CMDPOS + r"kill\s+(-[^\s]+\s+)*-1\b", re.I), "destructive_shell", "critical"),
    (re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", re.I), "destructive_shell", "critical"),  # fork bomb
    (re.compile(_CMDSTART + r"sudo\b", re.I), "sudo", "high"),
    (re.compile(_CMDSTART + r"git\s+push\b", re.I), "git_push", "medium"),
    (re.compile(_CMDSTART + r"(npm|pip|cargo)\s+publish\b", re.I), "publish", "high"),
    # pipe-to-shell (curl … | bash / wget … | sh) = vetor #1 de RCE via prompt-injection → aprovação ALTA
    # (audit 2026-06-08; pattern do Hermes). Antes só pegava curl -X POST.
    (re.compile(r"\b(curl|wget)\b[^\n|]*\|\s*(?:[\w./]*/)?(?:ba|z|da)?sh\b", re.I), "remote_exec", "high"),
    (re.compile(r"\bcurl\b[^\n]*-X\s*(POST|PUT|DELETE)|\bwget\b[^\n]*--post", re.I), "network_write", "medium"),
    (re.compile(_CMDSTART + r"chmod\b|" + _CMDSTART + r"docker\s+(rm|rmi|system\s+prune)", re.I),
     "system_change", "medium"),
]

# Quando o comando RE-EXECUTA o conteúdo entre aspas (sh -c '…', bash -c, eval), as aspas NÃO escondem
# um argumento — escondem um COMANDO. Aí não dá pra ignorar as aspas; checa o cru contra os críticos.
_RUNS_QUOTED = re.compile(r"\b(?:ba|z|da)?sh\s+-[a-z]*c\b|\beval\b", re.I)
# bash -c '…' / eval: gate de APROVAÇÃO (destructive_shell). Amplo — qualquer rm -rf, etc. + desligamentos
# (init 0/6, systemctl poweroff/reboot/halt/kexec, telinit 0/6 — audit 2026-06-08).
_EVAL_DANGER = re.compile(
    r"\brm\b(?=[^|&;\n`]*\s-(?:[a-z]*[rf]|-(?:recursive|force|no-preserve-root)))"
    r"|\bmkfs(\.[a-z0-9]+)?\b|\bdd\b[^\n]*of=/dev/(sd|nvme|hd|mmcblk|vd|xvd)"
    r"|:\(\)\s*\{\s*:|\bkill\s+(-[^\s]+\s+)*-1\b|\b(shutdown|reboot|halt|poweroff)\b"
    r"|\binit\s+[06]\b|\bsystemctl\s+(poweroff|reboot|halt|kexec)\b|\btelinit\s+[06]\b", re.I)
# bash -c '…' / eval: bloqueio HARDLINE incondicional. Catástrofes SEM uso legítimo (rm de SISTEMA, não
# todo rm -rf). Era o furo: detect_hardline usava só os patterns ancorados em _CMDPOS, que NÃO casam
# DENTRO das aspas → `bash -c 'rm -rf /'` passava o yolo-proof (audit 2026-06-08).
_HARDLINE_EVAL = re.compile(
    r"\brm\s+(-[^\s]*\s+)*(/|/\*|~|\$HOME|/(home|root|etc|usr|var|bin|sbin|boot|lib|opt|sys|proc)(/\*?)?)(?=[\s'\";&|)]|$)"
    r"|\bmkfs(\.[a-z0-9]+)?\b|\bdd\b[^\n]*\bof=/dev/(sd|nvme|hd|mmcblk|vd|xvd)|:\(\)\s*\{\s*:"
    r"|\bkill\s+(-[^\s]+\s+)*-1\b|\b(shutdown|reboot|halt|poweroff)\b|\binit\s+[06]\b"
    r"|\bsystemctl\s+(poweroff|reboot|halt|kexec)\b|\btelinit\s+[06]\b", re.I)


def _strip_quoted(cmd: str) -> str:
    """Remove o CONTEÚDO entre aspas (padrão de grep, mensagem de echo) antes de checar perigo:
    `grep 'mkfs\\|kill -1' f` → `grep '' f`. Comando destrutivo REAL é invocado SEM aspas, então isto
    só apaga argumento/padrão — nunca a invocação. Era o falso-positivo de auditoria (grep de padrões
    perigosos pedia aprovação a cada linha)."""
    return re.sub(r"\"[^\"]*\"|'[^']*'", "''", cmd)


# HARDLINE (Hermes tools/approval.py HARDLINE_PATTERNS): catástrofes SEM uso legítimo pelo agente. Estas
# são BLOQUEADAS de forma INCONDICIONAL — nem /yolo nem /always passam (≠ destructive_shell, que é só gate
# de aprovação). É a rede que o go/no-go não cobre: um yolo distraído não pode formatar o disco.
_HARDLINE = [
    (re.compile(_CMDPOS + r"rm\s+(-[^\s]*\s+)*(/|/\*|~|\$HOME|"
                r"/(home|root|etc|usr|var|bin|sbin|boot|lib|opt|sys|proc)(/\*?)?)(?=[\s'\";&|)]|$)", re.I),
     "rm recursivo de / ou diretório de sistema"),
    (re.compile(_CMDPOS + r"mkfs(\.[a-z0-9]+)?\b", re.I), "formatar filesystem (mkfs)"),   # ancorado: NÃO
    #                                                       dispara em `head mkfs-howto.md` (nome de arquivo)
    (re.compile(r"\bdd\b[^\n]*\bof=/dev/(sd|nvme|hd|mmcblk|vd|xvd)[a-z0-9]*", re.I), "dd p/ dispositivo cru"),
    (re.compile(r">\s*/dev/(sd|nvme|hd|mmcblk|vd|xvd)[a-z0-9]*\b", re.I), "redirect p/ dispositivo cru"),
    (re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", re.I), "fork bomb"),
    (re.compile(_CMDPOS + r"kill\s+(-[^\s]+\s+)*-1\b", re.I), "kill -1 (todos os processos)"),
    (re.compile(_CMDPOS + r"(shutdown|reboot|halt|poweroff)\b", re.I), "shutdown/reboot/halt/poweroff"),
    (re.compile(_CMDPOS + r"init\s+[06]\b", re.I), "init 0/6 (shutdown/reboot)"),
    (re.compile(_CMDPOS + r"systemctl\s+(poweroff|reboot|halt|kexec)\b", re.I), "systemctl poweroff/reboot"),
    (re.compile(_CMDPOS + r"telinit\s+[06]\b", re.I), "telinit 0/6"),
]


def detect_hardline(cmd: str) -> str | None:
    """Comando CATASTRÓFICO (rm -rf /, mkfs, fork bomb, shutdown…) → razão do BLOQUEIO INCONDICIONAL (nem
    yolo passa). None se ok. Usa o mesmo strip de aspas do classify (não dispara em `grep 'mkfs'`)."""
    if not cmd:
        return None
    if _RUNS_QUOTED.search(cmd):                      # bash -c '…'/eval: a catástrofe está DENTRO das aspas →
        return "catástrofe via sh -c/eval" if _HARDLINE_EVAL.search(cmd) else None   # checa sem âncora
    c = _strip_quoted(cmd)
    for rx, desc in _HARDLINE:
        if rx.search(c):
            return desc
    return None


@dataclass
class Sensitive:
    reason: str
    category: str
    risk: str  # low | medium | high | critical


# Rótulos humanos por categoria de risco — usados pra DESTACAR o porquê no prompt de aprovação
# (paridade OpenClaw exec-approvals: o humano vê O QUE é arriscado, não só "Approve?").
_RISK_LABELS = {
    "destructive_shell": "destrutivo (rm -rf / mkfs / dd / shutdown…)",
    "sudo": "privilégio elevado (sudo/doas)",
    "git_push": "publica no repositório remoto (git push)",
    "publish": "publica pacote (npm/pip/cargo publish)",
    "remote_exec": "baixa e executa da internet (pipe p/ shell) — vetor clássico de RCE",
    "network_write": "escrita de rede (POST/PUT/DELETE)",
    "system_change": "mudança de sistema (chmod/docker rm…)",
}


def command_risks(cmd: str) -> list[str]:
    """Lista HUMANA dos riscos detectados num comando shell (vazia = nada flagrado). Reusa as mesmas
    regras do classify — isto é só a camada de APRESENTAÇÃO p/ o prompt de aprovação."""
    if not (cmd or "").strip():
        return []
    out: list[str] = []
    hard = detect_hardline(cmd)
    if hard:
        out.append(f"CATASTRÓFICO: {hard}")
    if _RUNS_QUOTED.search(cmd):
        out.append("executa string dinâmica (eval / sh -c) — o conteúdo das aspas é COMANDO")
    c = _strip_quoted(cmd)
    seen: set[str] = set()
    for rx, cat, _risk in _SHELL_RULES:
        if cat not in seen and rx.search(c):
            seen.add(cat)
            out.append(_RISK_LABELS.get(cat, cat))
    return out


def classify(tool: str, args: dict) -> Sensitive | None:
    """None se não-sensível; senão (razão, categoria, risco)."""
    if tool in ("write_file", "edit_file"):              # edit_file também escreve → mesma trava
        path = str(args.get("path", "")).replace("\\", "/")
        for rx, cat, risk in _FILE_RULES:
            if rx.search(path):
                return Sensitive(f"escrever em {cat}: {path}", cat, risk)
        from okami.core.tools.base import _SENSITIVE_PATH   # MESMA cobertura do shell p/ ESCRITA: id_rsa,
        if _SENSITIVE_PATH.search(path):                    # .ssh, .aws, history, gitconfig… (audit: write/edit
            return Sensitive(f"escrever em caminho sensível: {path}", "secret_file", "high")  # ignorava-os)
    if tool == "apply_patch":                            # patch multi-arquivo: CADA path passa na trava de escrita
        from okami.core.tools.base import _SENSITIVE_PATH
        from okami.core.tools.patch import patch_paths
        for path in patch_paths(str(args.get("patch", ""))):
            path = path.replace("\\", "/")
            for rx, cat, risk in _FILE_RULES:
                if rx.search(path):
                    return Sensitive(f"patch toca {cat}: {path}", cat, risk)
            if _SENSITIVE_PATH.search(path):
                return Sensitive(f"patch toca caminho sensível: {path}", "secret_file", "high")
    if tool in ("run_shell", "process_start"):           # process_start = shell em background → mesma trava
        cmd_raw = str(args.get("cmd", ""))
        if _RUNS_QUOTED.search(cmd_raw):                 # sh -c '…' / eval: aspas escondem COMANDO → checa cru
            if _EVAL_DANGER.search(cmd_raw):
                return Sensitive(f"destructive_shell: {cmd_raw[:100]}", "destructive_shell", "critical")
            cmd = cmd_raw
        else:                                            # senão: aspas escondem ARGUMENTO/padrão → ignora
            cmd = _strip_quoted(cmd_raw)
        for rx, cat, risk in _SHELL_RULES:
            if rx.search(cmd):
                return Sensitive(f"{cat}: {cmd_raw[:100]}", cat, risk)
    if tool == "manage_skill":                           # cria/edita skill que ENTRA no prompt → sensível
        return Sensitive(f"criar/editar skill: {args.get('name', '?')}", "skill_write", "medium")
    if tool == "execute_code":                           # código com rede/processo/deleção → go/no-go
        from okami.core.tools.execute_code import code_is_dangerous
        code = str(args.get("code", ""))
        if code_is_dangerous(code):
            return Sensitive(f"código com padrão perigoso (rede/processo/deleção): {code[:90]}",
                             "execute_code_risk", "high")
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
