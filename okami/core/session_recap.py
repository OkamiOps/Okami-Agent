"""Recap de sessão SEM LLM (instantâneo) — resumo determinístico do que rolou.

Onde o `dump`/checkpoint precisam de um panorama BARATO da sessão (sem gastar token de modelo),
este módulo monta um resumo multi-linha a partir do `history` (pares USER/AGENT) e, opcionalmente,
dos `steps` (chamadas de ferramenta). Reporta: nº de turnos, top ferramentas com contagem
("run_shell×3"), arquivos tocados (args.path/src/dst) e o último pedido/resposta truncados.

Fail-safe de propósito: history torto, steps None, objeto sem `.args` — nada disso levanta; o pior
caso é uma linha a menos no recap. Texto que pode trazer segredo passa pelo `redact` antes de sair.
"""

from __future__ import annotations

from collections import Counter

from okami.core.redact import redact

_TRUNC = 120                                  # ~120 chars no pedido/resposta — recap é panorama, não transcript
_TOP_TOOLS = 5                                # top-5 ferramentas mais usadas
_PATH_KEYS = ("path", "src", "dst")           # de onde extraímos "arquivo tocado" nos args do step


def _trunc(text: str, n: int = _TRUNC) -> str:
    """Encurta `text` p/ ~n chars (com reticências) e mascara segredo — no-op p/ vazio/não-str."""
    if not text or not isinstance(text, str):
        return ""
    text = redact(text.strip())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _last(history, role: str) -> str:
    """Último texto de `role` ("USER"/"AGENT") no history, ou "" — tolera tuplas tortas."""
    for item in reversed(history or []):
        try:
            r, text = item[0], item[1]
        except (TypeError, IndexError, ValueError, KeyError):   # KeyError: item dict ({"role":...}) → item[0] explode
            continue
        if isinstance(r, str) and r.upper() == role:
            return text if isinstance(text, str) else ""
    return ""


def _count_turns(history) -> int:
    """Nº de turnos = pares user→agent. Conta quantos AGENT respondem após algum USER prévio."""
    turns, saw_user = 0, False
    for item in history or []:
        try:
            r = item[0]
        except (TypeError, IndexError, KeyError):   # KeyError: item dict → item[0] explode
            continue
        if not isinstance(r, str):
            continue
        ru = r.upper()
        if ru == "USER":
            saw_user = True
        elif ru == "AGENT" and saw_user:
            turns += 1
            saw_user = False                  # fecha o par; próximo AGENT precisa de novo USER
    return turns


def _scan_steps(steps):
    """Varre `steps` → (Counter de ferramentas, lista ordenada-única de arquivos tocados). Best-effort."""
    tools: Counter = Counter()
    files: list[str] = []
    seen: set[str] = set()
    for st in steps or []:
        if st is None:
            continue
        tool = getattr(st, "tool", None)
        if isinstance(tool, str) and tool:
            tools[tool] += 1
        args = getattr(st, "args", None)
        if isinstance(args, dict):
            for key in _PATH_KEYS:
                val = args.get(key)
                if isinstance(val, str) and val and val not in seen:
                    seen.add(val)
                    files.append(val)
    return tools, files


def build_recap(history, steps=None, n: int = 8) -> str:
    """Resumo multi-linha e instantâneo da sessão (sem LLM).

    history: lista de (role, text) com role "USER"/"AGENT".
    steps:   lista opcional de objetos com `.tool` (str) e `.args` (dict) — chamadas de ferramenta.
    n:        nº de itens (arquivos) a listar no recap (cap defensivo).

    Devolve string com: nº de turnos, top ferramentas com contagem, arquivos tocados, último pedido
    do user e última resposta do agente (truncados). Nunca levanta — no pior caso, recap mais curto.
    """
    try:
        lines: list[str] = []
        lines.append(f"Turnos: {_count_turns(history)}")

        tools, files = _scan_steps(steps)
        if tools:
            top = ", ".join(f"{name}×{cnt}" for name, cnt in tools.most_common(_TOP_TOOLS))
            lines.append(f"Ferramentas: {top}")
        if files:
            shown = files[: max(0, n)]
            extra = len(files) - len(shown)
            tail = f" (+{extra})" if extra > 0 else ""
            lines.append(f"Arquivos: {', '.join(shown)}{tail}")

        ask = _last(history, "USER")
        if ask:
            lines.append(f"Último pedido: {_trunc(ask)}")
        ans = _last(history, "AGENT")
        if ans:
            lines.append(f"Última resposta: {_trunc(ans)}")

        return "\n".join(lines)
    except Exception:                          # fail-safe absoluto: recap NUNCA derruba o caller
        return ""
