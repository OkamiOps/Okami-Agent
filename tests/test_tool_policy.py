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


class _NamedCh:
    def __init__(self, name):
        self.name = name


def test_surface_of_uses_channel_name():
    # #P1: channel.name vence o nome da classe (Slack/Discord/Mattermost têm name, não casam classe)
    assert surface_of(_NamedCh("slack")) == "slack"
    assert surface_of(_NamedCh("discord")) == "discord"
    assert surface_of(_NamedCh("mattermost")) == "mattermost"
    assert surface_of(_NamedCh("telegram")) == "telegram"
    assert surface_of(_NamedCh("telegram-group")) == "group"
    assert surface_of(_NamedCh("paperclip")) == "paperclip"
    assert surface_of(_NamedCh("")) == "cli"


def test_real_rest_channels_are_not_cli():
    # #P1 (bug de segurança): antes SlackChannel etc. caíam em 'cli' e ganhavam shell/processo
    from okami.channels.discord import DiscordChannel
    from okami.channels.mattermost import MattermostChannel
    from okami.channels.slack import SlackChannel
    assert surface_of(SlackChannel.__new__(SlackChannel)) == "slack"
    assert surface_of(DiscordChannel.__new__(DiscordChannel)) == "discord"
    assert surface_of(MattermostChannel.__new__(MattermostChannel)) == "mattermost"


def test_remote_rest_channels_deny_shell_and_process():
    for cname in ("slack", "discord", "mattermost"):
        reg = filter_registry(default_registry(), surface_of(_NamedCh(cname)))
        for t in ("run_shell", "process_start", "process_write", "process_signal", "process_kill", "spawn"):
            assert t not in reg, f"{cname} NÃO pode ter {t} (canal remoto)"
        assert "read_file" in reg and "respond" in reg and "task_complete" in reg   # mantém o seguro
