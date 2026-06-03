"""ACP — Agent Client Protocol (Zed/IDEs) §13. Servidor JSON-RPC sobre stdio com framing LSP
(Content-Length). Expõe o Okami como AGENTE que a IDE dirige: initialize → session/new →
session/prompt (roda o harness e devolve o resultado via session/update).

EXPERIMENTAL/mínimo: não streama token-a-token (devolve o resultado completo num chunk); cobre o
fluxo básico que um cliente ACP espera. `okami acp` é o entrypoint (a IDE o lança como subprocesso).
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


def run_acp(cfg, ws, run_task, *, stdin=None, stdout=None) -> None:
    """Loop do servidor ACP. `run_task(cfg, ws, goal) -> Task`."""
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout.buffer
    sessions: dict[str, bool] = {}
    while True:
        req = _read_message(stdin)
        if req is None:
            break
        method, rid, params = req.get("method"), req.get("id"), (req.get("params") or {})
        if method == "initialize":
            _reply(stdout, rid, {"protocolVersion": 1,
                                 "agentCapabilities": {"loadSession": False,
                                                       "promptCapabilities": {"image": False}}})
        elif method == "authenticate":
            _reply(stdout, rid, {})
        elif method == "session/new":
            sid = f"sess-{len(sessions) + 1}"
            sessions[sid] = True
            _reply(stdout, rid, {"sessionId": sid})
        elif method == "session/prompt":
            sid = params.get("sessionId", "sess-1")
            task = run_task(cfg, ws, _prompt_text(params.get("prompt")))
            result = (getattr(task, "result", None) or getattr(task, "reason", None)
                      or getattr(getattr(task, "state", None), "value", "ok"))
            _notify(stdout, "session/update", {"sessionId": sid, "update": {
                "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": result}}})
            _reply(stdout, rid, {"stopReason": "end_turn"})
        elif rid is not None:
            _reply(stdout, rid, {})            # método desconhecido → ok vazio (tolerante)
