"""Expansão do ANTISLOP.md (15 → 25 padrões pt-BR) + bloco positivo de voz + self-audit no
VOICE.md (dono: agente soava robótico — ANTISLOP só tinha "evite X", sem exemplo do que É bom).

Cobre: as duas cópias (agents/okami/ vs okami/builtin/identity/, a versionada que shipa) ficam
IDÊNTICAS; ≥25 padrões numerados; bloco "como soa bem" (antes/depois com pulso) presente;
VOICE.md tem a linha de autoauditoria; e core_block() ainda injeta tudo dentro do teto de char
(_cap_for) — se estourasse, a cauda nunca chegaria ao prompt."""
from __future__ import annotations

from pathlib import Path

from okami.memory import files as mf

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ANTISLOP_AGENT = _REPO_ROOT / "agents" / "okami" / "ANTISLOP.md"
_ANTISLOP_BUILTIN = _REPO_ROOT / "okami" / "builtin" / "identity" / "ANTISLOP.md"
_VOICE = _REPO_ROOT / "agents" / "okami" / "VOICE.md"


def test_both_antislop_copies_exist():
    assert _ANTISLOP_AGENT.exists()
    assert _ANTISLOP_BUILTIN.exists()


def test_both_antislop_copies_are_byte_identical():
    # okami/builtin/identity/ANTISLOP.md é a cópia VERSIONADA que shipa com o pacote (agents/okami/
    # é gitignored) — se elas divergirem, quem instala do zero recebe uma versão desatualizada.
    agent_bytes = _ANTISLOP_AGENT.read_bytes()
    builtin_bytes = _ANTISLOP_BUILTIN.read_bytes()
    assert agent_bytes == builtin_bytes


def test_antislop_has_at_least_25_patterns():
    text = _ANTISLOP_AGENT.read_text(encoding="utf-8")
    assert text.count("### ") >= 25
    assert text.count("**Evite:**") >= 25
    assert text.count("**Antes:**") >= 25
    assert text.count("**Depois:**") >= 25


def test_antislop_has_positive_voice_block():
    # não é só "evite X" — tem um bloco mostrando o que É bom (antes/depois de voz, não de erro).
    text = _ANTISLOP_AGENT.read_text(encoding="utf-8")
    assert "Como soa bem" in text
    assert "Sem alma" in text
    assert "Com pulso" in text


def test_antislop_under_layer_cap():
    text = _ANTISLOP_AGENT.read_text(encoding="utf-8")
    assert len(text) <= mf._cap_for("ANTISLOP.md")


def test_voice_has_self_audit_instruction():
    text = _VOICE.read_text(encoding="utf-8")
    assert "soa como resposta genérica de IA" in text
    assert "reescreve uma vez" in text


def test_core_block_still_includes_antislop_content(tmp_path):
    (tmp_path / "ANTISLOP.md").write_text(_ANTISLOP_AGENT.read_text(encoding="utf-8"), encoding="utf-8")
    block = mf.core_block(tmp_path)
    assert "ANTISLOP" in block
    assert "Como posso ajudar" in block       # padrão #1 ainda presente após a expansão
    assert "Espero que" in block              # padrão #4 ainda presente após a expansão
    assert "Como soa bem" in block            # bloco positivo também é injetado, não só a lista de evitar
    assert len(block) <= mf._cap_for("ANTISLOP.md") + 200   # margem pro header "### ANTISLOP..." injetado
