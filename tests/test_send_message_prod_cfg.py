"""send_message(target) estava MORTO em produção (config-drop trap): o runner passa ctx.cfg = OBJETO
OkamiConfig (runner.py:352), e `channels` foi deliberadamente mantido FORA do OkamiConfig (token=segredo).
O código fazia `cfg.get("channels")` só quando `isinstance(cfg, dict)` → com o objeto isso é False → token
None → SEMPRE 'sem token'. Os testes antigos passavam cfg=dict, mascarando a realidade de produção.
Fix: ler o token do RAW (load_raw + token/token_env), como o próprio gateway faz."""
from __future__ import annotations


def _okami_cfg():
    """OkamiConfig REAL via build_config (não dict) — o tipo que o runner passa em produção."""
    from okami.config import build_config
    return build_config({"default_provider": "p", "providers": {"p": {"name": "p", "model": "openai/x"}}})


def _fake_tg(monkeypatch):
    import okami.channels.telegram as tg
    sent = []

    class FakeTG:
        def __init__(self, token, *a, **k):
            self.token = token

        def send(self, chat_id, text):
            sent.append((self.token, chat_id, text))
    monkeypatch.setattr(tg, "TelegramChannel", FakeTG)
    return sent


def test_send_target_works_with_okamiconfig_object(monkeypatch, tmp_path):
    from okami.core.tools.base import ToolContext
    from okami.core.tools.notify import SendMessage
    fake_token = "999" + ":" + "AA" + "faketoken"             # montado por concat (sem literal de segredo)
    monkeypatch.setattr("okami.config.load_raw",
                        lambda path=None: ({"channels": {"telegram": {"token": fake_token}}}, tmp_path))
    sent = _fake_tg(monkeypatch)
    ctx = ToolContext(workspace=".", cfg=_okami_cfg())        # OBJETO, como em produção (não dict)
    res = SendMessage().run({"text": "oi", "target": "555"}, ctx)
    assert res.ok and res.effect is True
    assert sent == [(fake_token, "555", "oi")]


def test_send_target_resolves_token_env_from_raw(monkeypatch, tmp_path):
    from okami.core.tools.base import ToolContext
    from okami.core.tools.notify import SendMessage
    monkeypatch.setenv("MY_TG_TOKEN_X", "777" + ":" + "envtoken")   # padrão seguro: token_env, não literal
    monkeypatch.setattr("okami.config.load_raw",
                        lambda path=None: ({"channels": {"telegram": {"token_env": "MY_TG_TOKEN_X"}}}, tmp_path))
    sent = _fake_tg(monkeypatch)
    ctx = ToolContext(workspace=".", cfg=_okami_cfg())
    res = SendMessage().run({"text": "alô", "target": "42"}, ctx)
    assert res.ok and sent == [("777:envtoken", "42", "alô")]
