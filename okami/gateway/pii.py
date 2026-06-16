"""Redação de PII no caminho prompt->LLM, POR plataforma.

Complementa o `redact.py` (segredos/credenciais): aqui o alvo é PII de conversa — telefone e
ids numéricos longos — que NÃO precisa ir cru pro modelo. A política é por plataforma porque o
id cru às vezes é estrutural: no Discord a menção é montada com o id numérico (<@id>), então
mascará-lo quebraria a funcionalidade. Telegram/WhatsApp/Signal/BlueBubbles não dependem disso.

Conservador e fail-safe: best-effort, nunca levanta exceção que derrube o caller; fora das
plataformas seguras (ou em entrada vazia/não-str) devolve o texto INTACTO.
"""

from __future__ import annotations

import hashlib
import re

from okami.core.redact import redact

# Plataformas onde mascarar PII é seguro — o id cru NÃO é necessário p/ menção/roteamento.
# Discord fica DE FORA de propósito: a menção (<@123…>) exige o id numérico cru.
PII_SAFE_PLATFORMS: set[str] = {"telegram", "whatsapp", "signal", "bluebubbles"}

# Telefone internacional: opcional "+", DDI/DDD e grupos de dígitos separados por espaço/-/(),
# com pelo menos um separador (senão colide com qualquer número longo — esse caso vai pro id).
# Telefone — ESTREITO (achado da review #9: o regex frouxo comia data/CEP/decimal/IP). Exige um sinal
# REAL de telefone: '+' internacional, DDD entre parênteses, ou 3 grupos no formato de telefone.
_PHONE = re.compile(
    r"\+\d[\d\s().\-]{7,}\d"                      # internacional: +55 11 99999-8888
    r"|\(\d{2,3}\)\s?\d[\d\s.\-]{6,}\d"           # (11) 99999-8888
    r"|\b\d{3}[\s.\-]\d{3}[\s.\-]\d{4}\b"         # 555-123-4567 (US)
    r"|\b\d{2}[\s.\-]\d{4,5}[\s.\-]\d{4}\b"       # 11 99999-8888 (BR sem +)
)

# Id numérico longo (>=7 dígitos contíguos) — user-id, chat-id etc. Trocado por hash curto.
# Boundary por LETRA/DÍGITO (não \b): \b trata '_' como caractere de palavra, então 'chat_123456789' não
# era mascarado (id colado a '_' é comum). Já dígitos DENTRO de um token alfanumérico (hash/hex
# 'abc123456789def') ficam intactos — só mascara a corrida de dígitos que NÃO encosta em letra/dígito
# (permite '_', espaço, pontuação em volta).
_LONG_ID = re.compile(r"(?<![A-Za-z0-9])\d{7,}(?![A-Za-z0-9])")


def hash_id(x: str) -> str:
    """Hash determinístico curto de `x` (sha256 hex[:8]) — estável entre execuções.

    Determinístico de propósito: o modelo precisa reconhecer "o mesmo usuário" ao longo da
    conversa SEM ver o id real. Best-effort: coage p/ str e nunca explode."""
    try:
        return hashlib.sha256(str(x).encode("utf-8", "replace")).hexdigest()[:8]
    except Exception:
        return "????????"  # fail-safe: nunca derruba o caller


def redact_pii(text: str, platform: str) -> str:
    """Mascara PII (telefone->`[telefone]`, id longo->`hash_id`) SE `platform` é segura.

    Fora de `PII_SAFE_PLATFORMS` (ou entrada vazia/não-str) devolve `text` intacto — o id cru
    pode ser estrutural (menção no Discord). Best-effort: qualquer erro → texto original."""
    if not text or not isinstance(text, str):
        return text
    if platform not in PII_SAFE_PLATFORMS:
        return text
    try:
        # passa o redator de segredos antes — defesa em profundidade no caminho pro LLM
        out = redact(text)
        out = _PHONE.sub("[telefone]", out)          # telefone primeiro (consome os dígitos)
        out = _LONG_ID.sub(lambda m: hash_id(m.group(0)), out)  # id longo restante -> hash
        return out
    except Exception:
        return text  # fail-safe: nunca levanta p/ o caller
