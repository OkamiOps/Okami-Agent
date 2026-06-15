"""Citação/origem (#11): memória injetada/recuperada carrega categoria · origem · confiança."""

from __future__ import annotations

from okami.memory import MemoryItem, open_memory
from okami.memory.citation import cite, cited_line


def test_cite_shows_kind_source_confidence():
    i = MemoryItem(text="x", kind="preference", source="agent", score=0.82)
    assert cite(i) == "[preference · agent · 0.82]"


def test_cite_omits_confidence_when_score_not_normalized():
    assert cite(MemoryItem(text="x", kind="fact", source="cli")) == "[fact · cli]"   # sem score → sem nº
    raw = cite(MemoryItem(text="x", kind="fact", source="cli", score=12.5))           # BM25 cru
    assert "12.5" not in raw and raw == "[fact · cli]"


def test_cited_line_has_text_and_origin():
    line = cited_line(MemoryItem(text="usa Vercel", kind="fact", source="task", score=0.5))
    assert line.startswith("- usa Vercel") and "[fact · task · 0.50]" in line


def test_inject_carries_citation(tmp_path):
    m = open_memory(tmp_path)
    m.write(MemoryItem(text="o usuário prefere TypeScript", kind="preference", source="cli"))
    block = m.inject("typescript")
    m.close()
    assert "TypeScript" in block and "preference" in block and "cli" in block   # texto + origem


def test_inject_frames_recall_as_reference_not_instruction(tmp_path):
    # Defesa de injeção (estilo Hermes memory_manager): a memória recuperada vem MARCADA como dado
    # de referência, NÃO como nova instrução/entrada do usuário — conteúdo recuperado nunca é comando.
    m = open_memory(tmp_path)
    m.write(MemoryItem(text="prefere respostas curtas", kind="preference", source="user"))
    block = m.inject("como responder")
    m.close()
    up = block.upper()
    assert "REFERÊNCIA" in up                         # é dado de referência…
    assert "INSTRUÇÃO" in up                          # …NÃO instrução
    assert "prefere respostas curtas" in block        # e ainda injeta o conteúdo


def test_preference_kind_is_injected(tmp_path):
    """Regressão p/ #10+#11: a categoria 'preference' (nova) PRECISA aparecer na injeção."""
    m = open_memory(tmp_path)
    m.write(MemoryItem(text="sempre usa modo escuro", kind="preference", source="agent"))
    assert "modo escuro" in m.inject("modo")
    m.close()
