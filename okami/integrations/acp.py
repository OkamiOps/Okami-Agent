"""ACP — Agent Client Protocol (Zed/IDEs) §13. Servidor JSON-RPC sobre stdio com framing LSP
(Content-Length). Expõe o Okami como AGENTE que a IDE dirige: initialize → session/new →
session/prompt → session/update (STREAMING de progresso) + session/cancel.

Pesquisa #6 item 28: streaming dos tool-calls ao vivo (a IDE vê o agente trabalhando, não só o
resultado no fim) + cancel por sessão. O handler (`AcpServer.handle`) é PURO (req→result + sink de
notificações), testável sem stdio; `run_acp` é o loop fino por cima. `okami acp` é o entrypoint.
"""

from __future__ import annotations

import json
import queue
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


def _available_commands() -> list[dict]:
    """agentCapabilities.availableCommands a partir do COMMAND_REGISTRY (item 13): a IDE mostra os
    slash-commands do Okami no autocomplete. {name, description, input} por comando — `input` carrega
    o hint de args (ex.: '<n>') quando o comando aceita argumento."""
    from okami.commands import COMMAND_REGISTRY, desc_of
    out: list[dict] = []
    for c in COMMAND_REGISTRY:
        if getattr(c, "scope", "both") == "chat":     # item 27: comando só-TUI (/exit, /copy, /mouse…)
            continue                                  # não faz sentido na IDE (ACP) → não anuncia
        entry = {"name": c.name, "description": desc_of(c)}
        # `input` = hint de args do ACP (None p/ comando sem argumento; senão o placeholder).
        entry["input"] = {"hint": c.args} if c.args else None
        out.append(entry)
    return out


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
        # round-trip de permissão (item 13): cada session/request_permission ganha um _rid; o callback
        # BLOQUEIA num queue.Queue por _rid até o loop run_acp rotear a resposta do cliente via
        # deliver_permission(). Sem cliente respondendo = fail-closed (nega) no timeout.
        self._perm_rid = 0
        import threading
        self._perm_lock = threading.Lock()            # item 26: rid++ atômico (2 permissões concorrentes
        self._perm_pending: dict[int, queue.Queue] = {}   # não podem colidir o mesmo rid e orfanar a queue)

    def _session(self, sid: str) -> dict:
        return self.sessions.setdefault(sid, {"cancel": False})

    def deliver_permission(self, rid, decision: str) -> None:
        """O loop run_acp chama isto ao ver a RESPOSTA do cliente a um session/request_permission:
        entrega a decisão na queue daquele _rid, desbloqueando o callback approve que espera."""
        try:
            rid = int(rid)
        except (TypeError, ValueError):
            return
        q = self._perm_pending.get(rid)
        if q is not None:
            q.put(decision)

    def handle(self, req: dict, emit) -> dict | None:
        """Processa UMA requisição; `emit(method, params)` é o sink de NOTIFICAÇÕES (session/update).
        Retorna {"id","result"} p/ o rid, ou None p/ notificação (sem id)."""
        method, rid, params = req.get("method"), req.get("id"), (req.get("params") or {})
        if rid is None:
            return None
        if method == "initialize":
            return self._ok(rid, {"protocolVersion": 1, "agentCapabilities": {
                "loadSession": True, "cancellable": True,            # item 13: loadSession ON (rehidrata)
                "availableCommands": _available_commands(),          # item 13: anuncia os slash-commands
                "promptCapabilities": {"image": False}}})
        if method == "authenticate":
            return self._ok(rid, {})
        if method == "session/new":
            sid = f"sess-{len(self.sessions) + 1}"
            self._session(sid)
            return self._ok(rid, {"sessionId": sid})
        if method == "session/load":                                 # item 13: rehidrata uma sessão salva
            sid = params.get("sessionId") or f"sess-{len(self.sessions) + 1}"
            self._session(sid)                                       # cria/recupera o estado da sessão
            return self._ok(rid, {"sessionId": sid})
        if method in ("session/list", "session/fork"):               # tolerante: ainda não persistimos
            return self._ok(rid, {})                                 # histórico → resposta graciosa vazia
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

        def approve(req: dict) -> bool:        # go/no-go via session/request_permission (item 13):
            return self._request_permission(sid, req, emit)   # manda o request e BLOQUEIA na resposta

        task = self.run_task(self.cfg, self.ws, _prompt_text(params.get("prompt")),
                             on_event=on_event, cancel=lambda: sess["cancel"], approve=approve)
        cancelled = bool(sess["cancel"])       # flag pode ter sido setado por session/cancel durante o run
        sess["cancel"] = False                 # CONSOME ao fim do turno → o próximo começa fresco
        result = (getattr(task, "result", None) or getattr(task, "reason", None)
                  or getattr(getattr(task, "state", None), "value", "ok"))
        emit("session/update", {"sessionId": sid, "update": {
            "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": result}}})
        return {"stopReason": "cancelled" if cancelled else "end_turn"}

    def _request_permission(self, sid: str, req: dict, emit, *, timeout: float = 600.0) -> bool:
        """Manda um session/request_permission ao cliente (com diff p/ edit, riscos p/ shell) e BLOQUEIA
        até a resposta chegar via deliver_permission(). FAIL-CLOSED: timeout/erro → nega (igual ao
        go/no-go do gateway via Telegram). O round-trip vira uma queue.Queue por _rid: o callback espera
        no get(), o loop run_acp roteia a resposta do cliente p/ a mesma queue."""
        from okami.integrations.acp_permissions import decision_to_bool, permission_request
        with self._perm_lock:                          # rid++ e registro da queue sob lock (atômico)
            self._perm_rid += 1
            rid = self._perm_rid
            q: queue.Queue = queue.Queue(maxsize=1)
            self._perm_pending[rid] = q
        try:
            envelope = permission_request({**req, "_workspace": str(self.ws)})
            params = dict(envelope["params"])
            params["sessionId"] = sid
            params["_rid"] = rid               # o cliente devolve este _rid → deliver_permission o roteia
            emit("session/request_permission", params)
            try:
                decision = q.get(timeout=timeout)
            except queue.Empty:                # cliente não respondeu no prazo → nega (fail-closed)
                return False
            return decision_to_bool(decision)
        finally:
            self._perm_pending.pop(rid, None)

    @staticmethod
    def _ok(rid, result) -> dict:
        return {"jsonrpc": "2.0", "id": rid, "result": result}


