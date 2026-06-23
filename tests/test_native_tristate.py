"""Política tri-estado do native_tools (default SMART): None → nativo p/ nuvem, JSON p/ local; True/False
forçam. Ninguém precisa lembrar de ligar — provider de nuvem já vem nativo (probe protege); LMStudio fica
em JSON sozinho."""
from __future__ import annotations

import pytest

from okami.config import ProviderConfig
from okami.llm.native_capability import native_supported, reset_native_cache


@pytest.fixture(autouse=True)
def _reset():
    reset_native_cache()
    yield
    reset_native_cache()


def test_default_none_cloud_known_family_is_native():
    pc = ProviderConfig(name="oa", model="openai/gpt-4o", api_base="https://api.openai.com/v1")
    assert native_supported(pc) is True                    # None + nuvem + família conhecida → nativo, sem probe


def test_default_none_local_by_localhost_is_json():
    pc = ProviderConfig(name="lm", model="openai/whatever", api_base="http://localhost:1234/v1")
    assert native_supported(pc) is False                   # None + localhost → JSON (sem probe)


def test_default_none_local_by_tier_is_json():
    pc = ProviderConfig(name="lm", model="openai/x", tier="local")
    assert native_supported(pc) is False                   # None + tier=local → JSON


def test_explicit_false_forces_json_even_for_known():
    pc = ProviderConfig(name="x", model="openai/gpt-4o", native_tools=False)
    assert native_supported(pc) is False                   # /native-tools off vence até família conhecida


def test_explicit_true_on_local_tries_native_via_probe():
    pc = ProviderConfig(name="x", model="openai/somelocal", tier="local", native_tools=True)
    assert native_supported(pc, probe=lambda p: True) is True   # forçado: o _is_local não bloqueia o True


def test_default_none_unknown_cloud_uses_probe():
    pc = ProviderConfig(name="mm", model="openai/MiniMax-M3", api_base="https://api.minimax.io/v1", tier="weak")
    assert native_supported(pc, probe=lambda p: True) is True   # None + nuvem desconhecida → probe decide
    reset_native_cache()
    assert native_supported(pc, probe=lambda p: False) is False  # endpoint não honra → degrada


def test_run_task_native_override_does_not_mutate_shared_pc():
    # a cópia do /native-tools NÃO pode contaminar o provider compartilhado
    pc = ProviderConfig(name="oa", model="openai/gpt-4o")
    forced = pc.model_copy(update={"native_tools": False})
    assert forced.native_tools is False and pc.native_tools is None
