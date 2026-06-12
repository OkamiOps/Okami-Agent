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
    # inspeção/avaliação também EXIGE agir (self-review #10: "analisa a pasta" → liste/leia, não "vou…"):
    r"analis|examin|inspecion|verific|procur|encontr|mostr|busc|lista|listar|leia|ler|"
    r"test[ae]|teste|testar|compar|avali|revis|ach[ae]|achar|audita|"
    r"search|find|show|check|analyze|inspect|look|review|evaluate|compare)",
    re.IGNORECASE)


@dataclass
class Action:
    tool: str
    args: dict


def _actions_from_tool_calls(tool_calls) -> list[Action]:
    """TODAS as tool-calls NATIVAS (function-calling) → [Action] na ordem. Vazio se nenhuma. Hermes roda
    todas as tool_calls de um turno; aqui devolvemos todas e o loop decide o que dá pra rodar em lote."""
    out: list[Action] = []
    for tc in (tool_calls or []):
        name = tc.get("name") if isinstance(tc, dict) else None
        if not name:
            continue
        raw = tc.get("arguments") or "{}"
        try:
            args = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except json.JSONDecodeError:
            if raw.rstrip() and not raw.rstrip().endswith(("}", "]")):
                continue                             # args TRUNCADOS (stream cortou) → NÃO executa parcial
            args = {}
        out.append(Action(name, args if isinstance(args, dict) else {}))
    return out


def _action_from_tool_calls(tool_calls) -> Action | None:
    """Primeira tool-call NATIVA → Action (back-compat). None se vazio."""
    acts = _actions_from_tool_calls(tool_calls)
    return acts[0] if acts else None


def parse_action(text: str) -> Action | None:
    """Extrai a ÚLTIMA ação JSON. Prioriza bloco fenced ```json```; senão varre o texto com parser
    BALANCEADO (robusto a {} dentro de write_file/markdown). None se não houver ação válida."""
    acts = parse_actions(text)
    return acts[-1] if acts else None


def parse_actions(text: str) -> list[Action]:
    """TODAS as ações na ORDEM (batch — Hermes roda várias por turno). Suporta: vários blocos
    {"tool","args"} no texto, OU um envelope {"actions":[{...},{...}]}, OU um array top-level [{...}].
    Vazio se não houver ação válida."""
    candidates: list[str] = []
    for blk in _FENCE.findall(text):                 # 1) blocos fenced (o agente é instruído a usar)
        candidates += _balanced_json_objects(blk)
    if not candidates:
        candidates = _balanced_json_objects(text)    # 2) fallback: texto inteiro, balanceado
    out: list[Action] = []
    for raw in candidates:                           # ordem do documento (batch executa nessa ordem)
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for d in (obj if isinstance(obj, list) else [obj]):
            if not isinstance(d, dict):
                continue
            if isinstance(d.get("actions"), list):   # envelope batch {"actions":[...]}
                out += [Action(a["tool"], a.get("args") or {}) for a in d["actions"]
                        if isinstance(a, dict) and isinstance(a.get("tool"), str)]
            elif isinstance(d.get("tool"), str):
                out.append(Action(d["tool"], d.get("args") or {}))
    return out


def _unclosed_tail(text: str) -> str:
    """O trecho do texto a partir do primeiro `{` que NÃO fecha (candidato a JSON truncado). '' se
    todos os braces fecham."""
    s = text or ""
    for obj in _balanced_json_objects(s):            # remove os objetos COMPLETOS; sobra o truncado
        s = s.replace(obj, " ", 1)
    i = s.find("{")
    return s[i:] if i >= 0 else ""


def truncated_action_tail(text: str) -> bool:
    """O texto termina no MEIO de um JSON de ação (cortado por limite/queda)? Detecta `{` aberto sem
    fechar com cara de ação no rabo do texto — caso em que executar/continuar o parcial seria loteria.
    O harness NUNCA executa um JSON truncado (ele nem parseia); isto serve p/ ENSINAR em vez de só
    rejeitar genérico, e p/ o prompt de continuação certo ("re-emita menor", não "continue do meio")."""
    tail = _unclosed_tail(text)
    return bool(tail) and ('"tool"' in tail or tail.lstrip().startswith('{"'))


