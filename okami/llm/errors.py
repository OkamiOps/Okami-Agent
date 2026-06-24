"""Classificação de erros de provider → qual alavanca puxar (porta enxuta do error_classifier do Hermes).

Sem isto, o `complete_messages` rotaciona a chave em QUALQUER erro — inclusive um 400/content-policy
que vai falhar igual em toda chave, queimando o pool e o failover à toa. Aqui a gente decide:
- 429 (rate_limit)  → rotaciona chave do mesmo provider + pode failover; retriável.
- 503/529 (overloaded) → NÃO rotaciona (todas as chaves veem o mesmo provider sobrecarregado);
  back off e troca de provider; retriável.
- 401 (auth transitório) → rotaciona chave; retriável.
- 403 (auth permanente), content-policy, 404 (modelo inexistente) → NÃO retriável; só failover.
- contexto estourado / 413 → comprime e tenta de novo.
- 400 (bad request) → falha rápido (determinístico).
- timeout / 5xx → retriável.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ClassifiedError:
    reason: str
    status: int | None = None
    retryable: bool = True
    rotate_key: bool = False      # tenta outra chave do MESMO provider
    fallback: bool = False        # troca de provider
    compress: bool = False        # contexto estourou → compacta e retenta
    retry_after: float | None = None  # quanto o PROVIDER pediu p/ esperar (header/mensagem) — vence o TTL default
    never_repeat: bool = False    # NUNCA re-enviar o MESMO payload (content_policy) — nem p/ outro provider
    context_limit: int | None = None  # limite de contexto (TOKENS) que o provider REPORTOU no erro de overflow —
    #                                   crucial p/ Ollama/LMStudio: o contexto carregado raramente bate o catálogo


_RETRY_AFTER = re.compile(r"(?:retry.?after|try again in|wait)\s*:?\s*(\d+(?:\.\d+)?)\s*(?:s\b|sec)", re.I)


def _retry_after_of(exc) -> float | None:
    """Extrai o retry-after da exceção (atributo do SDK ou frase na mensagem). None = sem dica."""
    for attr in ("retry_after", "retry_after_secs"):
        v = getattr(exc, attr, None)
        if isinstance(v, (int, float)) and 0 < v < 24 * 3600:
            return float(v)
    m = _RETRY_AFTER.search(str(exc))
    return float(m.group(1)) if m else None


# Sinal de cota TRANSITÓRIA/periódica (reseta sozinha) — NÃO é billing permanente: martelar depois do
# reset resolve, pedir humano não. Desambigua um 429-de-cota de uma conta sem crédito.
_TRANSIENT_QUOTA = re.compile(r"resets?\s*(in|at)|try again in|requests?\s*remaining|per\s*(second|minute|hour|day)|"
                              r"\bwindow\b|retry.?after|\brpm\b|\btpm\b|periodic|rate.?limit", re.I)
# 5xx que na verdade é erro DETERMINÍSTICO de validação do request (alguns providers devolvem 500/502 p/
# parâmetro inválido) — re-tentar igual martela pra sempre; trata como bad_request (não-retriável).
_VALIDATION = re.compile(r"unknown parameter|unsupported parameter|unrecognized request argument|"
                         r"invalid_request_error|unexpected keyword|no such parameter|invalid value for", re.I)


def _msg_of(exc) -> str:
    """Texto p/ classificar — junta str(exc) + a mensagem REAL aninhada no body do provider (OpenRouter/
    litellm escondem o motivo em body['error']['message'] e ['metadata']['raw']). Defensivo: erro no parse
    nunca derruba a classificação (cai no str(exc))."""
    parts = [str(exc)]
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            if isinstance(err.get("message"), str):
                parts.append(err["message"])
            meta = err.get("metadata")
            raw = meta.get("raw") if isinstance(meta, dict) else None
            if isinstance(raw, str):
                try:
                    import json
                    inner = json.loads(raw)
                    im = (inner.get("error") or {}).get("message") if isinstance(inner, dict) else None
                    parts.append(im if isinstance(im, str) else raw)
                except Exception:  # noqa: BLE001
                    parts.append(raw)
    return "  ".join(parts)


def _status_of(exc) -> int | None:
    cur = exc                                          # alguns SDKs embrulham o status real no __cause__
    for _ in range(5):                                 # anda a cadeia de exceções (cause/context), bounded
        if cur is None:
            break
        for attr in ("status_code", "status", "code", "http_status"):
            v = getattr(cur, attr, None)
            if isinstance(v, int) and 100 <= v < 600:
                return v
        resp = getattr(cur, "response", None)          # boto3 ClientError esconde o status aqui
        if isinstance(resp, dict):
            v = (resp.get("ResponseMetadata") or {}).get("HTTPStatusCode")
            if isinstance(v, int) and 100 <= v < 600:
                return v
        nxt = getattr(cur, "__cause__", None) or getattr(cur, "__context__", None)
        cur = nxt if nxt is not cur else None
    m = re.search(r"\b([45]\d\d)\b", str(exc))
    return int(m.group(1)) if m else None


_RATE = re.compile(r"rate.?limit|too many requests|\b429\b|quota", re.I)
_OVERLOAD = re.compile(r"overloaded|\b529\b|\b503\b|temporarily unavailable|capacity", re.I)
_AUTH = re.compile(r"\b401\b|unauthorized|invalid api key|authentication", re.I)
_AUTHPERM = re.compile(r"\b403\b|forbidden|permission denied|account.*(disabled|revoked)", re.I)
_CTX = re.compile(r"context length|maximum context|context window|too long|\b413\b|payload too large", re.I)
# Extrai o limite de contexto (em TOKENS) que o provider cita no erro — ex.: "maximum context length is 8192
# tokens", "context window of 32768", "8192 tokens ... context". Multi-vendor: cada um escreve diferente.
_CTX_LIMIT = re.compile(
    r"(?:maximum context length|context length|context window|max(?:imum)? context)\D{0,40}(\d{3,8})"
    r"|(\d{3,8})\s*tokens?\D{0,30}(?:maximum|context)", re.I)
# DELTA de overflow (NÃO é o teto): minimax & co. dizem "context window exceeds limit (2013)" / "exceeded by
# 4096 tokens" — o número é o EXCESSO. Lê-lo como limite despencava a janela p/ ~6K (delta*3.2). Casa o número
# que vem logo depois de exceed(s/ed)/over/by, p/ IGNORÁ-LO na extração.
_CTX_DELTA = re.compile(r"(?:exceed(?:s|ed)?|over|by)\b\D{0,30}?(\d{3,8})", re.I)


def _extract_ctx_limit(msg: str) -> int | None:
    """O limite de contexto (tokens) reportado no erro, ou None. Faixa sã (256..10M) p/ não pegar lixo.
    Ignora número em posição de DELTA de overflow (senão o excesso vira 'limite' e a janela despenca)."""
    msg = msg or ""
    delta_spans = {m.span(1) for m in _CTX_DELTA.finditer(msg)}   # posições dos números-EXCESSO (a pular)
    for m in _CTX_LIMIT.finditer(msg):
        for gi in (1, 2):
            g = m.group(gi)
            if not g or m.span(gi) in delta_spans:    # vazio OU é o delta de overflow → não é teto
                continue
            try:
                v = int(g)
            except ValueError:
                continue
            if 256 <= v <= 10_000_000:
                return v
    return None
_POLICY = re.compile(r"content.?policy|content.?filter|safety|moderation|refus", re.I)
_NOTFOUND = re.compile(r"\b404\b|not found|model.*(does not exist|unavailable|invalid)", re.I)
_TIMEOUT = re.compile(r"timeout|timed out|deadline|read timed", re.I)
# Razões EXPANDIDAS (pesquisa #5 item 54 — error_classifier do Hermes, as que mudam a alavanca):
# billing ANCORADO (não a palavra nua 'billing' — um 429 de rate-limit que só MENCIONA "billing" num
# link de docs não é falta de crédito; o termo solto parqueava chave boa por 6h — bug do review #3).
_BILLING = re.compile(r"\b402\b|insufficient[_ ](quota|credit|balance|funds)|"
                      r"exceeded your current quota|billing (details|issue|problem)|"
                      r"(check|update|verify).{0,20}billing|billing.{0,20}(required|to continue)|"
                      r"payment required|credit balance is too low|purchase (more )?credits|"
                      r"quota exceeded|out of (credits?|quota)", re.I)
_NETWORK = re.compile(r"connection (reset|refused|aborted|error|broken)|name resolution|getaddrinfo|"
                      r"\bdns\b|network is unreachable|remote end closed|ssl|certificate verify|"
                      r"eof occurred", re.I)
_RETIRED = re.compile(r"decommissioned|model.*(retired|sunset)|"
                      r"(deprecated|sunset).*(removed|shut ?down|unavailable)|no longer supported", re.I)
_REGION = re.compile(r"not (available|supported) in your (country|region|location)|"
                     r"unsupported_country|region.{0,20}not.{0,20}supported", re.I)
_SUSPENDED = re.compile(r"account.{0,30}(suspended|deactivated|banned)|"
                        r"organization.{0,30}(disabled|restricted)", re.I)
_EMPTY = re.compile(r"resposta vazia|stream vazio|empty (response|completion)", re.I)


def _LONG_CTX_TIER(msg: str) -> bool:
    """True se o erro é de TIER de long-context: precisa de 'long context' E de um sinal de faixa/uso-extra
    ('extra usage'/'tier'/'not included'). 'tier' sozinho (ex.: 'rate limit do seu tier') NÃO casa — o
    discriminador é o 'long context' junto, p/ não confundir com throttle normal."""
    m = (msg or "").lower()
    return ("long context" in m or "long-context" in m) and (
        "extra usage" in m or "tier" in m or "not included" in m)


def classify(exc) -> ClassifiedError:
    """Mapeia uma exceção (status code e/ou mensagem) numa decisão acionável.

    ORDEM IMPORTA: billing ANTES de rate_limit (OpenAI manda 429 + "exceeded your current quota"
    quando é BILLING — backoff não resolve falta de crédito; rotacionar chave JÁ resolve), e
    model_retired/region/suspended antes dos genéricos 403/404."""
    s = _status_of(exc)
    msg = _msg_of(exc)                                  # inclui o motivo aninhado no body do provider
    if exc.__class__.__name__ == "EmptyResponse" or _EMPTY.search(msg):
        return ClassifiedError("empty_response", s, retryable=True, fallback=True)
    if (_BILLING.search(msg) or s == 402) and not _TRANSIENT_QUOTA.search(msg):
        # sem crédito NESTA chave/conta (sem sinal de reset): backoff é inútil — rotaciona JÁ e failover.
        # Cota TRANSITÓRIA (reset/try-again/window) NÃO entra aqui → cai no rate_limit abaixo e retenta.
        return ClassifiedError("billing", s, retryable=True, rotate_key=True, fallback=True)
    if (s == 429 or _RATE.search(msg)) and _LONG_CTX_TIER(msg):
        # 429 de TIER de long-context (Anthropic 'extra usage'+'long context', e qualquer proxy que repasse):
        # backoff não resolve (não é throttle) e failover queima a assinatura à toa — o request é grande demais
        # p/ a faixa INCLUÍDA. compress=True → mapeia p/ CONTEXT_OVERFLOW: o harness compacta e re-tenta o MESMO
        # provider. fallback=False p/ não pular pro backup antes de encolher. Multi-vendor (regex no corpo).
        return ClassifiedError("long_context_tier", s, retryable=True, compress=True, fallback=False)
    if s == 429 or _RATE.search(msg):
        return ClassifiedError("rate_limit", s, retryable=True, rotate_key=True, fallback=True,
                               retry_after=_retry_after_of(exc))
    if s in (503, 529) or _OVERLOAD.search(msg):
        return ClassifiedError("overloaded", s, retryable=True, rotate_key=False, fallback=True)
    if s == 413 or _CTX.search(msg):
        return ClassifiedError("context_overflow", s, retryable=True, compress=True,
                               context_limit=_extract_ctx_limit(msg))
    if _POLICY.search(msg):
        # NUNCA re-enviar o payload idêntico (nem p/ outro provider): vai ser recusado igual.
        # fallback=True fica p/ camadas que REFORMULAM antes de tentar de novo.
        return ClassifiedError("content_policy", s, retryable=False, fallback=True, never_repeat=True)
    if _SUSPENDED.search(msg):
        return ClassifiedError("account_suspended", s, retryable=False, fallback=True)
    if _REGION.search(msg):
        return ClassifiedError("region_blocked", s, retryable=False, fallback=True)
    if _RETIRED.search(msg):
        return ClassifiedError("model_retired", s, retryable=False, fallback=True)
    if s == 401 or _AUTH.search(msg):
        return ClassifiedError("auth", s, retryable=True, rotate_key=True, fallback=True)
    if s == 403 or _AUTHPERM.search(msg):
        return ClassifiedError("auth_permanent", s, retryable=False, fallback=True)
    if s == 404 or _NOTFOUND.search(msg):
        return ClassifiedError("not_found", s, retryable=False, fallback=True)
    if _TIMEOUT.search(msg):
        # timeout costuma ser contexto grande / modelo lento → vale ENCOLHER (compress) E trocar de
        # provider (fallback), não só re-tentar o mesmo no mesmo tamanho (era o que travava 6min e morria).
        return ClassifiedError("timeout", s, retryable=True, fallback=True, compress=True)
    if _NETWORK.search(msg):
        return ClassifiedError("network", s, retryable=True, fallback=True)
    if s == 400:
        return ClassifiedError("bad_request", s, retryable=False)
    if s in (500, 502) and _VALIDATION.search(msg):       # 5xx que é validação determinística → não retenta
        return ClassifiedError("bad_request", s, retryable=False, fallback=True)
    if s is not None and s >= 500:
        return ClassifiedError("server_error", s, retryable=True, fallback=True)
    return ClassifiedError("unknown", s, retryable=True)
