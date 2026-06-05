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


# ---------------- Paperclip por papel (#P1) ----------------

def test_paperclip_role_maps_to_surface():
    from okami.core.tool_policy import paperclip_surface
    assert paperclip_surface("worker") == "paperclip-worker"
    assert paperclip_surface("manager") == "paperclip-manager"
    assert paperclip_surface("reviewer") == "paperclip-reviewer"
    assert paperclip_surface("external") == "paperclip-external"
    assert paperclip_surface("admin") == "paperclip-manager"
    assert paperclip_surface("dev") == "paperclip"            # desconhecido → worker (default)
    assert paperclip_surface(None) == "paperclip"


def test_paperclip_default_is_worker_not_full_surface():
    # #P1: antes 'paperclip' era surface COMPLETA; agora default = worker (sem gestão de processo/spawn)
    # COM isolamento real (Docker/require_isolation), o worker EXECUTA shell/process_start.
    reg = filter_registry(default_registry(), "paperclip", sandbox={"require_isolation": True})
    assert "run_shell" in reg and "process_start" in reg     # worker EXECUTA (sob sandbox + defer)
    for t in ("process_write", "process_signal", "process_kill", "spawn"):
        assert t not in reg, t                               # mas não gerencia processo nem recursiona


def test_paperclip_worker_shell_gated_without_isolation():
    # #P1 gate: worker remoto SEM isolamento real (sem sandbox/sem Docker) NÃO ganha shell/process_start.
    reg = filter_registry(default_registry(), "paperclip")           # sandbox=None → não isolado
    assert "run_shell" not in reg and "process_start" not in reg     # fail-closed
    assert "read_file" in reg and "respond" in reg                   # leitura/resposta seguem
    # require_isolation libera (isolamento real):
    reg3 = filter_registry(default_registry(), "paperclip-worker", sandbox={"profile": "hardened-strict"})
    assert "run_shell" in reg3 and "process_start" in reg3


def test_allow_does_not_bypass_isolation_gate():
    # #P1: `allow` comum NÃO fura mais o gate de isolamento (era o buraco). Só a flag unsafe_* grotesca.
    allow_cfg = {"surfaces": {"paperclip": {"allow": ["run_shell"]}}}
    reg = filter_registry(default_registry(), "paperclip", config=allow_cfg)   # sem isolamento
    assert "run_shell" not in reg                                    # allow sozinho NÃO libera shell sem isolamento
    # a flag grotesca por superfície libera:
    unsafe_surface = {"surfaces": {"paperclip": {"unsafe_allow_without_isolation": True}}}
    assert "run_shell" in filter_registry(default_registry(), "paperclip", config=unsafe_surface)
    # a flag grotesca do sandbox (deploy inteiro) também:
    reg2 = filter_registry(default_registry(), "paperclip",
                           sandbox={"unsafe_allow_host_shell_without_isolation": True})
    assert "run_shell" in reg2
    # com isolamento real, allow funciona normalmente (não há gate a furar):
    iso = {"surfaces": {"paperclip-manager": {"allow": ["run_shell"]}}}
    assert "run_shell" in filter_registry(default_registry(), "paperclip-manager",
                                          config=iso, sandbox={"require_isolation": True})


class _FakeMcp:
    """Stub de tool MCP: tem .name e .capabilities (como McpTool)."""
    def __init__(self, name, caps):
        self.name = name
        self.capabilities = set(caps)


def test_mcp_filtered_by_surface_capability():
    from okami.core.tool_policy import filter_mcp_registry
    tools = {
        "srv__read_doc": _FakeMcp("srv__read_doc", {"read"}),
        "srv__write_file": _FakeMcp("srv__write_file", {"write"}),
        "srv__run_cmd": _FakeMcp("srv__run_cmd", {"shell"}),
        "srv__fetch": _FakeMcp("srv__fetch", {"network"}),
    }
    # CLI (máquina do dono): MCP livre
    assert set(filter_mcp_registry(dict(tools), "cli")) == set(tools)
    # Telegram (remoto): só a tool de LEITURA passa; write/shell/network somem
    tg = filter_mcp_registry(dict(tools), "telegram")
    assert set(tg) == {"srv__read_doc"}
    # Slack idem
    assert set(filter_mcp_registry(dict(tools), "slack")) == {"srv__read_doc"}
    # deploy pode abrir uma MCP de efeito por nome:
    cfg = {"surfaces": {"telegram": {"allow": ["srv__write_file"]}}}
    tg2 = filter_mcp_registry(dict(tools), "telegram", config=cfg)
    assert "srv__write_file" in tg2 and "srv__run_cmd" not in tg2


def test_mcp_worker_dangerous_requires_isolation():
    from okami.core.tool_policy import filter_mcp_registry
    tools = {"srv__run_cmd": _FakeMcp("srv__run_cmd", {"shell"}),
             "srv__read": _FakeMcp("srv__read", {"read"})}
    # worker SEM isolamento: MCP shell fura o sandbox → removida; leitura fica
    no_iso = filter_mcp_registry(dict(tools), "paperclip-worker")
    assert set(no_iso) == {"srv__read"}
    # worker COM isolamento real: MCP de efeito permitida
    iso = filter_mcp_registry(dict(tools), "paperclip-worker", sandbox={"require_isolation": True})
    assert set(iso) == {"srv__run_cmd", "srv__read"}


def test_mcp_allow_does_not_bypass_worker_isolation():
    # #P1: allow comum NÃO libera MCP de efeito sem isolamento real (era o buraco em mcp_denied).
    from okami.core.tool_policy import filter_mcp_registry
    tools = {"srv__run_cmd": _FakeMcp("srv__run_cmd", {"shell"})}
    allow_cfg = {"surfaces": {"paperclip-worker": {"allow": ["srv__run_cmd"]}}}
    # allow + SEM isolamento → AINDA removida (gate vence o allow)
    assert filter_mcp_registry(dict(tools), "paperclip-worker", config=allow_cfg) == {}
    # só a flag grotesca por superfície libera sem isolamento:
    unsafe = {"surfaces": {"paperclip-worker": {"unsafe_allow_without_isolation": True}}}
    assert "srv__run_cmd" in filter_mcp_registry(dict(tools), "paperclip-worker", config=unsafe)
    # ou a flag do sandbox (deploy inteiro):
    assert "srv__run_cmd" in filter_mcp_registry(
        dict(tools), "paperclip-worker", sandbox={"unsafe_allow_host_shell_without_isolation": True})
    # com isolamento real, o allow funciona normalmente:
    assert "srv__run_cmd" in filter_mcp_registry(
        dict(tools), "paperclip-worker", config=allow_cfg, sandbox={"require_isolation": True})


def test_paperclip_manager_no_execution():
    reg = filter_registry(default_registry(), "paperclip-manager")
    for t in ("run_shell", "process_start", "process_write", "process_kill", "spawn"):
        assert t not in reg, t                               # control plane: orquestra, não executa
    assert "read_file" in reg and "respond" in reg


def test_paperclip_reviewer_reads_does_not_write_or_execute():
    reg = filter_registry(default_registry(), "paperclip-reviewer")
    for t in ("run_shell", "process_start", "write_file", "edit_file", "spawn"):
        assert t not in reg, t
    assert "read_file" in reg and "recall_memory" in reg and "respond" in reg


def test_paperclip_external_denies_everything_dangerous():
    reg = filter_registry(default_registry(), "paperclip-external")
    for t in ("run_shell", "process_start", "spawn", "write_file", "edit_file", "browse"):
        assert t not in reg, t                               # cap 'safe' + remote deny → só leitura/resposta
    assert "read_file" in reg and "respond" in reg
