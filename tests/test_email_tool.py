"""Gap de capacidade (o dono pediu 'ler um email'): existia transporte (EmailChannel) mas NENHUMA tool
pro agente buscar/ler/enviar email sob demanda — igual faltava gerar PDF. Tool `email` (list/read/send)
sobre imaplib/smtplib, config em integrations.email, corpo como DADO não-confiável, envio gated."""
from __future__ import annotations

from types import SimpleNamespace

from okami.core.tools.mail import Email


def _ctx(integrations=None):
    cfg = SimpleNamespace(integrations=integrations or {})
    return SimpleNamespace(cfg=cfg, workspace=".")


def test_email_run_without_config_is_actionable():
    r = Email().run({"action": "list"}, _ctx())
    assert r.ok is False and "integrations.email" in r.output    # diz COMO configurar, não crash


def test_email_unknown_action_clear_error():
    ctx = _ctx({"email": {"user": "a@b.c", "app_password": "pw"}})
    r = Email().run({"action": "voar"}, ctx)
    assert r.ok is False and "action" in r.output                # erro acionável


def test_email_list_handles_connection_error_gracefully():
    """IMAP inacessível (host fake/porta morta) → ToolResult(False) acionável, NUNCA exception/travamento."""
    ctx = _ctx({"email": {"user": "a@b.c", "app_password": "pw",
                          "imap_host": "127.0.0.1", "imap_port": 1}})
    r = Email().run({"action": "list"}, ctx)
    assert r.ok is False and ("email" in r.output.lower() or "imap" in r.output.lower())


def test_email_send_requires_to_and_body():
    ctx = _ctx({"email": {"user": "a@b.c", "app_password": "pw"}})
    r = Email().run({"action": "send", "subject": "oi"}, ctx)    # sem 'to'/'body'
    assert r.ok is False and ("to" in r.output.lower() or "destinatário" in r.output.lower())


def test_email_send_is_sensitive():
    """Enviar email é ação pra FORA → marcada sensível p/ passar pela aprovação."""
    from okami.core.tool_registry import TOOL_REGISTRY
    spec = next((s for s in TOOL_REGISTRY if s.name == "email"), None)
    assert spec is not None and spec.danger == "sensitive"


def test_email_registered():
    from okami.core.tools.registry import default_registry
    assert "email" in default_registry()
