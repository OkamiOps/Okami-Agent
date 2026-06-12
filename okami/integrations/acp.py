"""ACP — Agent Client Protocol (Zed/IDEs) §13. Servidor JSON-RPC sobre stdio com framing LSP
(Content-Length). Expõe o Okami como AGENTE que a IDE dirige: initialize → session/new →
session/prompt → session/update (STREAMING de progresso) + session/cancel.

Pesquisa #6 item 28: streaming dos tool-calls ao vivo (a IDE vê o agente trabalhando, não só o
resultado no fim) + cancel por sessão. O handler (`AcpServer.handle`) é PURO (req→result + sink de
notificações), testável sem stdio; `run_acp` é o loop fino por cima. `okami acp` é o entrypoint.
"""

from __future__ import annotations

import json
import sys


def _read_message(stream) -> dict | None:
    headers: dict[str, str] = {}
    while True:
        line = stream.readline()
        if not line:
            return None
        s = line.decode("ascii", "ignore").strip()
        if s == "":
            break
        if ":" in s:
            k, v = s.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    n = int(headers.get("content-length", 0) or 0)
    if n <= 0:
        return None
    body = stream.read(n)
    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        return None


def _write_message(stream, msg: dict) -> None:
    data = json.dumps(msg).encode("utf-8")
    stream.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii"))
    stream.write(data)
    stream.flush()


def _reply(out, rid, result) -> None:
    _write_message(out, {"jsonrpc": "2.0", "id": rid, "result": result})


def _notify(out, method, params) -> None:
    _write_message(out, {"jsonrpc": "2.0", "method": method, "params": params})


def _prompt_text(prompt) -> str:
    if isinstance(prompt, str):
        return prompt
    if isinstance(prompt, list):
        return " ".join(b.get("text", "") for b in prompt
                        if isinstance(b, dict) and b.get("type") == "text").strip()
    return str(prompt or "")


class AcpServer:
    """Handler ACP puro (testável). `run_task(cfg, ws, goal, *, on_event, cancel) -> Task`."""

    def __init__(self, cfg, ws, run_task):
        self.cfg, self.ws, self.run_task = cfg, ws, run_task
        self.sessions: dict[str, dict] = {}

    def _session(self, sid: str) -> dict:
        return self.sessions.setdefault(sid, {"cancel": False})

    def handle(self, req: dict, emit) -> dict | None:
        """Processa UMA requisição; `emit(method, params)` é o sink de NOTIFICAÇÕES (session/update).
        Retorna {"id","result"} p/ o rid, ou None p/ notificação (sem id)."""
        method, rid, params = req.get("method"), req.get("id"), (req.get("params") or {})
        if rid is None:
            return None
        if method == "initialize":
            return self._ok(rid, {"protocolVersion": 1, "agentCapabilities": {
                "loadSession": False, "cancellable": True,
                "promptCapabilities": {"image": False}}})
        if method == "authenticate":
            return self._ok(rid, {})
        if method == "session/new":
            sid = f"sess-{len(self.sessions) + 1}"
            self._session(sid)
            return self._ok(rid, {"sessionId": sid})
        if method == "session/cancel":
            self._session(params.get("sessionId", "sess-1"))["cancel"] = True
            return self._ok(rid, {})
        if method == "session/prompt":
            return self._ok(rid, self._run_prompt(params, emit))
        return self._ok(rid, {})               # método desconhecido → ok vazio (tolerante)

    def _run_prompt(self, params: dict, emit) -> dict:
        sid = params.get("sessionId", "sess-1")
        sess = self._session(sid)

        def on_event(e: dict) -> None:         # STREAMING: tool-calls ao vivo p/ a IDE (item 28)
            if e.get("kind") == "step":
                emit("session/update", {"sessionId": sid, "update": {
                    "sessionUpdate": "tool_call", "title": e.get("tool", ""),
                    "status": "completed" if e.get("ok", True) else "failed"}})

        task = self.run_task(self.cfg, self.ws, _prompt_text(params.get("prompt")),
                             on_event=on_event, cancel=lambda: sess["cancel"])
        cancelled = bool(sess["cancel"])       # flag pode ter sido setado por session/cancel durante o run
        sess["cancel"] = False                 # CONSOME ao fim do turno → o próximo começa fresco
        result = (getattr(task, "result", None) or getattr(task, "reason", None)
                  or getattr(getattr(task, "state", None), "value", "ok"))
        emit("session/update", {"sessionId": sid, "update": {
            "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": result}}})
        return {"stopReason": "cancelled" if cancelled else "end_turn"}

    @staticmethod
    def _ok(rid, result) -> dict:
        return {"jsonrpc": "2.0", "id": rid, "result": result}


def run_acp(cfg, ws, run_task, *, stdin=None, stdout=None) -> None:  # pragma: no cover — loop de I/O
    """Loop do servidor ACP sobre stdio (framing LSP). `run_task(cfg, ws, goal, *, on_event, cancel)`."""
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout.buffer
    srv = AcpServer(cfg, ws, run_task)

    def emit(method, params):
        _notify(stdout, method, params)

    while True:
        req = _read_message(stdin)
        if req is None:
            break
        resp = srv.handle(req, emit)
        if resp is not None:
            _reply(stdout, resp["id"], resp["result"])
