"""Testes do TranscriptStore (sessões 2 camadas: metadados + transcript append-only)."""

from __future__ import annotations

import json

from okami.gateway.sessions import TranscriptStore


def _store(tmp_path):
    ticks = iter(range(1, 10_000))
    return TranscriptStore(tmp_path, clock=lambda: next(ticks))   # relógio determinístico


def test_append_only_transcript_tree(tmp_path):
    st = _store(tmp_path)
    st.append("7", "USER", "oi")
    st.append("7", "AGENTE", "olá")
    nodes = st.read("7")
    assert [n["role"] for n in nodes] == ["USER", "AGENTE"]
    assert nodes[0]["id"] == "7-0" and nodes[0]["parentId"] is None
    assert nodes[1]["id"] == "7-1" and nodes[1]["parentId"] == "7-0"   # árvore id/parentId


def test_history_tail_and_metadata(tmp_path):
    st = _store(tmp_path)
    for i in range(20):
        st.append("7", "USER", f"m{i}")
    hist = st.history("7", limit=4)
    assert [t for _, t in hist] == ["m16", "m17", "m18", "m19"]    # só a cauda
    e = st.entry("7")
    assert e["node_count"] == 20 and e["last_role"] == "USER"


def test_append_does_not_rewrite_whole_file(tmp_path):
    # append-only: cada turno acrescenta EXATAMENTE uma linha (não reescreve a conversa)
    st = _store(tmp_path)
    st.append("7", "USER", "a")
    p = tmp_path / ".okami" / "sessions" / "7.jsonl"
    assert len(p.read_text(encoding="utf-8").splitlines()) == 1
    st.append("7", "AGENTE", "b")
    assert len(p.read_text(encoding="utf-8").splitlines()) == 2


def test_metadata_separate_from_transcript(tmp_path):
    st = _store(tmp_path)
    st.update_entry("7", yolo=True, persona_overlay="x")
    assert st.entry("7")["yolo"] is True
    assert not (tmp_path / ".okami" / "sessions" / "7.jsonl").exists()   # metadados ≠ transcript


def test_reset_archives_transcript(tmp_path):
    st = _store(tmp_path)
    st.append("7", "USER", "antiga")
    st.reset("7")
    sess = tmp_path / ".okami" / "sessions"
    assert not (sess / "7.jsonl").exists()
    assert list(sess.glob("7.*.reset.jsonl"))                      # arquivado, não apagado
    assert st.entry("7")["node_count"] == 0                        # contagem zerada
    st.append("7", "USER", "nova")
    assert st.read("7")[0]["text"] == "nova"


def test_corrupted_last_line_is_tolerated(tmp_path):
    st = _store(tmp_path)
    st.append("7", "USER", "ok")
    p = tmp_path / ".okami" / "sessions" / "7.jsonl"
    with p.open("a", encoding="utf-8") as f:
        f.write('{"id": "7-1", trunc')                            # linha truncada por um crash no append
    assert [t for _, t in st.history("7")] == ["ok"]              # ignora a linha corrompida


def test_compact_summary_replaces_prefix_in_rebuild(tmp_path):
    st = _store(tmp_path)
    for i in range(6):
        st.append("7", "USER", f"m{i}")
    st.compact("7", "RESUMO: discutimos m0..m5")
    st.append("7", "AGENTE", "continuando daqui")
    hist = st.history("7", limit=16)
    assert hist[0][0] == "SUMMARY" and "RESUMO" in hist[0][1]    # rebuild começa no resumo
    assert hist[-1] == ("AGENTE", "continuando daqui")
    assert not any(t == "m0" for _, t in hist)                  # prefixo antigo saiu do rebuild
    assert len(st.read("7")) == 8                               # mas o transcript COMPLETO continua no disco


def test_write_lock_cleans_stale_lock(tmp_path):
    import os
    st = _store(tmp_path)
    st.update_entry("7", yolo=True)
    lock = tmp_path / ".okami" / "sessions" / "sessions.json.lock"
    lock.write_text("x", encoding="utf-8")                      # lock órfão de um processo morto
    old = 1.0
    os.utime(lock, (old, old))                                  # bem antigo → stale
    st.update_entry("7", yolo=False)
    assert st.entry("7")["yolo"] is False and not lock.exists()  # limpou o stale e gravou


def test_prune_keeps_recent(tmp_path):
    st = _store(tmp_path)
    for c in ("a", "b", "c", "d"):
        st.append(c, "USER", "oi")                               # 4 sessões (updated_at crescente)
    removed = st.prune(max_sessions=2)
    assert removed == 2 and set(st.ids()) == {"c", "d"}          # mantém as 2 mais recentes
    assert not (tmp_path / ".okami" / "sessions" / "a.jsonl").exists()
