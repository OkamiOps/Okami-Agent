"""session_search (pesquisa #6 item 10, doutrina Hermes: "memória = preferência; histórico de
tarefa = busca de sessão"). FTS5 sobre TODOS os transcripts (ativos + arquivados) + tool de busca.

Hoje uma conversa compactada ou /new-ada vira arquivo morto irrecuperável. Isto deixa a agente
reabrir "o que a gente decidiu naquele projeto semana passada".
"""
from __future__ import annotations

from okami.gateway.sessions import TranscriptStore
from okami.memory.session_search import SessionIndex
from okami.core.tools import ToolContext
from okami.core.tools.session_search import SessionSearch


def _seed(home):
    st = TranscriptStore(home)
    st.append("100", "USER", "vamos usar postgres no projeto okami")
    st.append("100", "AGENTE", "decidido: postgres 16 com pgvector para embeddings")
    st.append("200", "USER", "qual era a senha do wifi mesmo")
    st.append("200", "AGENTE", "não guardo senha; pergunte ao roteador")
    st.reset("100")                                  # arquiva a sessão 100 (vira .reset.jsonl)
    st.append("100", "USER", "conversa nova no mesmo chat")
    return st


def test_reindex_counts_messages(tmp_path):
    _seed(tmp_path)
    idx = SessionIndex(tmp_path)
    n = idx.reindex()
    assert n >= 5                                     # 4 da sessão arquivada + 1 da nova


def test_search_finds_archived_session(tmp_path):
    _seed(tmp_path)
    idx = SessionIndex(tmp_path)
    idx.reindex()
    hits = idx.search("postgres pgvector")
    assert hits
    assert any("pgvector" in h["text"] for h in hits)
    assert any(h["chat_id"] == "100" for h in hits)


def test_search_returns_snippet_and_role(tmp_path):
    _seed(tmp_path)
    idx = SessionIndex(tmp_path)
    idx.reindex()
    h = idx.search("postgres")[0]
    assert h["role"] in ("USER", "AGENTE") and h["ts"] and h["session"]


def test_reindex_incremental_skips_unchanged(tmp_path):
    _seed(tmp_path)
    idx = SessionIndex(tmp_path)
    idx.reindex()
    assert idx.reindex() == 0                         # nada mudou → 0 reindexados


def test_no_results(tmp_path):
    _seed(tmp_path)
    idx = SessionIndex(tmp_path)
    idx.reindex()
    assert idx.search("zzz_nada_disso_existe") == []


# ------------------------------------------------------------------ tool
def test_tool_discovery(tmp_path):
    _seed(tmp_path)
    ctx = ToolContext(workspace=tmp_path, agent_home=tmp_path)
    res = SessionSearch().run({"query": "postgres"}, ctx)
    assert res.ok and res.effect is False
    assert "pgvector" in res.output or "postgres" in res.output
    assert "untrusted_tool_result" not in res.output  # transcript PRÓPRIO não é dado externo


def test_tool_no_match(tmp_path):
    _seed(tmp_path)
    ctx = ToolContext(workspace=tmp_path, agent_home=tmp_path)
    res = SessionSearch().run({"query": "zzzqqq"}, ctx)
    assert res.ok and ("nada" in res.output.lower() or "nenhum" in res.output.lower())


def test_tool_empty_query(tmp_path):
    ctx = ToolContext(workspace=tmp_path, agent_home=tmp_path)
    res = SessionSearch().run({"query": ""}, ctx)
    assert not res.ok


def test_registered():
    from okami.core.tools import default_registry
    assert "session_search" in default_registry()
