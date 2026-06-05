"""Parsing de AÇÃO (protocolo JSON-em-texto, model-agnóstico) + Action + action_schema (§3.2)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from okami.core.tools import Tool


FUTURE_INTENT = re.compile(
    r"\b(vou|irei|em seguida|depois eu|let me|i['’]?ll|i will|next i|i'm going to)\b",
    re.IGNORECASE,
)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)   # bloco fenced (conteúdo bruto)


def _balanced_json_objects(s: str) -> list[str]:
    """Extrai objetos {...} BALANCEADOS, ciente de strings/escapes — robusto a chaves dentro do content."""
    out, i, n = [], 0, len(s)
    while i < n:
        if s[i] == "{":
            depth, j, in_str, esc = 0, i, False, False
            while j < n:
                c = s[j]
                if in_str:
                    if esc:
                        esc = False
                    elif c == "\\":
                        esc = True
                    elif c == '"':
                        in_str = False
                elif c == '"':
                    in_str = True
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        out.append(s[i:j + 1])
                        i = j
                        break
                j += 1
            else:
                break   # chave aberta sem fechar até o fim do texto
        i += 1
    return out
# Verbo de AÇÃO no pedido → o agente DEVE executar uma ferramenta, não só falar (backstop p/ modelo fraco).
_ACTION_RE = re.compile(
    r"\b(cri[ae]|cri[ae]r|faç[ao]|faz|edit|alter|mud[ae]|atualiz|rod[ae]|execut|implement|"
    r"refator|consert|corrij|arrum|ger[ae]|ger[ae]r|escrev|escrev[ae]|instal|configur|delet|"
    r"apag|remov|adicion|comit|build|create|fix|run|write|generate|install|add|delete|deploy|"
    # inspeção também EXIGE agir (self-review #10: "analisa a pasta" → liste/leia, não "vou analisar"):
    r"analis|examin|inspecion|verific|procur|encontr|mostr|busc|lista|listar|leia|ler|"
    r"search|find|show|check|analyze|inspect|look)",
    re.IGNORECASE)


@dataclass
class Action:
    tool: str
    args: dict


def _action_from_tool_calls(tool_calls) -> Action | None:
    """Primeira tool-call NATIVA (function-calling) → Action. None se vazio. Convive com o protocolo JSON."""
    for tc in (tool_calls or []):
        name = tc.get("name") if isinstance(tc, dict) else None
        if not name:
            continue
        raw = tc.get("arguments") or "{}"
        try:
            args = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except json.JSONDecodeError:
            args = {}
        return Action(name, args if isinstance(args, dict) else {})
    return None


def parse_action(text: str) -> Action | None:
    """Extrai a ÚLTIMA ação JSON. Prioriza bloco fenced ```json```; senão varre o texto com parser
    BALANCEADO (robusto a {} dentro de write_file/markdown). None se não houver ação válida."""
    candidates: list[str] = []
    for blk in _FENCE.findall(text):                 # 1) blocos fenced (o agente é instruído a usar)
        candidates += _balanced_json_objects(blk)
    if not candidates:
        candidates = _balanced_json_objects(text)    # 2) fallback: texto inteiro, balanceado
    for raw in reversed(candidates):
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("tool"), str):
            return Action(obj["tool"], obj.get("args") or {})
    return None


def action_schema(registry: dict[str, Tool]) -> dict:
    """JSON schema da ação — usado no constrained decoding (§3.5)."""
    return {
        "type": "object",
        "properties": {
            "tool": {"type": "string", "enum": list(registry.keys())},
            "args": {"type": "object"},
        },
        "required": ["tool", "args"],
    }
