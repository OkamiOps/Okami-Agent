"""Hot-reload de config (#12): ConfigReloader (mtime+validação) + apply_config + /reload no gateway."""

from __future__ import annotations

from types import SimpleNamespace

from okami.core.reload import ConfigReloader


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_reloader_detects_change(tmp_path):
    f = tmp_path / "okami.yaml"
    f.write_text("a: 1\n", encoding="utf-8")
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return SimpleNamespace(loaded=calls["n"])

    rl = ConfigReloader([f], loader=loader)
    assert rl.poll().changed is False                 # sem mudança
    import os
    import time
    time.sleep(0.01)
    os.utime(f, (time.time() + 5, time.time() + 5))    # "edita" (mtime muda)
    res = rl.poll()
    assert res.changed and res.ok and res.config.loaded == 1
    assert rl.poll().changed is False                  # já consumiu a mudança


def test_reloader_keeps_old_on_invalid(tmp_path):
    f = tmp_path / "okami.yaml"
    f.write_text("a: 1\n", encoding="utf-8")

    def bad_loader():
        raise ValueError("default_provider faltando")

    rl = ConfigReloader([f], loader=bad_loader)
    rl._mtimes = {str(f): 0.0}                          # força changed
    res = rl.poll()
    assert res.changed and not res.ok and "default_provider" in res.error


def _bare_ep():
    from okami.gateway import AgentEndpoint
    ep = AgentEndpoint.__new__(AgentEndpoint)
    ep.approval_mode = "manual"
    ep.cfg = SimpleNamespace(approvals={"mode": "manual"}, sandbox={"backend": "local"})
    return ep


def test_apply_config_updates_safe_fields():
    ep = _bare_ep()
    new = SimpleNamespace(approvals={"mode": "smart"}, sandbox={"backend": "auto"})
    changed = ep.apply_config(new)
    assert ep.approval_mode == "smart" and ep.cfg is new
    assert any("aprovação=smart" in c for c in changed) and "sandbox" in changed


def test_apply_config_no_change():
    ep = _bare_ep()
    same = SimpleNamespace(approvals={"mode": "manual"}, sandbox={"backend": "local"})
    assert ep.apply_config(same) == []


def test_gateway_reload_command(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "okami.yaml").write_text(
        "default_provider: p\nproviders:\n  p:\n    tier: free\n    model: m\napprovals:\n  mode: smart\n",
        encoding="utf-8")

    class _Ch:
        def __init__(self):
            self.sent = []

        def allowed(self, c):
            return True

        def send(self, c, t):
            self.sent.append(t)

    ep = _bare_ep()
    ep.channel = _Ch()
    ep._pending = {}
    ep.sessions = {}

    # /reload via reload_config direto (evita o roteamento completo de handle)
    ok, msg = ep.reload_config()
    assert ok and "smart" in msg and ep.approval_mode == "smart"


def test_gateway_reload_invalid_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "okami.yaml").write_text("providers: {}\n", encoding="utf-8")   # sem default_provider → inválida
    ep = _bare_ep()
    ok, msg = ep.reload_config()
    assert not ok and ep.approval_mode == "manual"     # manteve a anterior
