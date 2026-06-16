"""Reparo multi-passe de argumentos de tool-call malformados (#11, port do Hermes
agent/message_sanitization._repair_tool_call_arguments).

Modelo local (GLM-5.1 via Ollama, llama.cpp) cospe JSON truncado, vírgula sobrando, control-char cru,
Python None etc. → o proxy rejeita com HTTP 400 "invalid tool call arguments". Aqui aplicamos os
reparos comuns; se tudo falhar, devolve "{}" (melhor que derrubar a sessão). Tudo logado em WARNING.
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)


def _escape_control_chars_in_strings(s: str) -> str:
    """Escapa control-char CRU (<0x20, exceto os já-escapados) DENTRO de strings JSON. Fora de string,
    deixa como está (whitespace estrutural é válido)."""
    out: list[str] = []
    in_str = False
    esc = False
    for ch in s:
        if in_str:
            if esc:
                out.append(ch)
                esc = False
            elif ch == "\\":
                out.append(ch)
                esc = True
            elif ch == '"':
                out.append(ch)
                in_str = False
            elif ord(ch) < 0x20:
                out.append({"\n": "\\n", "\t": "\\t", "\r": "\\r"}.get(ch, f"\\u{ord(ch):04x}"))
            else:
                out.append(ch)
        else:
            if ch == '"':
                in_str = True
            out.append(ch)
    return "".join(out)


def _closing_suffix(s: str) -> str:
    """Sufixo de fechamento p/ estrutura aberta, na ORDEM correta (pilha, ciente de string/escape) —
    `{"b":[2,3` → `]}` (não `}]`). Ignora chaves/colchetes dentro de string."""
    stack: list[str] = []
    in_str = esc = False
    for ch in s:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch == "}" and stack and stack[-1] == "{":
            stack.pop()
        elif ch == "]" and stack and stack[-1] == "[":
            stack.pop()
    return "".join("}" if c == "{" else "]" for c in reversed(stack))


def repair_tool_call_arguments(raw_args, tool_name: str = "?") -> str:
    """Tenta reparar o JSON de argumentos da tool-call. Devolve JSON wire-válido, ou "{}" se irreparável."""
    raw = raw_args.strip() if isinstance(raw_args, str) else ""

    if not raw:
        logger.warning("args de tool-call vazios p/ %s → {}", tool_name)
        return "{}"
    if raw == "None":                                    # Python None literal
        logger.warning("args 'None' p/ %s → {}", tool_name)
        return "{}"

    # Passo 0: strict=False aceita control-char cru dentro de string; re-serializa wire-válido (caso mais
    # comum de modelo local, #12068).
    try:
        return json.dumps(json.loads(raw, strict=False), separators=(",", ":"))
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    fixed = raw
    fixed = re.sub(r",\s*([}\]])", r"\1", fixed)         # 1) tira vírgula antes de } ou ]
    fixed += _closing_suffix(fixed)                      # 2) fecha estrutura aberta na ORDEM certa (pilha)
    for _ in range(50):                                  # 3) tira chave/colchete a mais (bounded)
        try:
            json.loads(fixed)
            break
        except json.JSONDecodeError:
            if fixed.endswith("}") and fixed.count("}") > fixed.count("{"):
                fixed = fixed[:-1]
            elif fixed.endswith("]") and fixed.count("]") > fixed.count("["):
                fixed = fixed[:-1]
            else:
                break
    try:
        json.loads(fixed)
        logger.warning("args de tool-call reparados p/ %s: %s → %s", tool_name, raw[:80], fixed[:80])
        return fixed
    except json.JSONDecodeError:
        pass

    # Passo 4: escapa control-char dentro de string e retenta.
    try:
        escaped = _escape_control_chars_in_strings(fixed)
        if escaped != fixed:
            json.loads(escaped)
            logger.warning("args com control-char reparados p/ %s", tool_name)
            return escaped
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    logger.warning("args de tool-call irreparáveis p/ %s → {} (era: %s)", tool_name, raw[:80])
    return "{}"


__all__ = ["repair_tool_call_arguments"]
