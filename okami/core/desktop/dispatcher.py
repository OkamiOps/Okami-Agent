"""Dispatcher do computer-use — validação de ação + HARDLINE-block (#port Hermes tools/computer_use).

Camada PURA/testável (sem tocar no SO): valida o schema da ação e RECUSA incondicionalmente combinações
destrutivas (logout/lock/shutdown/empty-trash) — antes mesmo do go/no-go, sem override por /yolo. O backend
(mover mouse/teclado/screenshot) é injetado pela tool.
"""
from __future__ import annotations

VALID_ACTIONS = frozenset({
    "screenshot", "click", "right_click", "double_click", "move", "type", "key", "scroll",
})
_NEEDS_XY = frozenset({"click", "right_click", "double_click", "move", "scroll"})

def _norm_combo(keys: str) -> str:
    parts = [k.strip().lower() for k in str(keys or "").replace(" ", "").split("+") if k.strip()]
    # aliases comuns
    alias = {"control": "ctrl", "command": "cmd", "option": "alt", "del": "delete", "return": "enter"}
    parts = [alias.get(p, p) for p in parts]
    return "+".join(sorted(parts))


# Combinações de teclas HARDLINE (recusadas sempre): logout/lock/shutdown/fechar-tudo/lixeira.
# Guardadas NORMALIZADAS (minúsculas + ordenadas) p/ casar com `_norm_combo` no lookup.
_HARDLINE_RAW = (
    "cmd+q", "cmd+shift+q", "cmd+ctrl+q", "ctrl+cmd+q",          # quit Finder / logout / lock (macOS)
    "ctrl+cmd+eject", "cmd+ctrl+eject",                          # sleep/shutdown
    "alt+f4",                                                    # fechar app (cadeia de logout no Win)
    "ctrl+alt+delete", "alt+ctrl+delete",                       # Win security screen
    "cmd+delete", "shift+delete", "cmd+shift+delete",           # apagar / esvaziar lixeira
)
_HARDLINE_KEYS = frozenset(_norm_combo(c) for c in _HARDLINE_RAW)


def validate_action(action: str, args: dict) -> tuple[bool, str]:
    """Schema da ação bem-formado? (sem backend). Devolve (ok, motivo)."""
    if action not in VALID_ACTIONS:
        return False, f"ação desconhecida: {action!r} (use: {', '.join(sorted(VALID_ACTIONS))})"
    if action in _NEEDS_XY:
        for k in ("x", "y"):
            v = args.get(k)
            if not isinstance(v, int) or isinstance(v, bool):
                return False, f"ação {action!r} precisa de {k} inteiro"
            if v < 0:
                return False, f"coordenada {k}={v} negativa"
    if action == "type" and not str(args.get("text") or "").strip():
        return False, "ação 'type' precisa de 'text' não-vazio"
    if action == "key" and not str(args.get("keys") or "").strip():
        return False, "ação 'key' precisa de 'keys' (ex.: 'cmd+c')"
    return True, ""


def is_hardline(action: str, args: dict) -> str | None:
    """Razão se a ação é HARDLINE (recusa incondicional), senão None. Cobre combos de teclas destrutivos."""
    if action == "key":
        combo = _norm_combo(args.get("keys", ""))
        if combo in _HARDLINE_KEYS:
            return f"combinação de teclas bloqueada (destrutiva/logout/lock): {args.get('keys')!r}"
    return None


__all__ = ["VALID_ACTIONS", "validate_action", "is_hardline"]
