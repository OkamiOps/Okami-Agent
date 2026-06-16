"""Web dashboard leve (#12, port enxuto do Hermes web/ + web_server.py).

DIFERENÇA do Hermes (React/Vite/FastAPI): aqui é stdlib `http.server` + HTML server-rendered — ZERO dep
nova (constraint do Okami), mas entrega o valor: status/sessões/config num navegador, p/ quem não vive no
CLI. `okami gui` sobe e abre no browser. Read-only por padrão. Localhost.
"""
from __future__ import annotations

import html as _html


def render_status_html(data: dict) -> str:
    """HTML de status a partir de `data` (agent/sessions/uptime/…)."""
    rows = "".join(
        f"<tr><th style='text-align:left;padding:4px 12px'>{_html.escape(str(k))}</th>"
        f"<td style='padding:4px 12px'>{_html.escape(str(v))}</td></tr>"
        for k, v in (data or {}).items()
    )
    return (
        "<!doctype html><html lang='pt-br'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Okami</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:680px;margin:40px auto;padding:0 16px}"
        "h1{font-weight:600}table{border-collapse:collapse;width:100%}"
        "tr:nth-child(even){background:#f6f6f6}</style></head>"
        "<body><h1>🐺 Okami — status</h1>"
        f"<table>{rows}</table>"
        "<p style='color:#888;margin-top:24px'>read-only · localhost</p></body></html>"
    )


def route(path: str, *, status_provider=None) -> tuple:
    """Roteamento puro p/ o handler: devolve (code, content_type, body)."""
    if path in ("/", "/index.html"):
        data = status_provider() if status_provider else {"status": "online"}
        return 200, "text/html; charset=utf-8", render_status_html(data)
    if path == "/healthz":
        return 200, "text/plain", "ok"
    return 404, "text/plain", "not found"


def serve_dashboard(port: int = 9119, *, host: str = "127.0.0.1", status_provider=None):
    """Sobe o dashboard (bloqueante). Best-effort; localhost por padrão."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class _H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            code, ctype, body = route(self.path, status_provider=status_provider)
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))

        def log_message(self, *a):  # silencia o log padrão
            return

    httpd = HTTPServer((host, port), _H)
    httpd.serve_forever()


__all__ = ["render_status_html", "route", "serve_dashboard"]
