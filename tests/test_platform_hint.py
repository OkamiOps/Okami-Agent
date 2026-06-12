"""platform_hint no ChannelSpec (pesquisa #6 item 22, paridade Hermes platform_registry).

String injetada no system prompt POR SUPERFÍCIE — orienta a voz/formatação do canal (Telegram HTML,
Slack mrkdwn). CLI/desconhecida não injeta nada (sem custo no caminho comum).
"""
from __future__ import annotations

from okami.gateway.channel_registry import REGISTRY, platform_hint
from okami.core.harness.prompt import build_system_prompt
from okami.core.harness.models import Task
from okami.core.tools import default_registry


def test_specs_have_hint_field():
    assert hasattr(REGISTRY["telegram"], "hint")
    assert REGISTRY["telegram"].hint                     # telegram tem hint não-vazio


def test_platform_hint_by_surface():
    assert "html" in platform_hint("telegram").lower() or "negrito" in platform_hint("telegram").lower()
    assert platform_hint("slack")                        # slack tem hint
    assert platform_hint("cli") == ""                    # CLI não injeta
    assert platform_hint("desconhecida") == ""


def test_group_surface_uses_telegram_hint():
    # grupo do telegram é a mesma plataforma → herda o hint do telegram
    assert platform_hint("group")


def test_prompt_includes_hint_for_telegram(tmp_path):
    p = build_system_prompt(Task(goal="oi"), default_registry(), surface="telegram")
    assert "HTML" in p or "<b>" in p


def test_prompt_no_hint_for_cli(tmp_path):
    p = build_system_prompt(Task(goal="oi"), default_registry(), surface="cli")
    # o hint específico de plataforma não aparece em CLI (o style_block de CLI é outro)
    assert "Telegram (HTML)" not in p
