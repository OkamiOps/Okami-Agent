"""ANTISLOP.md — lista pt-BR de padrões de 'chatbot de atendimento' a NUNCA soar (dono se importa
MUITO com isso). Injetada todo turno via core_block, na mesma família de VOICE.md."""
from __future__ import annotations

from pathlib import Path

from okami.memory import files as mf

_REPO_ANTISLOP = Path(__file__).resolve().parent.parent / "agents" / "okami" / "ANTISLOP.md"


def test_antislop_file_exists_and_parses():
    assert _REPO_ANTISLOP.exists()
    text = _REPO_ANTISLOP.read_text(encoding="utf-8")
    assert text.strip()
    # cada padrão numerado tem título + Evite/Antes/Depois (mesmo formato do humanizer/SKILL.md)
    assert text.count("### ") >= 10          # 10-15 padrões, como pedido
    assert text.count("**Evite:**") >= 10
    assert text.count("**Antes:**") >= 10
    assert text.count("**Depois:**") >= 10


def test_antislop_file_under_layer_cap():
    # o mesmo teto que core_block injeta ([:cap]) — se estourar, a cauda nunca chega ao modelo
    text = _REPO_ANTISLOP.read_text(encoding="utf-8")
    assert len(text) <= mf._cap_for("ANTISLOP.md")


def test_core_block_includes_antislop_content(tmp_path):
    (tmp_path / "ANTISLOP.md").write_text(_REPO_ANTISLOP.read_text(encoding="utf-8"), encoding="utf-8")
    block = mf.core_block(tmp_path)
    assert "ANTISLOP" in block
    assert "Como posso ajudar" in block             # padrão #1 (abertura de atendente) presente
    assert "Espero que isso ajude" in block         # padrão #4 (fechamento de atendente) presente


def test_core_block_local_antislop_overrides_builtin(tmp_path):
    # sem ANTISLOP.md local → cai no default builtin versionado (sempre-on); um ANTISLOP.md local
    # SOBRESCREVE o builtin.
    (tmp_path / "SOUL.md").write_text("# SOUL\nvalores.\n", encoding="utf-8")
    (tmp_path / "ANTISLOP.md").write_text("# ANTISLOP\nregra local exclusiva.\n", encoding="utf-8")
    block = mf.core_block(tmp_path)
    assert "valores" in block
    assert "regra local exclusiva" in block   # o arquivo local venceu o builtin


def test_core_block_orders_antislop_after_voice(tmp_path):
    (tmp_path / "VOICE.md").write_text("# VOICE\ntom próximo.\n", encoding="utf-8")
    (tmp_path / "ANTISLOP.md").write_text(_REPO_ANTISLOP.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "PERSONA.md").write_text("# PERSONA\nengenheiro.\n", encoding="utf-8")
    block = mf.core_block(tmp_path)
    assert block.index("VOZ / TOM") < block.index("ANTISLOP") < block.index("PERSONA / SELF")


def test_agent_okami_dir_has_antislop_alongside_identity_files():
    # o agente 'okami' de referência no repo (agents/okami/) carrega ANTISLOP igual a SOUL/VOICE/PERSONA
    agent_dir = _REPO_ANTISLOP.parent
    assert (agent_dir / "SOUL.md").exists()
    assert (agent_dir / "VOICE.md").exists()
    assert (agent_dir / "ANTISLOP.md").exists()
