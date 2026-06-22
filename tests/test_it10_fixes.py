"""Caça it.10 (find→verify adversarial): isolamento de sessão (sender vazio não colapsa), agent.yaml com
token não fica world-readable, parsers não crasham com tipo errado, MEDIA: extrai caminho no fim de frase."""
from __future__ import annotations

import os
import stat


# ---------------------------------------------------------------- #1/#16 sender vazio não colapsa sessão
def test_webhook_parser_drops_empty_sender():
    from okami.channels.inbound_parsers import webhook_parser
    sms = webhook_parser("sms")
    assert sms(b"Body=oi") is None                        # sem From → None (não roteia p/ chat_id "")
    assert sms(b"From=%2B5511999&Body=oi") is not None    # com From → Inbound normal


def test_signal_parser_skips_empty_source():
    from okami.channels.inbound_parsers import parse_signal_receive
    assert parse_signal_receive([{"envelope": {"dataMessage": {"message": "oi"}}}]) == []   # sem source → dropa
    good = parse_signal_receive([{"envelope": {"source": "+55", "dataMessage": {"message": "oi"}}}])
    assert len(good) == 1 and good[0].chat_id == "+55"


# ---------------------------------------------------------------- #13/#14/#15 parser não crasha com tipo errado
def test_parsers_no_crash_on_wrong_type():
    from okami.channels.inbound_parsers import (
        parse_dingtalk_webhook, parse_qqbot_webhook, parse_wecom_webhook,
    )
    assert parse_dingtalk_webhook([]) is None             # lista onde espera dict
    assert parse_qqbot_webhook(["x"]) is None
    assert parse_wecom_webhook({"nao": "xml"}) is None     # dict onde espera XML string


# ---------------------------------------------------------------- #2 agent.yaml/identidade não world-readable
def test_agent_yaml_and_identity_are_0600(tmp_path, monkeypatch):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    from okami.cli._shared import _ensure_agent
    from okami.home import agents_dir
    _ensure_agent("bot", name="Bot", telegram_token="123:" + "ABCSECRET")   # token no agent.yaml
    base = agents_dir() / "bot"
    assert stat.S_IMODE(os.stat(base / "agent.yaml").st_mode) == 0o600        # token não vaza p/ outro user
    assert stat.S_IMODE(os.stat(base / "SOUL.md").st_mode) == 0o600


# ---------------------------------------------------------------- #20 MEDIA: caminho no fim de frase
def test_media_extracts_path_before_period():
    from okami.channels.media import extract_media
    _clean, items = extract_media("segue a imagem MEDIA:/tmp/foto.png.")
    assert any(m.path.endswith("foto.png") for m in items)                    # '.' final não impede a extração
