"""API HTTP mínima do Okami (stdlib http.server, sem dependência extra) — expõe o agente por HTTP.

  POST /chat   {"message": "...", "agent": "okami"}  →  {"reply", "state", "usage"}
  GET  /health                                       →  {"ok": true}

FAIL-CLOSED: exige `Authorization: Bearer <OKAMI_API_TOKEN>`; sem token configurado a API NÃO sobe.
Bind em 127.0.0.1 por padrão (não exposto à rede sem querer).
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable


def handle_chat(body: dict, run: Callable[[str, str], object]) -> dict:
    """Lógica PURA (testável): valida, roda a tarefa e monta o payload de resposta."""
    msg = str((body or {}).get("message", "")).strip()
    if not msg:
        return {"error": "campo 'message' vazio"}
    task = run(str(body.get("agent") or "okami"), msg)
    state = getattr(task, "state", None)
    return {
        "reply": getattr(task, "result", None) or getattr(task, "reason", "") or "",
        "state": getattr(state, "value", str(state) if state else "unknown"),
        "usage": (getattr(task, "stats", {}) or {}).get("usage", {}),
    }


def make_handler(token: str, run: Callable[[str, str], object]):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, obj: dict) -> None:
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):  # silencia o log default do http.server
            pass

        def do_GET(self):
            self._send(200, {"ok": True}) if self.path == "/health" else self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.headers.get("Authorization", "") != f"Bearer {token}":
                self._send(401, {"error": "não autorizado (Authorization: Bearer <token>)"})
                return
            if self.path != "/chat":
                self._send(404, {"error": "not found"})
                return
            try:
                n = int(self.headers.get("Content-Length", 0) or 0)
                if n > 1_048_576:                       # teto de 1 MB: Content-Length gigante não estoura a RAM (DoS)
                    self._send(413, {"error": "corpo grande demais (máx 1MB)"})
                    return
                body = json.loads(self.rfile.read(n) or b"{}")
            except Exception:  # noqa: BLE001
                self._send(400, {"error": "json inválido"})
                return
            self._send(200, handle_chat(body, run))

    return Handler


def serve(port: int, token: str, run: Callable[[str, str], object], *, host: str = "127.0.0.1"):
    """Cria o servidor (fail-closed sem token). O chamador roda `serve_forever()`."""
    if not token:
        raise RuntimeError("OKAMI_API_TOKEN não configurado — a API não sobe sem token (fail-closed).")
    return ThreadingHTTPServer((host, port), make_handler(token, run))
