"""Redator central — estilo Hermes `redact.py`.

UM lugar só p/ mascarar segredos antes de QUALQUER coisa sair pra log, saída de tool,
auditoria (.okami/audit.jsonl) ou mensagem de erro. Conservador de propósito: prefere
mascarar a vazar, mas não mutila texto comum (padrões específicos, não "qualquer coisa longa").
"""

from __future__ import annotations

import re

_MASK = "«redacted»"

_PATTERNS: list[tuple[re.Pattern, str]] = [
    # NOME_SENSÍVEL = valor  /  "nome": "valor"  (KEY/SECRET/TOKEN/PASSWORD/AUTH/SESSION/COOKIE…)
    # O sep tolera aspas (estilo JSON: "password": "x") entre o nome e o = / :.
    (re.compile(
        r'(?i)(\b[A-Z0-9_]*(?:API[_-]?KEY|ACCESS[_-]?KEY|SECRET|TOKEN|PASSWORD|PASSWD|'
        r'CREDENTIAL|PRIVATE[_-]?KEY|SESSION|COOKIE|AUTH)[A-Z0-9_]*\b)(["\']?\s*[=:]\s*["\']?)'
        r'((?=[^\s"\',;]*[A-Za-z])[^\s"\',;]+)'),     # valor PRECISA ter letra: não mascara contagem (tokens_in: 2650)
     lambda m: f"{m.group(1)}{m.group(2)}{_MASK}"),
    (re.compile(r'(?i)\bBearer\s+[A-Za-z0-9._\-]{8,}'), f"Bearer {_MASK}"),
    (re.compile(r'\bsk-[A-Za-z0-9_\-]{16,}\b'), f"sk-{_MASK}"),          # OpenAI-style
    (re.compile(r'\bxox[baprs]-[A-Za-z0-9-]{8,}\b'), f"xox-{_MASK}"),    # Slack
    (re.compile(r'\b(gh[pousr]_)[A-Za-z0-9]{20,}\b'), lambda m: f"{m.group(1)}{_MASK}"),  # GitHub
    (re.compile(r'\bAKIA[0-9A-Z]{12,}\b'), f"AKIA{_MASK}"),             # AWS access key id
    (re.compile(r'\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{6,}\b'),
     f"{_MASK}-jwt"),                                                    # JWT
    (re.compile(r'-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----', re.DOTALL),
     f"-----BEGIN PRIVATE KEY-----{_MASK}-----END PRIVATE KEY-----"),  # pragma: allowlist secret  (é a MÁSCARA, não segredo)
    (re.compile(r'-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[A-Za-z0-9+/=\s]{40,}'),  # pragma: allowlist secret
     f"-----BEGIN PRIVATE KEY-----{_MASK}"),  # pragma: allowlist secret  — chave TRUNCADA/sem END: mascara o corpo base64
    (re.compile(r'([a-z][a-z0-9+.\-]*://[^:/@\s]+:)([^@/\s]+)(@)'),      # senha em URL: scheme://user:SENHA@host
     lambda m: f"{m.group(1)}{_MASK}{m.group(3)}"),
    (re.compile(r'\bAIza[0-9A-Za-z_\-]{35}\b'), f"AIza{_MASK}"),         # Google API key
]


def redact(text: str) -> str:
    """Mascara segredos conhecidos em `text` (no-op p/ vazio/não-str)."""
    if not text or not isinstance(text, str):
        return text
    for rx, repl in _PATTERNS:
        text = rx.sub(repl, text)
    return text


_LONE_SURROGATE = re.compile("[\ud800-\udfff]")


def safe_text(text: str) -> str:
    """Remove surrogates SOLITÁRIOS (U+D800–U+DFFF) trocando-os por U+FFFD (�).

    No Windows o console às vezes injeta meio-surrogate no input (emoji/colagem). Eles NÃO são UTF-8
    válido e estouram qualquer `.encode('utf-8')` — histórico do prompt_toolkit, print do Rich, JSON
    pro LLM (UnicodeEncodeError: 'surrogates not allowed'). Texto comum e emoji VÁLIDO passam intactos.
    """
    if not text or not isinstance(text, str):
        return text
    return _LONE_SURROGATE.sub("�", text)


def looks_secret(text: str) -> bool:
    """True se `text` contém um padrão de segredo conhecido (= o redator mexeria nele).

    Usado para RECUSAR persistência (memória/USER.md) — segredo não vira contexto durável."""
    return bool(text) and isinstance(text, str) and redact(text) != text


_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")


def strip_ansi(text: str) -> str:
    """Remove escapes ANSI (cor/cursor) — saída de tool não deve poluir o contexto do modelo (P1.1)."""
    if not text or not isinstance(text, str):
        return text
    return _ANSI.sub("", text)


def clean_output(text: str, *, head: int = 6000, tail: int = 2000) -> str:
    """Higieniza saída de tool ANTES do modelo: strip ANSI + redact segredo + truncagem HEAD/TAIL
    (preserva os dois extremos — o exit code/erro costuma ficar no fim)."""
    if not text or not isinstance(text, str):
        return text
    text = redact(strip_ansi(text))
    if len(text) <= head + tail + 80:
        return text
    omitted = len(text) - head - tail
    return f"{text[:head]}\n…[{omitted} chars omitidos no meio]…\n{text[-tail:]}"
