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


# --- Captura de segredo INLINE (diretiva do dono: "Só no cofre, nunca no LLM") -------------------
#
# Detector CONSERVADOR de propósito: só dispara em formatos de ALTA CONFIANÇA (prefixo de chave
# conhecido, ou "NOME_SENSÍVEL = valor"/"NOME_SENSÍVEL: valor" com valor comprido o bastante) — texto
# comum tipo "minha senha é hunter2" (linguagem natural, valor curto) passa batido de propósito.
# Usado pelo gateway ANTES de tocar o modelo (okami/gateway/endpoint.py `_run`), nunca pelo redator
# de SAÍDA (`redact`/`clean_output` acima, que continua mascarando qualquer forma reconhecida).

# prefixo de chave conhecido -> nome canônico da env var (paridade com o `.env`/`store_secret`).
_KEY_PREFIXES: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\bgithub_pat_[A-Za-z0-9_]{20,}\b'), "GITHUB_TOKEN"),
    (re.compile(r'\bgh[pousr]_[A-Za-z0-9]{20,}\b'), "GITHUB_TOKEN"),
    (re.compile(r'\bsk-ant-[A-Za-z0-9\-_]{20,}\b'), "ANTHROPIC_API_KEY"),
    (re.compile(r'\bsk-proj-[A-Za-z0-9\-_]{20,}\b'), "OPENAI_API_KEY"),
    (re.compile(r'\bsk_live_[A-Za-z0-9]{20,}\b'), "STRIPE_API_KEY"),
    (re.compile(r'\bsk_test_[A-Za-z0-9]{20,}\b'), "STRIPE_API_KEY"),
    (re.compile(r'\bsk-[A-Za-z0-9]{20,}\b'), "OPENAI_API_KEY"),           # genérico — DEPOIS de sk-ant-/sk-proj-
    (re.compile(r'\bxai-[A-Za-z0-9]{20,}\b'), "XAI_API_KEY"),
    (re.compile(r'\bAKIA[0-9A-Z]{12,}\b'), "AWS_ACCESS_KEY_ID"),
    (re.compile(r'\bxox[baprs]-[A-Za-z0-9-]{10,}\b'), "SLACK_TOKEN"),
    (re.compile(r'\bAIza[0-9A-Za-z_\-]{35}\b'), "GOOGLE_API_KEY"),
    (re.compile(r'\bglpat-[A-Za-z0-9_\-]{20,}\b'), "GITLAB_TOKEN"),
    (re.compile(r'\bnpm_[A-Za-z0-9]{20,}\b'), "NPM_TOKEN"),
    (re.compile(r'\bhf_[A-Za-z0-9]{20,}\b'), "HF_TOKEN"),
]

# forma explícita "NOME_SENSÍVEL = valor" / "NOME_SENSÍVEL: valor" — só com separador LITERAL (=/:),
# nunca "é"/"is" (evita casar frase natural tipo "minha senha é hunter2"); valor exige >=12 chars
# sem espaço — corta senha curta de propósito (conservador > sensível).
_ASSIGN_SECRET = re.compile(
    r'(?i)\b([A-Z0-9_]*(?:API[_-]?KEY|ACCESS[_-]?KEY|SECRET|TOKEN|PASSWORD|PASSWD|SENHA|'
    r'CREDENTIAL|PRIVATE[_-]?KEY|AUTH)[A-Z0-9_]*)\b'
    r'\s*[=:]\s*["\']?([^\s"\']{12,})["\']?'
)

# hint de provider por PALAVRA no texto (linguagem natural, "minha chave do github é …") — só usado
# p/ nomear um valor com PREFIXO já reconhecido (nunca sozinho: não vira gatilho de detecção).
_PROVIDER_HINTS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'(?i)\bgit ?hub\b'), "GITHUB_TOKEN"),
    (re.compile(r'(?i)\bopen ?ai\b'), "OPENAI_API_KEY"),
    (re.compile(r'(?i)\banthropic\b|\bclaude\b'), "ANTHROPIC_API_KEY"),
    (re.compile(r'(?i)\bminimax\b'), "MINIMAX_API_KEY"),
    (re.compile(r'(?i)\beleven ?labs\b'), "ELEVENLABS_API_KEY"),
    (re.compile(r'(?i)\bslack\b'), "SLACK_TOKEN"),
    (re.compile(r'(?i)\baws\b'), "AWS_ACCESS_KEY_ID"),
    (re.compile(r'(?i)\bgoogle\b|\bgemini\b'), "GOOGLE_API_KEY"),
    (re.compile(r'(?i)\bxai\b|\bgrok\b'), "XAI_API_KEY"),
    (re.compile(r'(?i)\bgitlab\b'), "GITLAB_TOKEN"),
    (re.compile(r'(?i)\bnpm\b'), "NPM_TOKEN"),
    (re.compile(r'(?i)\bstripe\b'), "STRIPE_API_KEY"),
    (re.compile(r'(?i)\bopenrouter\b'), "OPENROUTER_API_KEY"),
    (re.compile(r'(?i)\bmistral\b'), "MISTRAL_API_KEY"),
    (re.compile(r'(?i)\bcohere\b'), "COHERE_API_KEY"),
    (re.compile(r'(?i)\bhugging ?face\b'), "HF_TOKEN"),
    (re.compile(r'(?i)\bvercel\b'), "VERCEL_TOKEN"),
    (re.compile(r'(?i)\bsupabase\b'), "SUPABASE_KEY"),
    (re.compile(r'(?i)\btelegram\b'), "TELEGRAM_BOT_TOKEN"),
    (re.compile(r'(?i)\bmimo\b'), "MIMO_API_KEY"),
]