_TOOL_NAME = re.compile(r'"tool"\s*:\s*"([^"]*)')


def truncated_action_name(text: str) -> str | None:
    """Nome da tool no JSON TRUNCADO do fim do texto (None se não termina truncado, ou se o corte
    veio antes do nome). Decide a continuação certa: respond/task_complete truncado → CONTINUAR
    (preserva o relatório longo); write_file gigante → re-emitir com args MENORES."""
    tail = _unclosed_tail(text)
    if not tail or not ('"tool"' in tail or tail.lstrip().startswith('{"')):
        return None
    m = _TOOL_NAME.search(tail)
    return (m.group(1) or None) if m else None


def detect_malformed(text: str) -> str | None:
    """Diagnóstico que ENSINA (pesquisa #5 item 8, Hermes _repair_tool_call) quando nenhuma ação
    parseou mas o modelo claramente TENTOU emitir uma: JSON truncado → re-emitir menor (sem executar
    o parcial); JSON inválido → erro sintético com o motivo exato. None = não parece tentativa de ação."""
    if truncated_action_tail(text):
        return ("Seu JSON de ação foi TRUNCADO (abre '{' e não fecha). NÃO re-emita igual: reduza os "
                "args (quebre conteúdo grande em pedaços menores) e reenvie a ação COMPLETA.")
    candidates: list[str] = []
    for blk in _FENCE.findall(text or ""):
        candidates += _balanced_json_objects(blk) or [blk.strip()]
    for raw in candidates:
        if not raw or '"tool"' not in raw:
            continue
        try:
            json.loads(raw)
        except json.JSONDecodeError as e:
            return (f"Seu bloco json de ação é INVÁLIDO ({e.msg}, linha {e.lineno}, coluna {e.colno}). "
                    "Regras: aspas DUPLAS em chaves e strings, sem comentários, sem vírgula sobrando — "
                    'um objeto {"tool": "...", "args": {...}}. Reenvie corrigido.')
    return None


def prose_outside_action(text: str) -> str:
    """A 'fala' livre do modelo SEM os blocos de ação JSON. Recupera a resposta quando o envelope
    respond/task_complete vem com message VAZIO mas o modelo escreveu a resposta em PROSA (modelo fraco
    que conversa fora do JSON e manda um respond vazio) — senão a fala se perdia e virava '(COMPLETE)'."""
    s = _FENCE.sub(" ", text or "")                  # remove blocos ```...```
    for obj in _balanced_json_objects(s):            # remove objetos JSON que sejam AÇÃO ({"tool": ...})
        try:
            d = json.loads(obj)
        except json.JSONDecodeError:
            continue
        if isinstance(d, dict) and isinstance(d.get("tool"), str):
            s = s.replace(obj, " ", 1)
    return "\n".join(ln.rstrip() for ln in s.splitlines() if ln.strip()).strip()


def action_schema(registry: dict[str, Tool]) -> dict:
    """JSON schema da ação — constrained decoding (§3.5). Aceita UMA ação {tool,args} OU um LOTE
    {"actions":[{tool,args}, …]} (batch de passos de LEITURA independentes — Hermes roda vários por turno).
    `strict:False` no provider → o schema é guia, não trava (modelo emite uma ou várias)."""
    one = {
        "type": "object",
        "properties": {
            "tool": {"type": "string", "enum": list(registry.keys())},
            "args": {"type": "object"},
        },
        "required": ["tool", "args"],
    }
    return {
        "type": "object",
        "properties": {
            "tool": {"type": "string", "enum": list(registry.keys())},
            "args": {"type": "object"},
            "actions": {"type": "array", "items": one},   # lote opcional (passos de leitura independentes)
        },
    }
