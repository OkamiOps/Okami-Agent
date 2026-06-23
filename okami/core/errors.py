"""Classificador de falhas do AGENTE (nível harness) — superset do error_classifier de provider.

`okami/llm/errors.py` já classifica erro de PROVIDER (429/auth/overload/contexto…) e alimenta o
retry do TRANSPORTE — isso continua intocado. Aqui é o nível de cima: classifica TODA falha do
turno numa taxonomia única, incluindo o que o provider-classifier NÃO vê — falha de TOOL e
NEGAÇÃO da sandbox — e diz a AÇÃO sugerida (retry/escalate/ask_user/abort). É a base p/ decisão
consistente no harness e p/ o event log (replay/debug enxerga o PORQUÊ).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class FailureKind(str, Enum):
    TRANSIENT = "transient"                # timeout / 5xx / overloaded → tenta de novo
    RATE_LIMIT = "rate_limit"              # 429 → backoff/rotate/fallback
    AUTH = "auth"                          # 401 → rotaciona chave
    AUTH_PERMANENT = "auth_permanent"      # 403 / conta revogada → precisa de humano
    CONTEXT_OVERFLOW = "context_overflow"  # estourou → comprime e tenta
    CONTENT_POLICY = "content_policy"      # recusa/moderação → reformula/aborta
    NOT_FOUND = "not_found"                # modelo inexistente → failover/escala
    BAD_REQUEST = "bad_request"            # 400 → aborta (determinístico)
    TOOL_FAIL = "tool_fail"                # tool devolveu ok=False (exit≠0, arquivo não existe…)
    SANDBOX_DENY = "sandbox_deny"          # sandbox bloqueou (read-only, path-escape, permissão)
    INVALID_ACTION = "invalid_action"      # modelo emitiu ação não-parseável
    UNKNOWN = "unknown"


class Action(str, Enum):
    RETRY = "retry"          # transitório → tentar de novo
    ESCALATE = "escalate"    # subir p/ modelo mais forte
    ASK_USER = "ask_user"    # precisa de humano (auth, decisão)
    ABORT = "abort"          # determinístico → parar (repetir não resolve)


@dataclass
class Failure:
    kind: FailureKind
    retryable: bool
    action: Action
    reason: str
    status: int | None = None


_ACTION: dict[FailureKind, Action] = {
    FailureKind.TRANSIENT: Action.RETRY,
    FailureKind.RATE_LIMIT: Action.RETRY,
    FailureKind.AUTH: Action.RETRY,
    FailureKind.AUTH_PERMANENT: Action.ASK_USER,
    FailureKind.CONTEXT_OVERFLOW: Action.RETRY,
    FailureKind.CONTENT_POLICY: Action.ABORT,
    FailureKind.NOT_FOUND: Action.ESCALATE,
    FailureKind.BAD_REQUEST: Action.ABORT,
    FailureKind.TOOL_FAIL: Action.RETRY,
    FailureKind.SANDBOX_DENY: Action.ABORT,
    FailureKind.INVALID_ACTION: Action.RETRY,
    FailureKind.UNKNOWN: Action.RETRY,
}

# reason do okami.llm.errors.ClassifiedError → FailureKind (mantém UMA fonte de verdade pro provider)
_PROVIDER_MAP: dict[str, FailureKind] = {
    "rate_limit": FailureKind.RATE_LIMIT,
    "overloaded": FailureKind.TRANSIENT,
    "context_overflow": FailureKind.CONTEXT_OVERFLOW,
    "content_policy": FailureKind.CONTENT_POLICY,
    "auth": FailureKind.AUTH,
    "auth_permanent": FailureKind.AUTH_PERMANENT,
    "not_found": FailureKind.NOT_FOUND,
    "timeout": FailureKind.TRANSIENT,
    "bad_request": FailureKind.BAD_REQUEST,
    "server_error": FailureKind.TRANSIENT,
    "unknown": FailureKind.UNKNOWN,
    # razões expandidas (pesquisa #5 item 54) — o provider-layer já rotacionou/failover; aqui é o
    # que sobra quando TUDO falhou: billing/suspenso/região precisam de humano, rede é transitório.
    "billing": FailureKind.AUTH_PERMANENT,
    "account_suspended": FailureKind.AUTH_PERMANENT,
    "region_blocked": FailureKind.AUTH_PERMANENT,
    "model_retired": FailureKind.NOT_FOUND,
    "network": FailureKind.TRANSIENT,
    "empty_response": FailureKind.TRANSIENT,
}

_SANDBOX = re.compile(r"sandbox|read-only|fora do workspace|path.?escape|bloquead|permission denied|operation not permitted", re.I)
# Falha de tool que NA VERDADE é provider transitório (a tool chamou um modelo auxiliar): repetir IGUAL só
# martela a cota — o loop deve ESPERAR, não tratar como "abordagem quebrada".
_TOOL_TRANSIENT = re.compile(r"rate.?limit|too many requests|overloaded|sobrecarregad|temporariamente|"
                            r"try again in|tente de novo em|\b429\b|\b503\b|\b502\b|timed?.?out|\btimeout\b", re.I)


def _mk(kind: FailureKind, reason: str, *, status: int | None = None) -> Failure:
    action = _ACTION[kind]
    return Failure(kind, action in (Action.RETRY, Action.ESCALATE), action, (reason or "").strip()[:160], status)


def _first_line(text: str) -> str:
    for ln in (text or "").splitlines():
        if ln.strip():
            return ln.strip()
    return (text or "").strip()


def classify_provider(exc) -> Failure:
    """Falha de provider/transporte → reusa o classifier de provider e mapeia p/ a taxonomia única."""
    from okami.llm.errors import classify as _classify
    ce = _classify(exc)
    return _mk(_PROVIDER_MAP.get(ce.reason, FailureKind.UNKNOWN), ce.reason, status=ce.status)


# Mensagem HUMANA por motivo de falha — o usuário no chat vê isto em vez de "provider falhou: overloaded".
# Diz O QUE houve e O QUE fazer. Já reflete que o fallback automático foi tentado e também não rolou.
_FRIENDLY = {
    "overloaded": ("o modelo está sobrecarregado agora (e o fallback também não respondeu). "
                   "Tente de novo em alguns instantes — costuma normalizar rápido."),
    "rate_limit": ("bati no limite de uso do provedor (rate limit). Espere um pouco e tente de novo, "
                   "ou troque de modelo com /model."),
    "auth": "a credencial do provedor falhou — refaça o login (ex.: `okami login`) e tente de novo.",
    "auth_permanent": "a credencial do provedor está inválida/expirada — refaça o login e tente de novo.",
    "context_overflow": ("a conversa ficou longa demais p/ a janela do modelo. Use /compact p/ resumir "
                         "ou /new p/ começar limpo."),
    "content_policy": "o provedor recusou o conteúdo por política. Reformule o pedido.",
    "timeout": ("o modelo demorou demais p/ responder (e o fallback também). Tente de novo, ou use um "
                "modelo mais rápido com /model."),
    "server_error": "o provedor teve um erro interno (e o fallback também). Tente de novo em instantes.",
    "billing": ("a conta do provedor está sem crédito/cota (billing). Verifique o plano/saldo, "
                "ou troque de modelo com /model."),
    "network": "a conexão com o provedor caiu (rede). Verifique a internet e tente de novo.",
    "model_retired": "esse modelo foi descontinuado pelo provedor. Escolha outro com /model.",
    "account_suspended": "a conta no provedor está suspensa — resolva com o provedor antes de tentar de novo.",
    "region_blocked": "o provedor não atende sua região p/ esse modelo. Escolha outro com /model.",
    "empty_response": "o modelo devolveu resposta vazia repetidamente. Tente de novo ou troque com /model.",
}


def friendly_failure(reason: str) -> str:
    """Frase humana e acionável p/ um motivo de falha de provider. Desconhecido → frase genérica
    com o motivo cru (não engole a informação)."""
    r = (reason or "").strip().lower()
    if r in _FRIENDLY:
        return _FRIENDLY[r]
    return f"não consegui falar com o modelo agora ({reason}). Tente de novo em instantes."


def classify_tool(result) -> Failure:
    """Falha de tool (ToolResult ok=False ou exceção): distingue NEGAÇÃO de sandbox de falha comum."""
    text = getattr(result, "output", None)
    if text is None:
        text = str(result)
    if _SANDBOX.search(text):
        return _mk(FailureKind.SANDBOX_DENY, _first_line(text))
    if _TOOL_TRANSIENT.search(text):            # tool que chamou modelo aux levou 429/sobrecarga → NÃO é a
        return _mk(FailureKind.RATE_LIMIT, _first_line(text))   # tool quebrada; repetir IGUAL martela a cota
    return _mk(FailureKind.TOOL_FAIL, _first_line(text))


def classify(obj) -> Failure:
    """Despacho genérico: exceção → provider; objeto com .ok/.output → tool; senão UNKNOWN."""
    if isinstance(obj, BaseException):
        return classify_provider(obj)
    if hasattr(obj, "ok") and hasattr(obj, "output"):
        return classify_tool(obj)
    return _mk(FailureKind.UNKNOWN, str(obj)[:120])