def _normalize_secret_name(raw: str) -> str:
    """'ElevenLabs API Key' → 'ELEVENLABS_API_KEY' (mesma normalização de core/tools/secrets.py,
    duplicada aqui de propósito — redact.py é módulo de baixo nível, sem depender da camada de tools)."""
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", (raw or "").strip()).strip("_").upper()
    if cleaned and cleaned[0].isdigit():
        cleaned = "_" + cleaned
    return cleaned or "SECRET"


def detect_inline_secrets(text: str) -> list[dict]:
    """Varre `text` por segredo de ALTA CONFIANÇA e devolve `[{"name", "value", "start", "end"}, …]`
    em ordem de aparição, sem sobreposição (o 1º match "ganha" o trecho). Vazio/não-str → [].

    Conservador: só prefixo de chave conhecido OU "NOME=valor"/"NOME:valor" explícito disparam —
    frase solta tipo "minha senha é hunter2" nunca aparece aqui (ver docstring da seção acima)."""
    if not text or not isinstance(text, str):
        return []
    matches: list[dict] = []
    claimed: list[tuple[int, int]] = []

    def _overlaps(a: int, b: int) -> bool:
        return any(a < e and s < b for s, e in claimed)

    for rx, name in _KEY_PREFIXES:
        for m in rx.finditer(text):
            s, e = m.span()
            if _overlaps(s, e):
                continue
            matches.append({"name": name, "value": m.group(0), "start": s, "end": e})
            claimed.append((s, e))

    for m in _ASSIGN_SECRET.finditer(text):
        s, e = m.span()
        if _overlaps(s, e):
            continue
        raw_name, value = m.group(1), m.group(2)
        # se o VALOR em si já bate um prefixo conhecido, prefere o nome do prefixo (mais preciso que
        # o rótulo digitado pelo usuário); senão usa hint de provider no texto; senão normaliza o rótulo.
        name = None
        for rx2, hinted in _KEY_PREFIXES:
            if rx2.match(value):
                name = hinted
                break
        if name is None:
            for hint_rx, hinted in _PROVIDER_HINTS:
                if hint_rx.search(text):
                    name = hinted
                    break
        if name is None:
            name = _normalize_secret_name(raw_name)
        matches.append({"name": name, "value": value, "start": s, "end": e})
        claimed.append((s, e))

    matches.sort(key=lambda d: d["start"])
    return matches


def sanitize_inline_secrets(text: str) -> tuple[str, list[dict], str]:
    """Aplica `detect_inline_secrets` e devolve `(texto_saneado, matches, nota)`:
      - `texto_saneado`: `text` com CADA valor de segredo substituído por uma nota — é o que deve
        seguir para o modelo/transcript/log (o valor cru NUNCA aparece nele).
      - `matches`: a lista crua (com os valores, só para o CALLER guardar no cofre — não persista).
      - `nota`: resumo "[o usuário forneceu a credencial X, Y; guardada(s) com segurança]" (ou "" se
        não achou nada) — pronto para prefixar o texto final se o caller preferir uma nota única.

    Sem matches → `(text, [], "")` intocado (custo zero no caminho comum)."""
    matches = detect_inline_secrets(text)
    if not matches:
        return text, [], ""
    out = []
    last = 0
    for m in matches:
        out.append(text[last:m["start"]])
        out.append(f"[credencial {m['name']} recebida — guardada com segurança, não repetida aqui]")
        last = m["end"]
    out.append(text[last:])
    sanitized = "".join(out)
    names = ", ".join(dict.fromkeys(m["name"] for m in matches))  # dedup preservando ordem
    note = f"[o usuário forneceu a(s) credencial(is) {names}; guardada(s) com segurança no cofre]"
    return sanitized, matches, note


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