def run_acp(cfg, ws, run_task, *, stdin=None, stdout=None) -> None:  # pragma: no cover — loop de I/O
    """Loop do servidor ACP sobre stdio (framing LSP). `run_task(cfg, ws, goal, *, on_event, cancel)`.

    O round-trip de PERMISSÃO (item 13) é bloqueante DENTRO do run_task → roda o session/prompt num
    thread worker p/ o loop continuar LENDO stdin e rotear a resposta do cliente
    (session/request_permission é um REQUEST com id; o cliente devolve {id, result}) p/ deliver_permission."""
    import threading

    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout.buffer
    srv = AcpServer(cfg, ws, run_task)
    write_lock = threading.Lock()

    def emit(method, params):
        # session/request_permission é um REQUEST (precisa de resposta do cliente): manda com id=_rid.
        if method == "session/request_permission":
            rid = params.get("_rid")
            with write_lock:
                _write_message(stdout, {"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        else:                                  # demais updates são NOTIFICAÇÕES (sem resposta)
            with write_lock:
                _notify(stdout, method, params)

    while True:
        msg = _read_message(stdin)
        if msg is None:
            break
        # RESPOSTA do cliente a um session/request_permission (tem id + result/outcome, sem method) →
        # roteia a decisão p/ a queue que o callback approve espera. Não é uma requisição a processar.
        if msg.get("method") is None and ("result" in msg or "error" in msg):
            srv.deliver_permission(msg.get("id"), _permission_outcome(msg.get("result")))
            continue
        if msg.get("method") == "session/prompt":   # bloqueia (round-trip de permissão) → thread worker
            threading.Thread(target=_serve_prompt, args=(srv, msg, emit, stdout, write_lock),
                             daemon=True).start()
            continue
        resp = srv.handle(msg, emit)
        if resp is not None:
            with write_lock:
                _reply(stdout, resp["id"], resp["result"])


def _serve_prompt(srv, msg, emit, stdout, write_lock) -> None:  # pragma: no cover — thread de I/O
    resp = srv.handle(msg, emit)
    if resp is not None:
        with write_lock:
            _reply(stdout, resp["id"], resp["result"])


def _permission_outcome(result) -> str:
    """Extrai a decisão da resposta do cliente ao session/request_permission. O ACP devolve
    {outcome:{outcome:'selected', optionId:'once'}} OU {outcome:'cancelled'}; toleramos formas planas."""
    if not isinstance(result, dict):
        return "deny"
    outcome = result.get("outcome", result)
    if isinstance(outcome, dict):
        return str(outcome.get("optionId") or outcome.get("outcome") or "deny")
    return str(outcome or "deny")
