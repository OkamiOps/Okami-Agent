"""Filtros de saída do gateway (#9) — sanitiza erro de PROVIDER antes do chat.

O `redact` mascara segredo; este filtro é defesa-em-profundidade no boundary externo: um envelope cru
de erro do provider (HTTP body, request-id, "incorrect api key", policy interna) pode despejar
fragmento de chave / detalhe interno num inbox móvel. Mapeia p/ uma categoria curta e segura. Só age
quando o texto PARECE erro de provider — prosa legítima passa intacta.
"""
from __future__ import annotations

import re

# marcadores fortes de envelope de erro de PROVIDER (não casam prosa comum em PT).
_RATE = re.compile(r"rate.?limit|\b429\b|insufficient_quota|too many requests", re.IGNORECASE)
_OVERLOADED = re.compile(r"overloaded|\b529\b|\b503\b|service unavailable", re.IGNORECASE)
_AUTH = re.compile(r"incorrect api key|invalid[_ ]api[_ ]key|authentication|unauthorized|\b401\b|\b403\b"
                   r"|permission denied|api key", re.IGNORECASE)
_GENERIC = re.compile(r'"type"\s*:\s*"error"|x-request-id|request id|\b5\d\d\b.*error|internal server error',
                      re.IGNORECASE)


def looks_like_provider_error(text: str) -> bool:
    """Curto + marcador forte de erro de provider (evita reescrever prosa longa legítima)."""
    return bool(text) and len(text) < 1500 and bool(
        _RATE.search(text) or _OVERLOADED.search(text) or _AUTH.search(text) or _GENERIC.search(text))


def sanitize_provider_error(text: str) -> str:
    """Envelope cru de erro de provider → categoria curta e segura; texto normal passa inalterado."""
    if not looks_like_provider_error(text):
        return text
    if _RATE.search(text):
        return "o provedor está limitando a taxa agora (rate limit) — tente de novo em instantes."
    if _OVERLOADED.search(text):
        return "o provedor está sobrecarregado no momento — tente de novo em instantes."
    if _AUTH.search(text):
        return "falha de autenticação com o provedor — verifique a credencial (detalhe nos logs)."
    return "o provedor retornou um erro — o detalhe está nos logs."
