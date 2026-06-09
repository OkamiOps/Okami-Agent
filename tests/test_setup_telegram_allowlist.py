"""Setup do Telegram TEM que pedir o allowlist (allow_chats / allow_all).

Bug relatado: o `okami setup` pegava só o TOKEN e nunca perguntava QUEM pode falar com o bot. Como o
gateway é deny-by-default, o bot ficava MUDO e o usuário tinha que editar o yaml na mão (40 min de dor).
Fix: o wizard auto-captura o chat_id (manda msg pro bot → pega o id), com manual/allow_all/depois.
"""
from __future__ import annotations

import pytest
import yaml


@pytest.fixture(autouse=True)
def _okami_home_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))


def _tg(agent_id="okami"):
    from okami.home import agents_dir
    spec = yaml.safe_load((agents_dir() / agent_id / "agent.yaml").read_text(encoding="utf-8"))
    return spec["channels"]["telegram"]


def test_ensure_agent_writes_allow_chats():
    from okami.cli._shared import _ensure_agent
    _ensure_agent("okami", telegram_token="T", telegram_allow=[12345, "@me"])
    tg = _tg()
    assert tg["token"] == "T" and tg["allow_chats"] == [12345, "@me"] and not tg.get("allow_all")


def test_ensure_agent_writes_allow_all():
    from okami.cli._shared import _ensure_agent
    _ensure_agent("okami", telegram_token="T", telegram_allow_all=True)
    assert _tg()["allow_all"] is True


def test_parse_chat_ids_handles_ints_negatives_usernames_and_separators():
    from okami.cli.commands.setup import _parse_chat_ids
    assert _parse_chat_ids("123, -456 ; @user") == [123, -456, "@user"]
    assert _parse_chat_ids("") == [] and _parse_chat_ids("  ") == []


def test_capture_chat_ids_extracts_from_getupdates():
    from okami.cli.commands.setup import _capture_telegram_chat_ids

    class FakeTransport:
        def __init__(self):
            self.calls = 0

        def get_updates(self, offset=0, timeout=30):
            self.calls += 1
            if self.calls == 1:
                return [{"update_id": 7,
                         "message": {"chat": {"id": 999, "first_name": "Marcos", "username": "marcos"}}}]
            return []

    found = _capture_telegram_chat_ids("T", transport=FakeTransport(), tries=3)
    assert 999 in found and "marcos" in found[999]


def test_capture_chat_ids_empty_when_no_message():
    from okami.cli.commands.setup import _capture_telegram_chat_ids

    class Empty:
        def get_updates(self, offset=0, timeout=30):
            return []

    assert _capture_telegram_chat_ids("T", transport=Empty(), tries=2) == {}


def test_allowlist_choice_is_authoritative_no_lingering_allow_all():
    # footgun de segurança: trocar allow_all → lista específica NÃO pode deixar allow_all fantasma
    # (que manteria o bot aberto pra todos). Cada escolha sobrescreve a outra.
    from okami.cli._shared import _ensure_agent
    _ensure_agent("okami", telegram_token="T", telegram_allow_all=True)
    assert _tg().get("allow_all") is True and "allow_chats" not in _tg()
    _ensure_agent("okami", telegram_allow=[42])                       # estreita p/ um chat
    assert _tg()["allow_chats"] == [42] and not _tg().get("allow_all")  # allow_all SUMIU
    _ensure_agent("okami", telegram_allow_all=True)                  # volta p/ todos
    assert _tg().get("allow_all") is True and "allow_chats" not in _tg()
