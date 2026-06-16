"""Tool computer_use (#embutido, opt-in, approval-gated) — controla mouse/teclado/tela do SO.

SEGURANÇA EM CAMADAS: (1) check_fn exige opt-in EXPLÍCITO (`computer_use.enabled: true`) + backend presente
→ desligado por padrão; (2) HARDLINE-block recusa combos destrutivos (logout/lock/lixeira) ANTES de tocar
no SO, sem override; (3) danger="dangerous" no ToolSpec → cada ação passa por go/no-go. Decisão de escopo
revista: o dono optou por EMBUTIR (era só-MCP no #17).
"""
from __future__ import annotations

from okami.core.tools.base import Tool, ToolResult, _safe_path
from okami.core.desktop.dispatcher import is_hardline, validate_action


class ComputerUse(Tool):
    name = "computer_use"
    description = ("Controla o DESKTOP do dono (mouse/teclado/tela). action=screenshot (tira foto da tela) | "
                   "click/right_click/double_click/move (x,y) | type (text) | key (keys, ex.: 'cmd+c') | "
                   "scroll (amount). DESLIGADO por padrão (computer_use.enabled). Ação perigosa → go/no-go; "
                   "combos destrutivos (logout/lock/lixeira) são recusados sempre.")
    args_schema = {"action": "screenshot|click|right_click|double_click|move|type|key|scroll",
                   "x": "(coord) inteiro", "y": "(coord) inteiro", "text": "(type) o que digitar",
                   "keys": "(key) combinação, ex.: cmd+c", "amount": "(scroll) linhas", "path": "(screenshot) saída"}
    required = ("action",)

    def __init__(self, _backend=None):
        self._backend = _backend

    def check(self) -> str | None:
        """Indisponível a menos que o dono ATIVE (computer_use.enabled) E haja backend (cliclick/pyautogui)."""
        try:
            from okami.config import load_config
            cfg = load_config()
        except Exception:  # noqa: BLE001
            return "config indisponível p/ computer_use"
        cu = getattr(cfg, "computer_use", None)
        enabled = cu.get("enabled") if isinstance(cu, dict) else getattr(cu, "enabled", False)
        if not enabled:
            return "computer_use desligado — ative com `computer_use.enabled: true` no okami.yaml"
        from okami.core.desktop.backend import get_backend
        if get_backend() is None:
            return "sem backend de desktop — instale cliclick (macOS) ou rode `okami deps install desktop.pyautogui`"
        return None

    def run(self, args, ctx):
        action = str(args.get("action") or "")
        ok, reason = validate_action(action, args)
        if not ok:
            return ToolResult(False, f"computer_use: {reason}")
        hl = is_hardline(action, args)
        if hl:
            return ToolResult(False, f"computer_use RECUSADO: {hl}")
        backend = self._backend
        if backend is None:
            from okami.core.desktop.backend import get_backend
            backend = get_backend()
        if backend is None:
            return ToolResult(False, "computer_use: sem backend de desktop disponível.")
        try:
            if action == "screenshot":
                out = _safe_path(ctx, args.get("path") or "screenshot.png")
                p = backend.screenshot(str(out))
                return ToolResult(True, f"screenshot da tela salvo: {p}", effect=False,
                                  content=_image_block(str(p)))
            rest = {k: v for k, v in args.items() if k != "action"}
            backend.act(action, rest)
            return ToolResult(True, f"computer_use ok: {action}", effect=True)
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, f"computer_use falhou: {e}")


def _image_block(path: str):
    """Embute o screenshot como bloco de imagem (o modelo VÊ a tela). Best-effort → None se falhar."""
    try:
        import base64
        from pathlib import Path as _P
        raw = _P(path).read_bytes()
        if not raw or len(raw) > 6 * 1024 * 1024:          # tela vazia ou grande demais → só o caminho
            return None
        uri = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
        return [{"type": "image_url", "image_url": {"url": uri}}]
    except Exception:  # noqa: BLE001
        return None
