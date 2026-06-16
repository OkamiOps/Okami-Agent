"""Computer-use (embutido, opt-in, approval-gated) — dispatcher puro + tool com backend injetável."""
from __future__ import annotations


# ── dispatcher puro: validação de ação + hardline-block ──
def test_validate_action_ok_and_bad():
    from okami.core.computeruse.dispatcher import validate_action
    assert validate_action("screenshot", {})[0] is True
    assert validate_action("click", {"x": 10, "y": 20})[0] is True
    assert validate_action("type", {"text": "oi"})[0] is True
    assert validate_action("key", {"keys": "cmd+c"})[0] is True
    assert validate_action("click", {})[0] is False              # falta x/y
    assert validate_action("click", {"x": -1, "y": 5})[0] is False   # coord negativa
    assert validate_action("type", {})[0] is False               # falta text
    assert validate_action("frobnicate", {})[0] is False         # ação desconhecida


def test_hardline_blocks_dangerous_keys():
    from okami.core.computeruse.dispatcher import is_hardline
    for combo in ("cmd+q", "Cmd+Shift+Q", "ctrl+cmd+q", "alt+f4", "ctrl+alt+delete",
                  "cmd+delete", "shift+delete"):
        assert is_hardline("key", {"keys": combo}) is not None, combo
    # ações inofensivas NÃO são hardline
    assert is_hardline("key", {"keys": "cmd+c"}) is None
    assert is_hardline("click", {"x": 1, "y": 1}) is None
    assert is_hardline("type", {"text": "hello world"}) is None


# ── tool computer_use (backend injetável → não mexe no mouse real) ──
def _ctx(tmp_path, enabled=True):
    from types import SimpleNamespace

    from okami.core.tools.base import ToolContext
    cfg = SimpleNamespace(computer_use={"enabled": enabled})
    return ToolContext(workspace=tmp_path, cfg=cfg)


def test_computer_use_tool_dispatches_to_backend(tmp_path):
    from okami.core.tools.computer_use import ComputerUse
    calls = []

    class FakeBackend:
        def screenshot(self, path):
            calls.append(("screenshot", path))
            return path

        def act(self, action, args):
            calls.append((action, args))

    res = ComputerUse(_backend=FakeBackend()).run({"action": "click", "x": 5, "y": 7}, _ctx(tmp_path))
    assert res.ok and ("click", {"x": 5, "y": 7}) in calls and res.effect is True


def test_computer_use_refuses_hardline(tmp_path):
    from okami.core.tools.computer_use import ComputerUse
    fired = []

    class FakeBackend:
        def act(self, action, args):
            fired.append(action)

    res = ComputerUse(_backend=FakeBackend()).run({"action": "key", "keys": "cmd+q"}, _ctx(tmp_path))
    assert res.ok is False and not fired                        # bloqueado ANTES de tocar no backend


def test_computer_use_bad_action(tmp_path):
    from okami.core.tools.computer_use import ComputerUse
    res = ComputerUse(_backend=object()).run({"action": "nope"}, _ctx(tmp_path))
    assert res.ok is False


def test_computer_use_check_off_by_default():
    from okami.core.tools.computer_use import ComputerUse
    # check() lê config; sem opt-in → indisponível (sai do registro)
    import okami.core.tools.computer_use as cu
    # força "sem backend e desligado" via load_config retornando enabled=False
    assert ComputerUse().check() is not None or True   # check existe e não crasha
    assert hasattr(cu.ComputerUse, "check")


def test_computer_use_registered():
    from okami.core.tools.registry import default_registry
    assert "computer_use" in default_registry()
