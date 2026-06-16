"""#19 integrações de nicho (paridade Hermes): X/Grok search, Home Assistant, Feishu — config-driven."""
from __future__ import annotations

from types import SimpleNamespace


def _cfg(integrations=None):
    return SimpleNamespace(integrations=integrations or {})


# ── X/Twitter (Grok) search ──
def test_x_config_none_without_setup():
    from okami.integrations.x_search import x_config
    assert x_config(_cfg()) is None
    assert x_config(_cfg({"x": {}})) is None               # sem api_key_env → não configurado


def test_x_search_builds_request_and_parses(monkeypatch):
    from okami.integrations.x_search import x_search
    monkeypatch.setenv("XAI_KEY", "k")
    cfg = _cfg({"x": {"api_key_env": "XAI_KEY", "model": "grok-4"}})
    sent = {}

    def _post(url, body, headers):
        sent["url"] = url
        sent["auth"] = headers.get("Authorization")
        sent["body"] = body
        return {"choices": [{"message": {"content": "o X diz X",
                 "citations": ["https://x.com/a/1"]}}]}

    res = x_search(cfg, "o que dizem sobre lobos?", _post=_post)
    assert res["answer"] == "o X diz X" and "https://x.com/a/1" in res["citations"]
    assert sent["auth"] == "Bearer k" and "api.x.ai" in sent["url"]
    assert sent["body"]["model"] == "grok-4"


def test_x_search_without_key_raises(monkeypatch):
    import pytest

    from okami.integrations.x_search import x_search
    monkeypatch.delenv("XAI_KEY", raising=False)
    with pytest.raises(RuntimeError, match="XAI_KEY"):
        x_search(_cfg({"x": {"api_key_env": "XAI_KEY"}}), "q", _post=lambda *a: {})


def test_x_search_tool_registered_and_check(tmp_path):
    from okami.core.tools.base import ToolContext
    from okami.core.tools.x_search import XSearch
    assert XSearch().run({"query": "q"}, ToolContext(workspace=tmp_path, cfg=_cfg())).ok is False  # sem config


# ── Home Assistant ──
def test_ha_blocks_dangerous_domain():
    import pytest

    from okami.integrations.homeassistant import call_service
    monkeyenv = SimpleNamespace()  # noqa: F841
    with pytest.raises(ValueError, match="bloqueado"):
        call_service(_cfg({"homeassistant": {"url": "http://h", "token_env": "HA"}}),
                     "shell_command", "run", {}, _post=lambda *a: {})


def test_ha_validates_entity_and_lists(monkeypatch):
    from okami.integrations.homeassistant import get_state
    monkeypatch.setenv("HA", "tok")
    cfg = _cfg({"homeassistant": {"url": "http://h", "token_env": "HA"}})
    seen = {}

    def _get(url, headers):
        seen["url"] = url
        seen["auth"] = headers.get("Authorization")
        return {"entity_id": "light.sala", "state": "on"}

    st = get_state(cfg, "light.sala", _get=_get)
    assert st["state"] == "on" and seen["auth"] == "Bearer tok"
    assert "/api/states/light.sala" in seen["url"]


def test_ha_rejects_malformed_entity():
    import pytest

    from okami.integrations.homeassistant import get_state
    with pytest.raises(ValueError):
        get_state(_cfg({"homeassistant": {"url": "http://h", "token_env": "HA"}}),
                  "../../api/config", _get=lambda *a: {})


def test_ha_call_service_posts(monkeypatch):
    from okami.integrations.homeassistant import call_service
    monkeypatch.setenv("HA", "tok")
    cfg = _cfg({"homeassistant": {"url": "http://h", "token_env": "HA"}})
    seen = {}

    def _post(url, body, headers):
        seen["url"] = url
        return [{"entity_id": "light.sala", "state": "on"}]

    out = call_service(cfg, "light", "turn_on", {"entity_id": "light.sala"}, _post=_post)
    assert "/api/services/light/turn_on" in seen["url"] and out


def test_ha_tool_registered():
    from okami.core.tools.registry import default_registry
    assert "homeassistant" in default_registry()


# ── Feishu ──
def test_feishu_reads_doc(monkeypatch):
    from okami.integrations.feishu import read_doc
    monkeypatch.setenv("FEISHU_SECRET", "s")
    cfg = _cfg({"feishu": {"app_id": "app", "app_secret_env": "FEISHU_SECRET"}})
    calls = []

    def _post(url, body, headers):
        calls.append(url)
        return {"tenant_access_token": "tat", "expire": 7200}     # token endpoint

    def _get(url, headers):
        calls.append(url)
        return {"data": {"content": "conteúdo do doc"}}

    res = read_doc(cfg, "doctoken123", _post=_post, _get=_get)
    assert "conteúdo do doc" in res
    assert any("tenant_access_token" in u for u in calls) and any("raw_content" in u for u in calls)


def test_feishu_without_secret_raises(monkeypatch):
    import pytest

    from okami.integrations.feishu import read_doc
    monkeypatch.delenv("FEISHU_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="FEISHU_SECRET"):
        read_doc(_cfg({"feishu": {"app_id": "a", "app_secret_env": "FEISHU_SECRET"}}), "d")


def test_feishu_tool_registered():
    from okami.core.tools.registry import default_registry
    assert "feishu_doc_read" in default_registry()


# ── #19 bug-hunt fixes ──
def test_feishu_rejects_path_injection_in_doc_token():
    import pytest

    from okami.integrations.feishu import read_doc
    cfg = _cfg({"feishu": {"app_id": "a", "app_secret_env": "FEISHU_SECRET"}})
    for evil in ("../../auth/v3/tenant_access_token", "doc/../../x", "a b", "x?y=1"):
        with pytest.raises(ValueError):
            read_doc(cfg, evil, _post=lambda *a: {"tenant_access_token": "t"}, _get=lambda *a: {})


def test_x_search_tool_redacts_error(monkeypatch, tmp_path):
    from okami.core.tools.base import ToolContext
    from okami.core.tools.x_search import XSearch
    fake = "sk-" + "ABCDEFGHIJ1234567890ABCDEFGHIJ"   # comprimento realista (redact mascara ≥20)
    cfg = _cfg({"x": {"api_key_env": "XAI_KEY"}})
    monkeypatch.setattr("okami.integrations.x_search.x_search",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError(f"erro com {fake} no header")))
    res = XSearch().run({"query": "q"}, ToolContext(workspace=tmp_path, cfg=cfg))
    assert res.ok is False and "ABCDEFGHIJ1234567890" not in res.output   # chave redigida
