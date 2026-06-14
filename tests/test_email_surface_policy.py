"""Wiring da pesquisa #7 — superfícies REMOTAS novas (email, webhook) e parsing de config.

E-mail e webhook são portas ABERTAS (qualquer um manda): a tool policy precisa tratá-las como o
Telegram — deny-by-default de shell/exec/processo. E o config precisa parsear channels.email
(host/port/user/app-password via secret_sources) e gateway.webhook (bind/port/secret/deliver_only)
sem quebrar nada (campos novos, default vazio)."""

from __future__ import annotations


# ── tool policy: email e webhook são remotas deny-by-default ─────────────────
def test_email_surface_denies_shell_and_exec():
    from okami.core.tool_policy import denied
    assert denied("email", "run_shell") is True
    assert denied("email", "execute_code") is True
    assert denied("email", "process_start") is True
    assert denied("email", "spawn") is True


def test_webhook_surface_denies_shell_and_exec():
    from okami.core.tool_policy import denied
    assert denied("webhook", "run_shell") is True
    assert denied("webhook", "execute_code") is True
    assert denied("webhook", "process_start") is True
    assert denied("webhook", "spawn") is True


def test_email_webhook_in_deny_by_surface():
    # anti-drift: as superfícies existem no mapa de política (senão denied() cairia no default vazio)
    from okami.core.tool_policy import _DENY_BY_SURFACE
    assert "email" in _DENY_BY_SURFACE
    assert "webhook" in _DENY_BY_SURFACE


def test_email_surface_allows_terminal_tools():
    # terminais de controle nunca somem, mesmo em superfície remota
    from okami.core.tool_policy import denied
    assert denied("email", "respond") is False
    assert denied("webhook", "task_complete") is False


def test_email_surface_allows_read_file():
    # deny-by-default é só shell/processo/spawn — leitura segue permitida na superfície remota
    from okami.core.tool_policy import denied
    assert denied("email", "read_file") is False


# ── channel registry: ChannelSpec email presente ────────────────────────────
def test_email_channel_spec_registered():
    from okami.gateway.channel_registry import REGISTRY
    assert "email" in REGISTRY
    spec = REGISTRY["email"]
    assert spec.surface == "email"
    assert spec.cls == "EmailChannel"
    assert spec.module == "okami.channels.email"


def test_email_in_surface_map():
    from okami.gateway.channel_registry import surface_map
    assert surface_map().get("email") == "email"


# ── config parsing: channels.email ──────────────────────────────────────────
def test_parse_email_channel_basico():
    from okami.config import parse_email_channel
    raw = {
        "user": "me@gmail.com",
        "app_password": "abcd efgh ijkl",
        "host": "imap.gmail.com",
        "port": 993,
        "allow": ["alice@example.com", "bob@example.com"],
    }
    parsed = parse_email_channel(raw)
    assert parsed["user"] == "me@gmail.com"
    assert parsed["app_password"] == "abcd efgh ijkl"
    assert parsed["imap_host"] == "imap.gmail.com"
    assert parsed["imap_port"] == 993
    assert parsed["allow_chats"] == ["alice@example.com", "bob@example.com"]
    assert parsed["allow_all"] is False


def test_parse_email_channel_app_password_via_secret_env(monkeypatch):
    # app-password pode vir de uma env-var (secret_sources injeta no boot) — nunca em texto puro no YAML
    from okami.config import parse_email_channel
    monkeypatch.setenv("OKAMI_EMAIL_PW", "segredo-do-cofre")
    parsed = parse_email_channel({"user": "me@gmail.com", "app_password_env": "OKAMI_EMAIL_PW"})
    assert parsed["app_password"] == "segredo-do-cofre"


def test_parse_email_channel_defaults_gmail():
    from okami.config import parse_email_channel
    parsed = parse_email_channel({"user": "me@gmail.com", "app_password": "pw"})
    assert parsed["imap_host"] == "imap.gmail.com"
    assert parsed["smtp_host"] == "smtp.gmail.com"
    assert parsed["allow_all"] is False        # deny-by-default


# ── config parsing: gateway.webhook ─────────────────────────────────────────
def test_parse_webhook_basico():
    from okami.config import parse_webhook
    raw = {
        "bind": "127.0.0.1",
        "port": 8099,
        "routes": {"deploy": {"secret": "s3cr3t"}},
        "deliver_only": True,
    }
    parsed = parse_webhook(raw)
    assert parsed["bind"] == "127.0.0.1"
    assert parsed["port"] == 8099
    assert parsed["deliver_only"] is True
    assert parsed["routes"]["deploy"]["secret"] == "s3cr3t"


def test_parse_webhook_defaults():
    from okami.config import parse_webhook
    parsed = parse_webhook({})
    # default deliver_only=True: webhook não roda o agente sem opt-in (porta aberta segura)
    assert parsed["deliver_only"] is True
    assert parsed["routes"] == {}
    assert isinstance(parsed["port"], int)


def test_parse_webhook_secret_via_env(monkeypatch):
    from okami.config import parse_webhook
    monkeypatch.setenv("OKAMI_HOOK_SECRET", "do-cofre")
    parsed = parse_webhook({"routes": {"ci": {"secret_env": "OKAMI_HOOK_SECRET"}}})
    assert parsed["routes"]["ci"]["secret"] == "do-cofre"
