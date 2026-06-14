"""Item 14 — webhook server + verificadores de assinatura (fail-closed).

Cobre: sig do GitHub (X-Hub-Signature-256) valida/invalida; esquema do Stripe (t=/v1=) com
tolerância; rota deliver_only NÃO chama o handler do agente (sem LLM); rota de evento chama;
POST sem assinatura → 401. Servidor injetável p/ não abrir socket real.
"""

from __future__ import annotations

import hashlib
import hmac
import time


from okami.channels.webhook import WebhookRoute, WebhookServer
from okami.channels.webhook_sig import (
    verify_generic,
    verify_github,
    verify_hmac,
    verify_stripe,
)


# ── verificadores puros ────────────────────────────────────────────────────
def _gh_sig(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_github_sig_valida():
    secret, body = "shh", b'{"action":"opened"}'
    headers = {"X-Hub-Signature-256": _gh_sig(secret, body)}
    assert verify_github(secret, headers, body) is True


def test_github_sig_invalida_fail_closed():
    secret, body = "shh", b'{"action":"opened"}'
    headers = {"X-Hub-Signature-256": "sha256=deadbeef"}
    assert verify_github(secret, headers, body) is False
    # corpo adulterado depois de assinar → cai
    good = {"X-Hub-Signature-256": _gh_sig(secret, body)}
    assert verify_github(secret, good, body + b"x") is False


def test_github_sig_ausente_fail_closed():
    assert verify_github("shh", {}, b"body") is False


def test_stripe_esquema_valida_e_tolerancia():
    secret, body = "whsec_x", b'{"id":"evt_1"}'
    ts = int(time.time())
    signed = f"{ts}.".encode() + body
    v1 = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    headers = {"Stripe-Signature": f"t={ts},v1={v1}"}
    assert verify_stripe(secret, headers, body) is True
    # assinatura de v1 errado → cai
    bad = {"Stripe-Signature": f"t={ts},v1=00"}
    assert verify_stripe(secret, bad, body) is False


def test_stripe_fora_da_tolerancia_fail_closed():
    secret, body = "whsec_x", b'{"id":"evt_1"}'
    old = int(time.time()) - 9999          # bem fora da janela default
    signed = f"{old}.".encode() + body
    v1 = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    headers = {"Stripe-Signature": f"t={old},v1={v1}"}
    assert verify_stripe(secret, headers, body, tolerance=300) is False


def test_generic_header_configuravel():
    secret, body = "k", b"payload"
    mac = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    headers = {"X-Sig": mac}
    assert verify_generic(secret, headers, body, header="X-Sig") is True
    assert verify_generic(secret, {"X-Sig": "nope"}, body, header="X-Sig") is False
    assert verify_generic(secret, {}, body, header="X-Sig") is False


def test_verify_hmac_dispatch_por_provider():
    secret, body = "shh", b"hi"
    gh = {"X-Hub-Signature-256": _gh_sig(secret, body)}
    assert verify_hmac("github", secret, gh, body) is True
    assert verify_hmac("github", secret, {}, body) is False
    # provider desconhecido → fail-closed
    assert verify_hmac("???", secret, gh, body) is False


# ── servidor (injetável, sem socket) ───────────────────────────────────────
def _make_server(routes, handle):
    # host/port não abrem socket: só guardamos config; do_POST é exercido direto.
    return WebhookServer(host="127.0.0.1", port=0, routes=routes, handle=handle, serve=False)


def test_deliver_only_nao_chama_handler_do_agente():
    chamou = {"agente": 0, "deliver": []}

    def handle(prompt, route):
        chamou["agente"] += 1

    def deliver(payload, route):
        chamou["deliver"].append(payload)

    secret = "shh"
    routes = {
        "/gh": WebhookRoute(provider="github", secret=secret,
                            deliver_only=True, deliver=deliver, chat_id="ops"),
    }
    srv = _make_server(routes, handle)
    body = b'{"action":"opened"}'
    status, _ = srv.handle_post("/gh", {"X-Hub-Signature-256": _gh_sig(secret, body)}, body)
    assert status == 200
    assert chamou["agente"] == 0                 # rota deliver_only NÃO roda o agente (sem LLM)
    assert chamou["deliver"] and b"opened" in chamou["deliver"][0]


def test_rota_de_evento_chama_handler_do_agente():
    visto = {}

    def handle(prompt, route):
        visto["prompt"] = prompt
        visto["route"] = route

    secret = "shh"
    routes = {
        "/deploy": WebhookRoute(provider="github", secret=secret, chat_id="ops"),
    }
    srv = _make_server(routes, handle)
    body = b'{"action":"push"}'
    status, _ = srv.handle_post("/deploy", {"X-Hub-Signature-256": _gh_sig(secret, body)}, body)
    assert status == 200
    assert "prompt" in visto                       # rota de evento → entrega prompt sintetizado
    assert visto["route"].chat_id == "ops"


def test_sem_assinatura_401():
    def handle(prompt, route):
        raise AssertionError("não deveria chamar o agente")

    secret = "shh"
    routes = {"/gh": WebhookRoute(provider="github", secret=secret, chat_id="ops")}
    srv = _make_server(routes, handle)
    body = b'{"x":1}'
    status, _ = srv.handle_post("/gh", {}, body)   # sem header de assinatura
    assert status == 401


def test_rota_desconhecida_404():
    srv = _make_server({}, lambda p, r: None)
    status, _ = srv.handle_post("/inexistente", {}, b"{}")
    assert status == 404


def test_assinatura_invalida_401_nao_chama_agente():
    def handle(prompt, route):
        raise AssertionError("assinatura inválida não pode chegar no agente")

    secret = "shh"
    routes = {"/gh": WebhookRoute(provider="github", secret=secret, chat_id="ops")}
    srv = _make_server(routes, handle)
    status, _ = srv.handle_post("/gh", {"X-Hub-Signature-256": "sha256=00"}, b"{}")
    assert status == 401
