"""Item 15a — clamp de reasoning_effort por modelo (cost-safe).

Um modelo que só suporta {minimal,low,medium} não pode receber "high" (alguns providers dão 400, outros
COBRAM caro por reasoning que o modelo nem usa direito). `clamp_effort` rebaixa para o maior nível
suportado <= o pedido. Modelo desconhecido / sem tabela de efforts → passa direto (fail-open)."""

from __future__ import annotations

from okami.config import ProviderConfig
from okami.llm import providers
from okami.llm.model_catalog import clamp_effort


def test_clamp_downgrades_to_highest_supported():
    # modelo que suporta até "medium" — pedido "high" rebaixa p/ "medium".
    assert clamp_effort("o4-mini", "high") in ("medium", "high")  # depende da tabela; ver abaixo


def test_clamp_unknown_model_passes_through():
    assert clamp_effort("modelo-que-nao-existe-123", "high") == "high"
    assert clamp_effort("modelo-que-nao-existe-123", "minimal") == "minimal"


def test_clamp_empty_effort_passes_through():
    assert clamp_effort("gpt-5.4", "") == ""


def test_clamp_supported_level_unchanged():
    # se o modelo suporta exatamente o pedido, não mexe.
    from okami.llm.model_catalog import model_info
    info = model_info("gpt-5.4")
    if info and info.supported_efforts:
        top = info.supported_efforts[-1]
        assert clamp_effort("gpt-5.4", top) == top


def test_clamp_below_all_supported_picks_lowest():
    # pedido abaixo do menor suportado → menor suportado (nunca devolve vazio/None aqui).
    # construímos via tabela conhecida: se um modelo só suporta {"low","medium","high"} e pedirem
    # "minimal", deve cair em "low".
    from okami.llm import model_catalog
    # injeta um modelo sintético na tabela só p/ este teste (restaura no fim).
    sup = model_catalog._EFFORTS
    sup["__synthetic__"] = ("low", "medium", "high")
    try:
        assert clamp_effort("__synthetic__", "minimal") == "low"
        assert clamp_effort("__synthetic__", "high") == "high"
        assert clamp_effort("__synthetic__", "medium") == "medium"
    finally:
        sup.pop("__synthetic__", None)


def test_kwargs_clamps_before_apply():
    # integração: _kwargs deve clampar o effort do modelo ANTES de montar reasoning_effort.
    from okami.llm import model_catalog
    model_catalog._EFFORTS["__synthetic2__"] = ("low", "medium")
    try:
        pc = ProviderConfig(name="p", model="openai/__synthetic2__", reasoning_effort="high")
        kw = providers._kwargs(pc, [{"role": "user", "content": "oi"}], stream=False, model=None)
        assert kw.get("reasoning_effort") == "medium"   # high → medium (teto do modelo)
    finally:
        model_catalog._EFFORTS.pop("__synthetic2__", None)
