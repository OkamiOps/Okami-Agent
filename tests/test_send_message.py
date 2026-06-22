"""Tool send_message (caça field-fail, capability gap): o agente não tinha como mandar uma mensagem de
texto direta a um canal/target sem rodar o LLM (notify só alcança o DONO do canal atual). Entrega via o
token do PRÓPRIO agente (ctx.cfg.channels), approval-gated (danger=sensitive); sem target → cai no dono."""
from __future__ import annotations


def _ctx(cfg=None, notify=None):
    from okami.core.tools.base import ToolContext
    return ToolContext(workspace=".", cfg=cfg, notify=notify)


def test_send_to_target_uses_agent_token(monkeypatch):
    import okami.channels.telegram as tg
    sent = []

    class FakeTG:
        def __init__(self, token, *a, **k):
            self.token = token

        def send(self, chat_id, text):
            sent.append((self.token, chat_id, text))
    monkeypatch.setattr(tg, "TelegramChannel", FakeTG)
    from okami.core.tools.notify import SendMessage
    ctx = _ctx(cfg={"channels": {"telegram": {"token": "123:ABC"}}})
    res = SendMessage().run({"text": "backup ok ✓", "target": "555"}, ctx)
    assert res.ok and res.effect is True
    assert sent == [("123:ABC", "555", "backup ok ✓")]      # token do agente + target + texto


def test_send_no_target_falls_back_to_owner_notify():
    got = []
    ctx = _ctx(cfg={"channels": {"telegram": {"token": "x"}}}, notify=lambda m: got.append(m) or True)
    from okami.core.tools.notify import SendMessage
    res = SendMessage().run({"text": "oi dono"}, ctx)
    assert res.ok and got == ["oi dono"]                    # sem target → entrega ao dono


def test_send_to_target_without_token_is_clean_error():
    from okami.core.tools.notify import SendMessage
    res = SendMessage().run({"text": "oi", "target": "555"}, _ctx(cfg={}))
    assert res.ok is False and "token" in res.output.lower()


def test_send_empty_text_rejected():
    from okami.core.tools.notify import SendMessage
    assert SendMessage().run({"text": "   "}, _ctx()).ok is False


def test_send_unsupported_channel():
    from okami.core.tools.notify import SendMessage
    res = SendMessage().run({"text": "oi", "target": "5", "channel": "slack"},
                            _ctx(cfg={"channels": {"telegram": {"token": "x"}}}))
    assert res.ok is False and "telegram" in res.output.lower()


def test_send_error_is_redacted(monkeypatch):
    import okami.channels.telegram as tg

    class BoomTG:
        def __init__(self, token, *a, **k):
            pass

        def send(self, chat_id, text):
            raise RuntimeError("falhou com token sk-SUPERSECRETVALUE1234567890")
    monkeypatch.setattr(tg, "TelegramChannel", BoomTG)
    from okami.core.tools.notify import SendMessage
    res = SendMessage().run({"text": "oi", "target": "5"},
                            _ctx(cfg={"channels": {"telegram": {"token": "t"}}}))
    assert res.ok is False and "SUPERSECRETVALUE" not in res.output   # erro redigido


def test_send_message_registered():
    from okami.core.tools.registry import default_registry
    assert "send_message" in default_registry()
