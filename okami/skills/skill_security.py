"""Validador de segurança de skills (CRÍTICO).

Skills são código + instruções que entram DIRETO no contexto/execução do agente. Uma skill
maliciosa pode: prompt injection, exfiltrar segredos (incl. suas credenciais OAuth!), rodar
`rm -rf`, `curl|bash`, instalar malware. Por isso: nada é instalado/injetado sem passar por
este scan. HIGH/CRITICAL = BLOQUEADO (só instala com --force explícito).

Cobre cenários que Hermes/OpenClaw aprenderam na marca: ofuscação/evasão de scanner (Hermes
#7072), unicode oculto/Trojan Source, descrição/arquivos injetados sem scan (#8884), binários
empacotados. Camada estática (regex). Uma revisão por LLM pode ser somada depois.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path


class Severity(IntEnum):
    INFO = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


SEV_NAME = {0: "INFO", 1: "LOW", 2: "MEDIUM", 3: "HIGH", 4: "CRITICAL"}

TEXT_EXT = {".md", ".txt", ".sh", ".bash", ".zsh", ".py", ".js", ".ts", ".mjs", ".cjs",
            ".rb", ".pl", ".ps1", ".yaml", ".yml", ".json", ".toml", ".cfg", ""}

# (regex, rule, severity, porquê) — IGNORECASE.
_RULES: list[tuple[str, str, Severity, str]] = [
    # Prompt injection / manipulação do agente
    (r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", "prompt_injection", Severity.HIGH, "tenta sobrescrever instruções"),
    (r"disregard\s+(the\s+)?(system|prior|previous|above)", "prompt_injection", Severity.HIGH, "tenta descartar o system prompt"),
    (r"(reveal|print|show|dump|leak)\s+(your|the)\s+(system\s+)?(prompt|instructions)", "prompt_leak", Severity.HIGH, "tenta vazar o system prompt"),
    (r"do\s+not\s+(tell|inform|notify|warn)\s+the\s+user", "stealth", Severity.HIGH, "instrui a agir escondido do usuário"),
    (r"without\s+(telling|informing|notifying|alerting)\s+(the\s+)?user", "stealth", Severity.HIGH, "ação escondida do usuário"),
    (r"\bexfiltrat", "exfiltration", Severity.HIGH, "menção a exfiltração"),
    (r"(send|upload|post|leak)\s+(the\s+)?(env|secrets?|credentials?|tokens?|api[_\s-]?keys?|password)", "exfiltration", Severity.HIGH, "envio de segredos"),
    (r"bypass\s+(the\s+)?(gate|safety|guard|harness|validation|security)", "bypass", Severity.HIGH, "tenta burlar proteções"),
    (r"you\s+are\s+now\s+", "persona_override", Severity.MEDIUM, "tenta trocar a persona"),
    (r"\b(jailbreak|DAN\s+mode)\b", "jailbreak", Severity.MEDIUM, "linguagem de jailbreak"),
    # Shell destrutivo / RCE remoto
    (r"rm\s+-[rf]{1,2}\s+(/|~|\$HOME|\*)", "rm_rf", Severity.CRITICAL, "remoção destrutiva"),
    (r":\(\)\s*\{\s*:\s*\|\s*:", "fork_bomb", Severity.CRITICAL, "fork bomb"),
    (r"\bmkfs\b", "mkfs", Severity.CRITICAL, "formata sistema de arquivos"),
    (r"dd\s+if=\S+\s+of=/dev/", "dd_disk", Severity.CRITICAL, "sobrescreve dispositivo"),
    (r">\s*/dev/sd[a-z]", "overwrite_disk", Severity.CRITICAL, "escreve em disco bruto"),
    (r"(curl|wget)\s+[^\n|]*\|\s*(sudo\s+)?(ba)?sh", "pipe_to_shell", Severity.HIGH, "baixa e executa código remoto"),
    (r"\b(?:ba)?sh\s+<\(\s*(?:curl|wget|fetch)", "proc_subst_exec", Severity.HIGH, "executa download via process substitution (sh <(curl…))"),
    (r"chmod\s+-R\s*0?777\s+/", "chmod_root", Severity.HIGH, "permissões perigosas na raiz"),
    # "prepara e executa" payload local — gap que o chmod_root não pegava (#7)
    (r"chmod\s+\+x\b[^\n]*?(?:&&|;|\|\||\n)\s*(?:\./|\bsh\s|\bbash\s|\bpython\d?\s|\bnode\s|\bperl\s|\bruby\s|\bsource\s)",
     "chmod_exec", Severity.MEDIUM, "prepara e EXECUTA payload local (chmod +x → run)"),
    (r"\b(?:bash|sh|python\d?|node|perl|ruby)\s+(?:/tmp/|/dev/shm/|/var/tmp/|~/\.[\w]|\$\{?TMPDIR)",
     "run_from_temp", Severity.MEDIUM, "executa arquivo de diretório temporário/oculto (payload solto)"),
    # Exfiltração — hosts/webhooks comuns
    (r"discord(app)?\.com/api/webhooks", "exfil_webhook", Severity.HIGH, "webhook Discord (exfil)"),
    (r"hooks\.slack\.com/services", "exfil_webhook", Severity.HIGH, "webhook Slack (exfil)"),
    (r"api\.telegram\.org/bot", "exfil_webhook", Severity.HIGH, "bot Telegram (exfil)"),
    (r"(webhook\.site|requestbin|pipedream\.net|ngrok\.io|pastebin\.com|transfer\.sh|0x0\.st|termbin)", "exfil_host", Severity.HIGH, "host de exfiltração comum"),
    # Acesso a segredos
    (r"\.ssh/|id_rsa|id_ed25519", "secret_ssh", Severity.MEDIUM, "acesso a chaves SSH"),
    (r"\.aws/credentials|AKIA[0-9A-Z]{16}", "secret_aws", Severity.MEDIUM, "credenciais AWS"),
    (r"\.codex/auth\.json|\.claude/\.credentials|\.okami/credentials|auth-profiles", "secret_agent", Severity.HIGH, "acesso às credenciais do agente"),
    # RCE / ofuscação
    (r"base64\s+-d|base64\s+--decode|\batob\s*\(", "obfuscation", Severity.MEDIUM, "decodificação de payload"),
    (r"\beval\s*\(|\bexec\s*\(", "dynamic_exec", Severity.MEDIUM, "execução dinâmica de código"),
    (r"os\.system\s*\(|shell\s*=\s*True|child_process", "shell_exec", Severity.MEDIUM, "execução de shell embutida"),
    (r"pickle\.loads|marshal\.loads", "unsafe_deser", Severity.MEDIUM, "desserialização insegura"),
    # Ofuscação/evasão de scanner (gap real do Hermes #7072)
    (r"__import__\s*\(|importlib\.import_module", "obf_dynamic_import", Severity.HIGH, "import dinâmico (evasão de scanner)"),
    (r"getattr\s*\(\s*__import__|getattr\s*\(\s*globals", "obf_getattr", Severity.HIGH, "getattr+import (evasão)"),
    (r"globals\(\)\s*\[|locals\(\)\s*\[", "obf_namespace", Severity.MEDIUM, "acesso dinâmico a namespace"),
    (r"(\\x[0-9a-fA-F]{2}){5,}", "obf_hex_string", Severity.MEDIUM, "string em hex escapes (ofuscação)"),
    (r"chr\s*\(\s*\d+\s*\)\s*\+\s*chr", "obf_charcode", Severity.MEDIUM, "string montada por char codes (ofuscação)"),
    # Rede
    (r"https?://\d{1,3}(\.\d{1,3}){3}", "raw_ip_url", Severity.LOW, "URL com IP bruto"),
]

_COMPILED = [(re.compile(rx, re.IGNORECASE), rule, sev, why) for rx, rule, sev, why in _RULES]
# Chamada de REDE — com word-boundaries: antes `curl` casava dentro de "Curly quotes", `fetch` sem `(`
# casava "fetch the guidelines" em prosa. Agora só a chamada de verdade (curl/wget como comando, fetch(,
# requests.<verbo>, urllib, axios, etc.).
_NET_CALL = re.compile(
    r"(\bcurl\b|\bwget\b|fetch\s*\(|requests\.(get|post|put|patch|delete)|\burllib\b|\baxios\b"
    r"|Invoke-WebRequest|http\.request|XMLHttpRequest|\.post\s*\()", re.IGNORECASE)
# Referência a CREDENCIAL — calibrado (2026-07-09): antes `token`/`secret`/`password`/`env` NUS casavam
# "design token", "csrf token", "tokenizer", "environment", "secretly", "no password required" — falso-
# positivo em toda skill de design/web/marketing. Agora só indicadores FORTES: caminhos de credencial,
# api-key, token QUALIFICADO (auth/access/bearer/oauth/api/secret token) ou atribuído (token=/:), secret/
# password como palavra inteira, env-var de credencial (STRIPE_KEY/OPENAI_API_KEY), e acesso a env real
# (.env/process.env/os.environ/getenv). "design token" e afins NÃO casam mais.
_SECRET_REF = re.compile(
    r"(\.ssh/|id_rsa|\.aws/cred|\.codex/auth|\.claude/\.cred|\.okami/cred"
    r"|\bapi[_\s-]?keys?\b"
    r"|(?:auth|access|bearer|oauth|refresh|api|session|private|client)[_\s-]?tokens?\b"
    r"|\btokens?\s*[=:]"
    r"|\bsecrets?\b|\bpasswords?\b|\bpasswd\b|\bsenhas?\b"
    r"|[A-Z][A-Z0-9]*_(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|APIKEY)\b"
    r"|\.env\b|process\.env|os\.environ|getenv)", re.IGNORECASE)
# Proximidade (linhas) exigida entre um segredo e uma chamada de rede p/ acusar exfiltração: o padrão real
# é "lê a credencial e MANDA logo em seguida". Um doc longo com uma env-var no topo e um fetch( 200 linhas
# abaixo NÃO é exfil. Janela apertada mata o falso-positivo sem abrir buraco no ataque de verdade.
_SECRET_NET_PROXIMITY = 4
# Unicode oculto: zero-width, BOM e overrides bidirecionais (Trojan Source) usados para
# esconder prompt injection da revisão humana.
_HIDDEN_UNICODE = re.compile("[\u200b-\u200f\u202a-\u202e\u2060\u2066-\u2069\ufeff]")
# Binários/executáveis empacotados (não dá para escanear o conteúdo).
_EXEC_EXT = {".exe", ".dll", ".so", ".dylib", ".bin", ".msi", ".scr", ".com", ".bat",
             ".cmd", ".app", ".o", ".a", ".node", ".wasm"}


@dataclass
class Finding:
    severity: Severity
    rule: str
    file: str
    line: int
    snippet: str
    why: str

    def __str__(self) -> str:
        return f"[{SEV_NAME[self.severity]}] {self.file}:{self.line} {self.rule} — {self.why}"


@dataclass
class RiskReport:
    findings: list[Finding] = field(default_factory=list)

    @property
    def max_severity(self) -> Severity:
        return max((f.severity for f in self.findings), default=Severity.INFO)

    @property
    def blocked(self) -> bool:
        return self.max_severity >= Severity.HIGH

    def sorted(self) -> list[Finding]:
        return sorted(self.findings, key=lambda f: (-int(f.severity), f.file, f.line))


def scan_text(name: str, text: str) -> list[Finding]:
    """Escaneia um texto (use para TUDO que será injetado no prompt — corpo, descrição, etc.)."""
    out: list[Finding] = []
    secret_lines: list[int] = []
    net_lines: list[int] = []
    for i, line in enumerate(text.splitlines(), 1):
        for rx, rule, sev, why in _COMPILED:
            if rx.search(line):
                out.append(Finding(sev, rule, name, i, line.strip()[:120], why))
        if _HIDDEN_UNICODE.search(line):
            out.append(Finding(Severity.HIGH, "hidden_unicode", name, i,
                               "caracteres unicode ocultos/bidi (Trojan Source)", "esconde conteúdo da revisão"))
        if _SECRET_REF.search(line):
            secret_lines.append(i)
        if _NET_CALL.search(line):
            net_lines.append(i)
    # exfiltração = credencial E envio PERTO um do outro (não o arquivo inteiro): mata o falso-positivo de
    # "design token"↔"fetch(" a 200 linhas de distância, mantendo o ataque real (ler segredo → mandar já).
    near = next(((s, n) for s in secret_lines for n in net_lines
                 if abs(s - n) <= _SECRET_NET_PROXIMITY), None)
    if near:
        # MEDIUM (avisa, NÃO bloqueia): a mera co-ocorrência de credencial + rede perto é COMUM em código
        # legítimo (skill de API lê a chave e chama o próprio serviço — api-debug, stocks). A intenção
        # MALICIOSA de verdade (MANDAR o segredo pra fora) já tem regra HIGH própria (`exfiltration`: verbo
        # send/upload/post/leak + segredo). Aqui é só um sinal p/ o dono revisar, não um bloqueio de install.
        out.append(Finding(Severity.MEDIUM, "secret_plus_network", name, near[0],
                           f"credencial (l.{near[0]}) e chamada de rede (l.{near[1]}) a <{_SECRET_NET_PROXIMITY+1} "
                           "linhas — revise se o segredo não vaza (uso legítimo: chave como header de auth)",
                           "credencial perto de chamada de rede"))
    return out


def scan_path(path: Path) -> RiskReport:
    report = RiskReport()
    files = [path] if path.is_file() else [p for p in path.rglob("*") if p.is_file()]
    for p in files:
        rel = str(p.relative_to(path)) if path.is_dir() else p.name
        suf = p.suffix.lower()
        if suf not in TEXT_EXT:
            sev = Severity.HIGH if suf in _EXEC_EXT else Severity.MEDIUM
            why = "executável empacotado" if suf in _EXEC_EXT else "binário não escaneável"
            report.findings.append(Finding(sev, "binary_file", rel, 0, p.name, why))
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        report.findings.extend(scan_text(rel, text))
    return report
