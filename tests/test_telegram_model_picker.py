"""UX do picker de provider/modelo no Telegram."""

from okami.config import build_config
from okami.gateway.endpoint_commands import EndpointCommandsMixin


def _cfg():
    return build_config({
        "default_provider": "local",
        "providers": {
            "local": {
                "model": "openai/qwen2.5",
                "api_base": "http://localhost:1234/v1",
                "api_key": "local-only",
                "auth": "api_key",
                "transport": "litellm",
                "tier": "local",
                "context_window": 32768,
                "models": ["qwen2.5", "llama3.1"],
            },
            "codex": {
                "model": "openai-codex/gpt-5.4-mini",
                "auth": "oauth_subscription",
                "transport": "codex_oauth",
                "tier": "strong",
                "context_window": 256000,
                "models": ["gpt-5.4-mini"],
            },
        },
    })


class _PickerChannel:
    def __init__(self):
        self.calls = []

    def send(self, chat_id, text):
        self.calls.append(("plain", chat_id, text))

    def send_model_picker(self, chat_id, text, options):
        self.calls.append(("picker", chat_id, text, options))


class _Endpoint(EndpointCommandsMixin):
    def __init__(self):
        self.cfg = _cfg()
        self.channel = _PickerChannel()


def test_models_command_sends_catalog_picker_with_readiness_and_context():
    ep = _Endpoint()

    ep._send_models("42")

    kind, chat_id, text, options = ep.channel.calls[0]
    assert kind == "picker" and chat_id == "42"
    assert "local" in text and "codex" in text
    assert any("ready" in hint and "context" in hint for _, _, hint in options)
    assert any(token == "codex/gpt-5.4-mini" for token, _, _ in options)
    assert all("local-only" not in (text + repr(options)) for _ in [0])


def test_telegram_model_callback_is_short_and_catalog_bound(monkeypatch):
    from okami.channels.telegram import TelegramChannel

    ch = TelegramChannel("tok", allow_chats=[55])
    sent = {}
    monkeypatch.setattr(ch.client, "send_model_picker",
                        lambda chat, text, buttons, thread=None: sent.update(
                            chat=chat, text=text, buttons=buttons, thread=thread))
    ch.send_model_picker("99", "Escolha", [("codex/gpt-5.4-mini", "codex", "ready")])
    callback = sent["buttons"][0][0]["callback_data"]
    assert len(callback.encode("utf-8")) <= 64

    updates = [{"update_id": 1, "callback_query": {"id": "cb", "data": callback,
                "from": {"id": 55}, "message": {"chat": {"id": 99}}}}]
    monkeypatch.setattr(ch.client, "get_updates", lambda **kwargs: updates)
    monkeypatch.setattr(ch.client, "answer_callback", lambda *args, **kwargs: None)
    inbound = ch.poll()
    assert inbound[0].text == "/model codex/gpt-5.4-mini"

    updates[0]["callback_query"]["data"] = "okmodel:999"
    assert ch.poll() == []


def test_telegram_menu_has_provider_model_commands():
    from okami.commands import telegram_menu

    names = {item["command"] for item in telegram_menu()}
    assert {"models", "model", "providers"} <= names
