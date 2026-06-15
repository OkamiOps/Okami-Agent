"""Scan de segurança WRITE-TIME (#9) — avisa quando o AGENTE grava um padrão perigoso.

Modo WARN (não bloqueia: regex tem falso-positivo): anexa um aviso ao resultado do write/edit; o
agente vê e se corrige no próximo passo. Regras de alta-sinal (porte do security-guidance da Anthropic),
por linguagem. Distinto do scan de skills de TERCEIROS — aqui é o código que o próprio agente produz.
"""
from __future__ import annotations

import re

_CODE_EXT = (".py", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs", ".go", ".rb", ".java", ".yml", ".yaml")
_CAP = 256_000

# (extensões, regex, mensagem). `.` no regex NÃO cruza linha → lookahead fica na mesma chamada/linha.
_RULES: tuple[tuple[tuple[str, ...], re.Pattern, str], ...] = (
    ((".py",), re.compile(r"\bpickle\.loads?\("), "pickle.load(s) desserializa código arbitrário — fonte não-confiável = RCE"),
    ((".py",), re.compile(r"\byaml\.load\((?![^)\n]*Loader\s*=\s*[A-Za-z_.]*SafeLoader)"), "yaml.load sem SafeLoader = RCE — use yaml.safe_load"),
    ((".py",), re.compile(r"(?<![A-Za-z_.])eval\("), "eval() executa código arbitrário"),
    ((".py",), re.compile(r"\bos\.system\("), "os.system = injeção de comando — prefira subprocess sem shell"),
    ((".py",), re.compile(r"\bshell\s*=\s*True\b"), "subprocess com shell=True = injeção de comando se houver entrada externa"),
    ((".py", ".go", ".js", ".ts"), re.compile(r"\bverify\s*=\s*False\b|InsecureSkipVerify\s*:\s*true|rejectUnauthorized\s*:\s*false"), "verificação de TLS desligada (MITM)"),
    ((".py",), re.compile(r"\btorch\.load\((?![^)\n]*weights_only\s*=\s*True)"), "torch.load sem weights_only=True = RCE por desserialização"),
    ((".py",), re.compile(r"\bMODE_ECB\b"), "AES no modo ECB é inseguro (vaza padrões) — use GCM/CBC com IV"),
    ((".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs"), re.compile(r"dangerouslySetInnerHTML|\.innerHTML\s*="), "innerHTML/dangerouslySetInnerHTML com dado do usuário = XSS"),
    ((".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs"), re.compile(r"child_process\.(exec|execSync)\(|\beval\("), "exec/eval em Node = injeção de comando/código"),
    ((".go",), re.compile(r'exec\.Command\(\s*"(sh|bash)"'), "exec.Command(\"sh\"/\"bash\") = injeção de comando"),
    ((".yml", ".yaml"), re.compile(r"\$\{\{\s*github\.event\.[^}]*\}\}"), "${{ github.event.* }} num run: = injeção em GitHub Actions — use env: intermediário"),
)


def _ext(filename: str) -> str:
    name = str(filename).lower()
    dot = name.rfind(".")
    return name[dot:] if dot >= 0 else ""


def scan_code(filename: str, content: str) -> list[str]:
    """Avisos de segurança p/ o código escrito (vazio se limpo ou se o arquivo não é código)."""
    ext = _ext(filename)
    if ext not in _CODE_EXT or not content:
        return []
    text = content[:_CAP]
    out = []
    for exts, rx, msg in _RULES:
        if ext in exts and rx.search(text):
            out.append(msg)
    return out


def security_warn(filename: str, content: str) -> str:
    """Bloco de aviso formatado p/ anexar ao resultado do write/edit, ou "" se limpo."""
    hits = scan_code(filename, content)
    if not hits:
        return ""
    return "⚠️ segurança (revise — não bloqueado):\n" + "\n".join(f"  • {h}" for h in hits)
