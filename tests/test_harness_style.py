"""Bloco de ESTILO visível + hint de formatação por superfície (paridade Hermes).

Dor: modelos fracos respondiam curto e sem formatação. Causa: a orientação de markdown/idioma
estava ENTERRADA no manual interno marcado 'NUNCA cite' → o modelo a evitava. Agora vira um bloco
VISÍVEL ('como escrever pra pessoa') e ganha hint por canal (Telegram não tem tabela, etc.)."""

from __future__ import annotations

from okami.core.harness.models import Task
from okami.core.harness.prompt import build_system_prompt
from okami.core.harness.style import style_block

_MANUAL_MARK = "=== COMO VOCÊ AGE"


# ----------------------------------------------------------------- style_block por superfície
def test_style_block_cli_keeps_table_skeleton():
    s = style_block("cli")
    assert "<entrega>" in s and "over-claim" in s
    assert "| suíte | passou | falhou |" in s          # CLI/TUI ainda tem o esqueleto de tabela p/ relatório
    # contrato novo: estrutura CONDICIONAL ao tamanho (resposta curta = prosa; não força tabela → não soa robô)
    assert "ESTRUTURA SEGUE O TAMANHO" in s and "PROSA" in s


def test_style_block_telegram_directs_like_hermes():
    # paridade Hermes: enquadra como PLATAFORMA ('você está no Telegram'), garante que o markdown CONVERTE,
    # e exige ESTRUTURADO em vez de paredão. Tabela agora é permitida (o renderer converte em lista).
    s = style_block("telegram")
    low = s.lower()
    assert "telegram" in low and "convert" in low                # garante ao modelo que vai renderizar
    assert "estrutura" in low and ("paredão" in low or "parágrafo" in low)   # anti-wall-of-text
    assert "tabela" in low                                       # tabela liberada (renderer converte)


def test_style_block_slack_and_discord_have_surface_hint():
    for surf in ("slack", "discord", "mattermost"):
        s = style_block(surf).lower()
        assert surf in s
        assert "| suíte | passou | falhou |" not in style_block(surf)


def test_style_block_always_mirrors_language():
    for surf in ("cli", "telegram", "slack", "subagent"):
        s = style_block(surf)
        assert "<idioma>" in s and "MESMO idioma" in s and "inglês" in s


def test_unknown_surface_falls_back_to_full_markdown():
    s = style_block("algum-canal-novo")
    assert "| suíte | passou | falhou |" in s           # default = markdown completo (como cli)


# ----------------------------------------------------------------- integração no system prompt
def test_prompt_style_is_visible_not_buried_in_internal_manual():
    p = build_system_prompt(Task(goal="faz X"), {}, surface="cli")
    # o bloco de estilo aparece ANTES do manual interno 'NUNCA cite' → é orientação visível, não escondida
    assert "<entrega>" in p and _MANUAL_MARK in p
    assert p.index("<entrega>") < p.index(_MANUAL_MARK)


def test_prompt_telegram_surface_injects_platform_direction():
    p = build_system_prompt(Task(goal="faz X"), {}, surface="telegram").lower()
    assert "telegram" in p and "convert" in p and "estrutura" in p   # direção estilo Hermes no prompt


def test_prompt_default_surface_is_cli_backcompat():
    # chamada SEM surface (assinatura antiga) segue com o esqueleto de tabela — não quebra nada
    p = build_system_prompt(Task(goal="faz X"), {})
    assert "| suíte | passou | falhou |" in p and "<idioma>" in p


def test_conversational_prompt_also_carries_style():
    t = Task(goal="oi tudo bem?")                       # sem exit_criteria → modo conversa
    p = build_system_prompt(t, {}, surface="telegram")
    assert "<idioma>" in p
    assert "telegram" in p.lower()
