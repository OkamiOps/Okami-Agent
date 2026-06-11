"""Registry declarativo de canais (paridade OpenClaw channel plugins): adicionar um canal = registrar
um ChannelSpec, não editar if/elif no builders. build_channel valida campos e instancia; rest_types()
alimenta o loop do gateway; o mapa de superfície deriva do registry (anti-drift com a tool policy)."""

from __future__ import annotations

import pytest

from okami.gateway.channel_registry import REGISTRY, build_channel, rest_channel_types, surface_map


def test_build_slack_from_spec():
    ch = build_channel("slack", {"token": "T", "channel_id": "C1", "allow_all": True})
    assert ch.name == "slack" and ch.channel_id == "C1" and ch.allow_all is True


def test_build_mattermost_positional_order():
    ch = build_channel("mattermost", {"base_url": "https://m", "token": "T", "channel_id": "C9"})
    assert ch.name == "mattermost" and ch.channel_id == "C9"


def test_missing_required_field_raises_with_field_name():
    with pytest.raises(KeyError) as e:
        build_channel("slack", {"token": "T"})            # falta channel_id
    assert "channel_id" in str(e.value)


def test_unknown_channel_type_raises():
    with pytest.raises(KeyError):
        build_channel("telepathy", {"token": "T"})


def test_rest_types_excludes_telegram():
    rt = rest_channel_types()
    assert "telegram" not in rt and {"slack", "discord", "mattermost"} <= set(rt)


def test_surface_map_matches_tool_policy():
    # anti-drift: toda superfície declarada no registry existe na política de ferramentas por superfície
    from okami.core.tool_policy import _DENY_BY_SURFACE
    for name, surface in surface_map().items():
        assert surface in _DENY_BY_SURFACE, f"{name}→{surface} sem política em tool_policy"


def test_registry_is_extensible(monkeypatch):
    # registrar um canal NOVO (reusando SlackChannel) → build_channel o constrói sem tocar no builders
    from okami.gateway.channel_registry import ChannelSpec
    spec = ChannelSpec(name="myslack", surface="slack", module="okami.channels.slack",
                       cls="SlackChannel", arg_keys=("token", "channel_id"), rest=True)
    monkeypatch.setitem(REGISTRY, "myslack", spec)
    ch = build_channel("myslack", {"token": "T", "channel_id": "C"})
    assert ch.channel_id == "C"
    assert "myslack" in rest_channel_types()


def test_builders_uses_registry_for_discord(monkeypatch):
    # build_endpoints constrói um canal não-telegram via registry (discord), sem if/elif hardcoded
    from okami.agents import AgentSpec
    from okami.gateway import build_endpoints
    import tempfile

    from pathlib import Path
    spec = AgentSpec("dev", Path(tempfile.mkdtemp()),
                     {"channels": {"discord": {"token": "T", "channel_id": "C42"}}})
    graw = {"default_provider": "lmstudio", "providers": {"lmstudio": {"model": "openai/x", "api_key": "k"}}}
    eps = build_endpoints(graw, {"dev": spec}, emit=lambda m: None, run_task=lambda *a, **k: None)
    assert eps and eps[0].channel.name == "discord" and eps[0].channel.channel_id == "C42"
