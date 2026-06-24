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
_STRIP_FIELDS = ("reasoning_content", "reasoning", "reasoning_details", "finish_reason", "_thinking",
                 "_thinking_prefill", "thinking", "thinking_blocks", "redacted_thinking", "tool_name",
                 "timestamp", "codex_reasoning_items", "codex_message_items")


def _strip_nonstandard(m: dict) -> dict:
    """Tira do objeto-mensagem os campos que um provider ESTRITO recusa: os explícitos de _STRIP_FIELDS MAIS,
    genericamente, QUALQUER chave top-level começada com '_' (belt do Hermes: marcadores internos nossos/de
    plugin/MCP que vazariam num 400). Os campos VÁLIDOS do OpenAI (role/content/tool_calls/tool_call_id/name)
    nunca começam com '_' nem estão na lista."""
    return {k: v for k, v in m.items() if k not in _STRIP_FIELDS and not k.startswith("_")}


def header_safe_key(key):
    """Devolve a API key pronta p/ virar header HTTP, ou None se for impossível. Multi-vendor: httpx (litellm)
    e urllib (transports nativos) codificam o header em latin-1 — uma key com CJK/emoji/NBSP estoura
    UnicodeEncodeError e derruba o turno ANTES de chamar o modelo. Salva o salvável (tira quebras/tabs de
    paste acidental nas bordas e no meio) e RECUSA o que não é header-safe (não-ASCII ou control char)."""
    if not isinstance(key, str):
        return None
    k = key.strip().replace("\r", "").replace("\n", "").replace("\t", "")   # quebras/tabs de paste
    if not k or not k.isascii():
        return None                                  # vazio OU não-ASCII (latin-1 estoura no header)
    if any(ord(c) < 0x20 or ord(c) == 0x7f for c in k):
        return None                                  # control char restante → header inválido
    return k


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
            if any(k in m for k in _STRIP_FIELDS) or any(k.startswith("_") for k in m):
                m = _strip_nonstandard(m)             # campo estranho/_-prefixado → tira (provider estrito 400)
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


__all__ = ["sanitize_text", "sanitize_messages", "header_safe_key"]
