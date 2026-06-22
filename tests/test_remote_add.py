"""Onda 2: remote_add — o agente cadastra um host SSH/Tailscale pelo chat (persiste em okami.local.yaml),
liberando o alias no remote_connect (inclusive no Telegram via allowlist). Valida o host (anti-injeção)."""
from __future__ import annotations


def test_set_local_writes_dotted_key(tmp_path, monkeypatch):
    import okami.config as cfg
    monkeypatch.setattr(cfg, "config_dir", lambda: tmp_path)
    cfg.set_local("remote.hosts.prod", {"host": "user@1.2.3.4", "via": "ssh"})
    import yaml
    raw = yaml.safe_load((tmp_path / "okami.local.yaml").read_text(encoding="utf-8"))
    assert raw["remote"]["hosts"]["prod"]["host"] == "user@1.2.3.4"      # merge dotted correto


def test_remote_add_tool_persists_and_validates(tmp_path, monkeypatch):
    import okami.config as cfg
    monkeypatch.setattr(cfg, "config_dir", lambda: tmp_path)
    from okami.core.tools.base import ToolContext
    from okami.core.tools.remote import RemoteAdd
    ctx = ToolContext(workspace=tmp_path)
    ok = RemoteAdd().run({"alias": "vps2", "host": "okami@10.0.0.5"}, ctx)
    assert ok.ok and "vps2" in ok.output
    import yaml
    raw = yaml.safe_load((tmp_path / "okami.local.yaml").read_text(encoding="utf-8"))
    assert raw["remote"]["hosts"]["vps2"] == {"host": "okami@10.0.0.5", "via": "ssh"}   # '@' → ssh


def test_remote_add_rejects_injection_host(tmp_path, monkeypatch):
    import okami.config as cfg
    monkeypatch.setattr(cfg, "config_dir", lambda: tmp_path)
    from okami.core.tools.base import ToolContext
    from okami.core.tools.remote import RemoteAdd
    res = RemoteAdd().run({"alias": "x", "host": "-oProxyCommand=evil"}, ToolContext(workspace=tmp_path))
    assert not res.ok                                                    # host '-' (injeção de flag ssh) recusado


def test_remote_add_registered():
    from okami.core.tools.registry import default_registry
    assert "remote_add" in default_registry()
