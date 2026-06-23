"""Probe de function-calling nativo: confirma que o endpoint honra `tools=` antes de confiar; degrada
pro JSON se ignorar/erra. Mesmo veredito p/ prompt e provider (sem descasamento de modo)."""
from __future__ import annotations

import pytest

from okami.config import ProviderConfig
from okami.llm.native_capability import native_supported, reset_native_cache


@pytest.fixture(autouse=True)
def _reset():
    reset_native_cache()
    yield
    reset_native_cache()


def _pc(native: bool, name="p"):
    return ProviderConfig(name=name, model="openai/x", native_tools=native)


def test_native_off_means_no_probe():
    calls = []
    assert native_supported(_pc(False), probe=lambda pc: calls.append(1) or True) is False
    assert calls == []                                       # native desligado → nem roda o probe


def test_endpoint_that_honors_tools_is_native():
    assert native_supported(_pc(True), probe=lambda pc: True) is True


def test_endpoint_that_ignores_tools_degrades():
    assert native_supported(_pc(True), probe=lambda pc: False) is False   # ignorou → JSON


def test_probe_error_degrades_failsafe():
    def boom(pc):
        raise RuntimeError("endpoint não suporta tools")
    assert native_supported(_pc(True), probe=boom) is False  # erro → fail-safe pro JSON


def test_verdict_is_cached_one_probe_per_provider():
    calls = []
    pc = _pc(True, name="prov-a")
    native_supported(pc, probe=lambda p: calls.append(1) or True)
    native_supported(pc, probe=lambda p: calls.append(1) or True)
    assert len(calls) == 1                                   # probe roda 1x por provider (cacheado)
