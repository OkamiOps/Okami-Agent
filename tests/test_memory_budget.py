"""Paridade Hermes (#6): USER.md/MEMORY.md tem TETO de char (core_block injeta [:cap]). Antes o append
crescia sem limite → fato novo era escrito mas SILENCIOSAMENTE cortado no inject (nunca via o modelo).
Agora: append acima do teto é RECUSADO com 'consolide', em vez de sumir do prompt."""
from __future__ import annotations

from okami.memory import files as _f


def test_append_rejected_when_over_cap(tmp_path):
    # USER.md cap = 4000; enche e tenta mais um
    (tmp_path / "USER.md").write_text("# USER\n\n## Sobre o usuário\n- " + ("x" * 4100) + "\n", encoding="utf-8")
    assert _f.is_full(tmp_path, "USER.md")
    assert _f.append_user(tmp_path, "fato novo importante") is False   # recusado (senão sumiria no inject)


def test_append_ok_under_cap(tmp_path):
    assert _f.append_user(tmp_path, "primeiro fato") is True
    assert not _f.is_full(tmp_path, "USER.md")


def test_remember_user_tool_says_consolidate_when_full(tmp_path):
    from types import SimpleNamespace
    from okami.core.tools.memory import RememberUser
    (tmp_path / "USER.md").write_text("# USER\n\n## Sobre o usuário\n- " + ("y" * 4100) + "\n", encoding="utf-8")
    ctx = SimpleNamespace(home=tmp_path, stage_writes=False, memory=None)
    r = RememberUser().run({"text": "mais um fato"}, ctx)
    assert "limite" in r.output.lower() or "consolid" in r.output.lower()
