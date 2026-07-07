"""Probe de function-calling nativo: confirma que o endpoint honra `tools=` antes de confiar; degrada
pro JSON se ignorar/erra. Mesmo veredito p/ prompt e provider (sem descasamento de modo)."""
from __future__ import annotations

import pytest

from okami.config import ProviderConfig
from okami.llm.native_capability import native_supported, reset_native_cache


@pytest.fixture(autouse=True)
def _reset(monkeypatch, tmp_path):
    # isola o cache L2 (disco) num tmp_path — sem isso os testes leriam/escreveriam em ~/.okami de verdade.
    monkeypatch.setattr("okami.home.okami_home", lambda: tmp_path)
    reset_native_cache()
    yield
    reset_native_cache()


def _pc(native: bool | None, name="p"):
    # tier "unknown" (não-local) + modelo fora de _KNOWN_NATIVE → cai no probe quando native=None (SMART).
    return ProviderConfig(name=name, model="openai/x", native_tools=native)


def test_native_off_means_no_probe():
    calls = []
    assert native_supported(_pc(False), probe=lambda pc: calls.append(1) or True) is False
    assert calls == []                                       # native desligado → nem roda o probe


def test_native_true_is_explicit_hint_no_probe():
    """native_tools=True é hint EXPLÍCITO do catálogo/config (ex.: provider_catalog.py p/ MiniMax) —
    já verificado por quem configurou, pula o probe (era o smoking gun: probe SEMPRE dava TypeError
    e degradava pra JSON mesmo com native_tools=True declarado)."""
    calls = []
    assert native_supported(_pc(True), probe=lambda pc: calls.append(1) or False) is True
    assert calls == []


def test_endpoint_that_honors_tools_is_native():
    assert native_supported(_pc(None), probe=lambda pc: True) is True


def test_endpoint_that_ignores_tools_degrades():
    assert native_supported(_pc(None), probe=lambda pc: False) is False   # ignorou → JSON


def test_probe_error_degrades_failsafe():
    def boom(pc):
        raise RuntimeError("endpoint não suporta tools")
    assert native_supported(_pc(None), probe=boom) is False  # erro → fail-safe pro JSON


def test_verdict_is_cached_one_probe_per_provider():
    calls = []
    pc = _pc(None, name="prov-a")
    native_supported(pc, probe=lambda p: calls.append(1) or True)
    native_supported(pc, probe=lambda p: calls.append(1) or True)
    assert len(calls) == 1                                   # probe roda 1x por provider (cacheado)


def test_probe_call_does_not_raise_typeerror_on_kwargs():
    """Regressão do smoking gun: o probe chamava _kwargs(pc, msgs, stream=False) sem o `model`
    keyword-only obrigatório → TypeError em TODA chamada, sempre silenciada e degradada p/ JSON. Aqui
    o probe REAL (_default_probe) roda contra um litellm falso e confirma que o veredito é o do
    tool_call devolvido — não uma exceção mascarada de 'não suporta'."""
    import sys
    import types

    from okami.llm import native_capability as nc

    class _FakeMessage:
        tool_calls = [object()]

    class _FakeChoice:
        message = _FakeMessage()

    class _FakeResp:
        choices = [_FakeChoice()]

    calls = []

    def _fake_completion(**kw):
        calls.append(kw)
        return _FakeResp()

    fake_litellm = types.ModuleType("litellm")
    fake_litellm.completion = _fake_completion
    monkeypatch_module = sys.modules.get("litellm")
    sys.modules["litellm"] = fake_litellm
    try:
        pc = _pc(None, name="prov-b")
        assert nc.native_supported(pc) is True             # sem probe injetado → usa _default_probe de verdade
    finally:
        if monkeypatch_module is not None:
            sys.modules["litellm"] = monkeypatch_module
        else:
            del sys.modules["litellm"]
    assert len(calls) == 1
    assert calls[0]["model"] == "openai/x"                  # _kwargs resolveu o model corretamente (sem TypeError)


def test_verdict_persists_to_disk_l2_cache():
    """FIX 2: o veredito sobrevive a um 'restart' — 2ª instância (cache L1 zerado) lê do disco sem
    pagar outro round-trip de probe."""
    from okami.llm import native_capability as nc

    pc = _pc(None, name="prov-c")
    calls = []
    assert native_supported(pc, probe=lambda p: calls.append(1) or True) is True
    assert len(calls) == 1
    nc._VERDICT.clear()                                     # simula restart: só L1 zera (L2/disco permanece)
    assert native_supported(pc, probe=lambda p: calls.append(1) or False) is True
    assert len(calls) == 1                                  # não rodou probe de novo — leu do L2
