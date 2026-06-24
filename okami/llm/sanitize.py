"""Sanitização de mensagens ANTES de chamar o modelo (port do message_sanitization do Hermes).

Modelos LOCAIS (GLM/Qwen via LMStudio/Ollama) às vezes emitem SURROGATES solitários (U+D800–DFFF) e
control chars. O SDK serializa a request com `.encode('utf-8')`/json.dumps ANTES de mandar — e um
surrogate solitário estoura isso com UnicodeEncodeError, derrubando o turno INTEIRO sem nem chamar o
modelo. Mais crítico p/ modelo local (cloud raramente emite lixo unicode). Limpa fora-de-banda, copiando
(não muta o histórico), e FAIL-OPEN: qualquer erro na limpeza → devolve a mensagem original.
"""
from __future__ import annotations

import re

# surrogates solitários (U+D800–DFFF) + control chars de C0/C1 que quebram encode/json — preservando
# \t (\x09), \n (\x0a), \r (\x0d), que são whitespace legítimo.
_BAD = re.compile(r"[\ud800-\udfff\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Campos NÃO-padrão que um provider ESTRITO (Mistral/Fireworks/…) recusa no objeto-mensagem → 400. Aparecem
# quando um Completion de modelo de reasoning é ecoado/persistido cru. Tira ANTES de mandar. Os campos
# VÁLIDOS do OpenAI (role/content/tool_calls/tool_call_id/name) NUNCA entram aqui.
_STRIP_FIELDS = ("reasoning_content", "reasoning", "finish_reason", "_thinking", "_thinking_prefill",
                 "thinking", "thinking_blocks", "redacted_thinking")


def sanitize_text(s):
    """Remove surrogates solitários e control chars de UM texto. Não-str / vazio → devolve como veio."""
    if not isinstance(s, str) or not s:
        return s
    return _BAD.sub("", s)


def sanitize_messages(messages):
    """Limpa o `content` (str OU lista de blocos com `text`) de cada mensagem, copiando. Fail-open."""
    try:
        out = []
        for m in messages or []:
            if not isinstance(m, dict):
                out.append(m)
                continue
            if any(k in m for k in _STRIP_FIELDS):       # campo estranho no objeto → tira (provider estrito 400)
                m = {k: v for k, v in m.items() if k not in _STRIP_FIELDS}
            c = m.get("content")
            if isinstance(c, str):
                m = {**m, "content": sanitize_text(c)}
            elif isinstance(c, list):
                blocks = []
                for b in c:
                    if isinstance(b, dict) and isinstance(b.get("text"), str):
                        b = {**b, "text": sanitize_text(b["text"])}
                    blocks.append(b)
                m = {**m, "content": blocks}
            out.append(m)
        return out
    except Exception:  # noqa: BLE001 — sanitização nunca pode derrubar o turno; pior caso = original
        return messages


__all__ = ["sanitize_text", "sanitize_messages"]
