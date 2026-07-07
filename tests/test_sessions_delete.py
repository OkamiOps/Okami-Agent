"""`okami sessions delete` (WIN4): apaga transcript + arquivos de /new + entrada em sessions.json,
reusando as APIs do TranscriptStore. Chama a função do comando direto (bypassa o parsing do typer)."""

from __future__ import annotations

import pytest
import typer

from okami.cli.commands import misc as misc_mod
from okami.gateway.sessions import TranscriptStore


def _store(tmp_path):
    ticks = iter(range(1, 10_000))
    return TranscriptStore(tmp_path, clock=lambda: next(ticks))


def test_sessions_delete_removes_transcript_and_store_entry(tmp_path, monkeypatch):
    st = _store(tmp_path)
    st.append("7", "USER", "oi")
    st.append("7", "AGENTE", "olá")
    assert "7" in st.ids()
    tx = tmp_path / ".okami" / "sessions" / "7.jsonl"
    assert tx.exists()

    monkeypatch.setattr(misc_mod, "_sessions_store", lambda agent: (st, "dev"))
    misc_mod.sessions_delete(chat_id="7", agent="", yes=True)

    assert "7" not in st.ids()
    assert not tx.exists()


def test_sessions_delete_removes_reset_archives(tmp_path, monkeypatch):
    st = _store(tmp_path)
    st.append("7", "USER", "oi")
    st.reset("7")                       # /new arquiva o transcript em 7.<ts>.reset.jsonl
    st.append("7", "USER", "novo turno")
    sess_dir = tmp_path / ".okami" / "sessions"
    assert list(sess_dir.glob("7.*.reset.jsonl"))       # o arquivo existe antes de apagar

    monkeypatch.setattr(misc_mod, "_sessions_store", lambda agent: (st, "dev"))
    misc_mod.sessions_delete(chat_id="7", agent="", yes=True)

    assert not list(sess_dir.glob("7.*.reset.jsonl"))
    assert not (sess_dir / "7.jsonl").exists()
    assert "7" not in st.ids()


def test_sessions_delete_missing_chat_id_errors(tmp_path, monkeypatch):
    st = _store(tmp_path)
    monkeypatch.setattr(misc_mod, "_sessions_store", lambda agent: (st, "dev"))
    with pytest.raises(typer.Exit):
        misc_mod.sessions_delete(chat_id="nope", agent="", yes=True)


def test_sessions_delete_asks_confirmation_without_yes(tmp_path, monkeypatch):
    st = _store(tmp_path)
    st.append("7", "USER", "oi")
    monkeypatch.setattr(misc_mod, "_sessions_store", lambda agent: (st, "dev"))
    monkeypatch.setattr(typer, "confirm", lambda *a, **kw: False)   # usuário recusa
    with pytest.raises(typer.Exit) as exc:
        misc_mod.sessions_delete(chat_id="7", agent="", yes=False)
    assert exc.value.exit_code == 0
    assert "7" in st.ids()               # cancelado → nada foi removido
