"""Servidor de webhook (item 14) — recebe POSTs externos (GitHub/Stripe/genérico), verifica a
assinatura HMAC (fail-closed) e ou (a) ENTREGA o payload cru a um callback sem rodar o agente
(`deliver_only` → sem LLM, p/ notificação pura), ou (b) sintetiza um prompt e chama o handler do
agente.

Stdlib só (http.server ThreadingHTTPServer) — SEM dep nova. A lógica de roteamento mora em
`WebhookServer.handle_post`, separada do socket, p/ os testes exercerem do_POST sem abrir porta.
Deny-by-default: rota desconhecida → 404; assinatura ausente/inválida → 401.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from okami.channels.webhook_sig import verify_hmac
from okami.core.redact import redact

_MAX_BODY = 1 << 20          # 1 MiB: teto de corpo p/ POST não-autenticado (anti-DoS de memória)


@dataclass
class WebhookRoute:
    """Uma rota montada no servidor.

    provider/secret: como validar a assinatura. `deliver_only`+`deliver`: entrega o payload cru a
    um callback SEM rodar o agente (notificação pura, zero LLM). `chat_id`: para onde a resposta do
    agente volta (canal de entrega). `header`/`tolerance`: ajustes do verificador genérico/Stripe.
    `prompt_prefix`: texto opcional colado antes do payload ao sintetizar o prompt do agente.
    """

    provider: str = "generic"
    secret: str = ""
    chat_id: str = ""
    deliver_only: bool = False
    deliver: Callable[[bytes, "WebhookRoute"], None] | None = None
    header: str = "X-Signature"
    tolerance: int = 300
    prompt_prefix: str = ""
    parser: Callable[[bytes], object] | None = None   # #20: body→Inbound (msg de plataforma) p/ entregar
    #                                                   o TEXTO real ao agente em vez do prompt sintetizado


def _synthesize_prompt(route: WebhookRoute, body: bytes) -> str:
    """Monta o prompt sintetizado que vai pro agente (corpo redigido, nunca cru pro modelo)."""
    payload = redact(body.decode("utf-8", "replace"))
    prefix = route.prompt_prefix or f"Chegou um webhook de {route.provider}. Conteúdo:"
    return f"{prefix}\n\n{payload}"


class WebhookServer:
    """Roteador de webhooks. `serve=True` sobe o socket (ThreadingHTTPServer); `serve=False` só
    guarda a config (testes / wire posterior pelo dono do startup)."""

    def __init__(self, *, host: str = "127.0.0.1", port: int = 8788,
                 routes: dict[str, WebhookRoute] | None = None,
                 handle: Callable[[str, WebhookRoute], None] | None = None,
                 serve: bool = False):
        self.host = host
        self.port = int(port)
        self.routes = dict(routes or {})
        self.handle = handle           # callback(prompt, route) → roda o agente
        self._httpd = None
        if serve:
            self.start()

    # ── lógica pura (testável sem socket) ──────────────────────────────────
    def handle_post(self, path: str, headers, body: bytes) -> tuple[int, bytes]:
        """Processa um POST. Devolve (status, corpo de resposta). NÃO toca em socket.

        404 rota desconhecida · 401 assinatura ausente/inválida · 200 entregue/encaminhado.
        """
        route = self.routes.get(path)
        if route is None:
            return 404, b'{"erro":"rota desconhecida"}'

        if not verify_hmac(route.provider, route.secret, headers, body,
                           header=route.header, tolerance=route.tolerance):
            return 401, b'{"erro":"assinatura invalida"}'   # fail-closed: nada roda sem assinatura

        if route.deliver_only:
            # notificação pura: repassa o payload cru ao callback, SEM rodar o agente (zero LLM)
            if route.deliver is not None:
                route.deliver(body, route)
            return 200, b'{"ok":true,"modo":"deliver_only"}'

        # rota de mensagem de PLATAFORMA (#20): parseia o callback → Inbound e entrega o TEXTO real
        # (não o prompt genérico). Payload que não é texto (imagem/evento) → ignorado (200).
        if route.parser is not None:
            try:
                inb = route.parser(body)
            except Exception:  # noqa: BLE001 — payload malformado não derruba o servidor
                inb = None
            if inb is None or not getattr(inb, "text", ""):
                return 200, b'{"ok":true,"modo":"ignorado"}'
            route.chat_id = getattr(inb, "chat_id", "") or route.chat_id   # resposta volta p/ o remetente
            if self.handle is not None:
                self.handle(inb.text, route)
            return 200, b'{"ok":true}'

        # rota de evento: sintetiza prompt e chama o handler do agente
        if self.handle is not None:
            self.handle(_synthesize_prompt(route, body), route)
        return 200, b'{"ok":true}'

    # ── socket real (só quando serve=True) ─────────────────────────────────
    def start(self) -> None:  # pragma: no cover - exercício de socket real
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        server = self

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 (nome exigido pelo BaseHTTPRequestHandler)
                try:
                    try:                               # Content-Length hostil (não-num/negativo/ausente) → 0
                        length = int(self.headers.get("Content-Length") or 0)
                    except (TypeError, ValueError):
                        length = 0
                    if length < 0:
                        length = 0
                    if length > _MAX_BODY:               # corpo gigante não-autenticado → 413, sem alocar
                        status, resp = 413, b'{"erro":"payload grande demais"}'
                    else:
                        body = self.rfile.read(length) if length else b""
                        status, resp = server.handle_post(self.path, dict(self.headers), body)
                except Exception:  # noqa: BLE001 — nunca propaga (conexão resetada silenciosa / crash)
                    status, resp = 400, b'{"erro":"requisicao invalida"}'
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)

            def log_message(self, *a):   # silêncio: nada de poluir stderr
                pass

        self._httpd = ThreadingHTTPServer((self.host, self.port), _Handler)

    def serve_forever(self) -> None:  # pragma: no cover - loop bloqueante
        if self._httpd is None:
            self.start()
        self._httpd.serve_forever()

    def stop(self) -> None:  # pragma: no cover
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
