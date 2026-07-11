"""Expansão do ANTISLOP.md (15 → 25 padrões pt-BR) + bloco positivo de voz.

Cobre o default versionado que shipa com o pacote; ≥25 padrões numerados; bloco "como soa bem"
(antes/depois com pulso) presente; e core_block() ainda injeta tudo dentro do teto de char
(_cap_for) — se estourasse, a cauda nunca chegaria ao prompt."""
from __future__ import annotations

from pathlib import Path

from okami.memory import files as mf

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ANTISLOP_BUILTIN = _REPO_ROOT / "okami" / "builtin" / "identity" / "ANTISLOP.md"


def test_versioned_antislop_default_exists():
    assert _ANTISLOP_BUILTIN.exists()


def test_antislop_has_at_least_25_patterns():
    text = _ANTISLOP_BUILTIN.read_text(encoding="utf-8")
    assert text.count("### ") >= 25
    assert text.count("**Evite:**") >= 25
    assert text.count("**Antes:**") >= 25
    assert text.count("**Depois:**") >= 25


def test_antislop_has_positive_voice_block():
    # não é só "evite X" — tem um bloco mostrando o que É bom (antes/depois de voz, não de erro).
    text = _ANTISLOP_BUILTIN.read_text(encoding="utf-8")
    assert "Como soa bem" in text
    assert "Sem alma" in text
    assert "Com pulso" in text


def test_antislop_under_layer_cap():
    text = _ANTISLOP_BUILTIN.read_text(encoding="utf-8")
    assert len(text) <= mf._cap_for("ANTISLOP.md")


def test_core_block_still_includes_antislop_content(tmp_path):
    block = mf.core_block(tmp_path)
    assert "ANTISLOP" in block
    assert "Como posso ajudar" in block       # padrão #1 ainda presente após a expansão
    assert "Espero que" in block              # padrão #4 ainda presente após a expansão
    assert "Como soa bem" in block            # bloco positivo também é injetado, não só a lista de evitar
    assert len(block) <= mf._cap_for("ANTISLOP.md") + 200   # margem pro header "### ANTISLOP..." injetado
