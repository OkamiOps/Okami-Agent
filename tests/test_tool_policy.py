"""Tool policy por superfície (P1.4): cada surface tem um repertório diferente; terminais sempre ficam."""

from __future__ import annotations

from okami.core.tool_policy import filter_registry, surface_of
from okami.core.tools import default_registry


def test_telegram_denies_shell_keeps_safe_and_terminals():
    reg = filter_registry(default_registry(), "telegram")
    assert "run_shell" not in reg                       # remoto não roda shell por padrão
    assert "read_file" in reg and "respond" in reg and "task_complete" in reg


def test_group_is_most_restricted():
    reg = filter_registry(default_registry(), "group")
    for t in ("run_shell", "spawn", "generate_image", "write_file", "browse"):
        assert t not in reg                             # grupo: cap 'safe' + denylist
    assert "read_file" in reg and "respond" in reg


def test_subagent_cannot_spawn_but_keeps_shell():
    reg = filter_registry(default_registry(), "subagent")
    assert "spawn" not in reg and "run_shell" in reg    # anti-recursão, mas mantém o resto


def test_cli_is_the_full_surface_unchanged():
    reg = default_registry()
    assert filter_registry(reg, "cli") is reg           # sem config → mesmo objeto (nada filtrado)


def test_config_override_allow_beats_default_deny():
    cfg = {"surfaces": {"telegram": {"allow": ["run_shell"], "deny": ["read_file"]}}}
    reg = filter_registry(default_registry(), "telegram", config=cfg)
    assert "run_shell" in reg and "read_file" not in reg and "respond" in reg


def test_surface_of_maps_channel_classes():
    class TelegramChannel: ...
    class GroupChannel: ...
    class TerminalChannel: ...
    assert surface_of(TelegramChannel()) == "telegram"
    assert surface_of(GroupChannel()) == "group"
    assert surface_of(TerminalChannel()) == "cli"
