"""Guidance POR FAMÍLIA de modelo (paridade Hermes prompt_builder): cada família tem manias —
gpt/codex/grok precisam de 'aja, não prometa'; gemini/gemma respondem melhor com concisão +
caminho absoluto; os abertos fracos (qwen/deepseek/glm/minimax) precisam do lembrete de UMA ação.
Claude/forte segue instrução → sem bloco extra (não inflar o prompt à toa)."""

from __future__ import annotations

from okami.core.harness.models import Task
from okami.core.harness.prompt import build_system_prompt
from okami.core.harness.style import model_family_guidance


def test_openai_family_gets_persistence_block():
    g = model_family_guidance("openai/gpt-5.4-codex").lower()
    assert g and ("ferramenta" in g or "aja" in g or "verifique" in g)


def test_grok_counts_as_openai_family():
    assert model_family_guidance("xai/grok-4").strip() != ""


def test_gemini_family_gets_conciseness_block():
    g = model_family_guidance("gemini-3-pro").lower()
    assert g and ("concis" in g or "caminho absoluto" in g or "paralelo" in g)


def test_weak_open_family_gets_one_action_reminder():
    for m in ("openai/qwen3.5-9b", "deepseek-v4", "zai/glm-5", "minimax/abab"):
        g = model_family_guidance(m).lower()
        assert g and ("uma ação" in g or "um bloco" in g or "json" in g), m


def test_claude_strong_gets_no_extra_block():
    assert model_family_guidance("claude-subscription/claude-opus-4-8") == ""


def test_unknown_model_gets_no_block():
    assert model_family_guidance("algum-modelo-novo-xyz") == ""
    assert model_family_guidance("") == ""


def test_prompt_includes_family_block_when_model_given():
    p = build_system_prompt(Task(goal="faz X"), {}, model="openai/gpt-5.4")
    assert model_family_guidance("openai/gpt-5.4").split("\n")[0] in p


def test_prompt_without_model_is_backcompat():
    # sem model (assinatura antiga) → nenhum bloco de família, prompt normal
    p = build_system_prompt(Task(goal="faz X"), {})
    assert "<entrega>" in p and "<idioma>" in p
