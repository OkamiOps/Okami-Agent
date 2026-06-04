"""Testes de regressão do harness (Fase 1).

Provam, com um provider FALSO roteirizado (sem rede), que os modos de falha
clássicos são contidos por construção: trava-nunca, loop-nunca, conclusão falsa
barrada, e grounding anti-alucinação.
"""

from __future__ import annotations

import json

from okami.core import Budget, Harness, Task, TaskState, parse_action


def J(tool: str, **args) -> str:
    return "```json\n" + json.dumps({"tool": tool, "args": args}) + "\n```"


class Script:
    """Provider falso: devolve saídas na ordem; depois um default sem ação."""

    def __init__(self, outputs, default="Vou fazer isso já já."):
        self.outputs = list(outputs)
        self.default = default
        self.calls = 0

    def __call__(self, messages, schema=None):
        self.calls += 1
        return self.outputs.pop(0) if self.outputs else self.default


# ------------------------------------------------------------------ parse_action
def test_sanitized_env_strips_secrets(monkeypatch):
    from okami.core.tools import sanitized_env

    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    monkeypatch.setenv("MY_TOKEN", "t")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("PROJECT_DIR", "/ok")
    env = sanitized_env()
    assert "OPENAI_API_KEY" not in env
    assert "MY_TOKEN" not in env
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert env.get("PROJECT_DIR") == "/ok"  # não-sensível é mantido


def test_parse_action_json_block():
    a = parse_action('texto\n```json\n{"tool":"read_file","args":{"path":"x"}}\n```')
    assert a is not None and a.tool == "read_file" and a.args["path"] == "x"


def test_parse_action_none_on_prose():
    assert parse_action("só um plano: vou criar o arquivo depois") is None


# ------------------------------------------------------------------ loop ReAct (conversa vs ação)
def test_respond_is_conversational_terminal(tmp_path):
    """`respond` é o ramo 'fala' do ReAct: encerra COMPLETE com a mensagem, sem exigir tarefa."""
    r = Harness(Script([J("respond", message="Oi! Sou o Okami, tudo certo 👋")]),
                Task(goal="oi, tudo bem? quem é você?"), tmp_path).run()
    assert r.state == TaskState.COMPLETE
    assert "Okami" in r.result and "especifique" not in r.result.lower()   # conversa, não telemarketing


def test_conversation_prose_without_json_is_accepted_as_reply(tmp_path):
    """Em papo (sem ação pedida), prosa sem envelope JSON É a resposta — não vira 'violação' feia."""
    r = Harness(Script(["Tô de boa, e você? 🙂"]), Task(goal="e aí, tudo certo?"), tmp_path).run()
    assert r.state == TaskState.COMPLETE and "de boa" in r.result


def test_action_request_still_requires_action_not_loose_prose(tmp_path):
    """Mas se PEDIRAM ação, prosa solta NÃO basta — Action-or-Terminate mantém o piso (modo tarefa)."""
    r = Harness(Script(["já já eu crio", "deixa comigo", "tô fazendo"]),
                Task(goal="crie um arquivo x.txt"), tmp_path).run()
    assert r.state == TaskState.FAILED


def test_action_request_blocks_lazy_respond_then_executes(tmp_path):
    """Pedido com verbo de ação: se o modelo só fala (respond) sem executar, o backstop re-prompta
    e ele acaba usando a ferramenta de verdade (paridade com modelo fraco)."""
    outputs = [
        J("respond", message="pronto, criei!"),                 # preguiça: diz que fez sem fazer
        J("write_file", path="nota.txt", content="feito de verdade"),
        J("respond", message="Arquivo nota.txt criado."),       # agora sim, com efeito
    ]
    events = []
    r = Harness(Script(outputs), Task(goal="crie um arquivo nota.txt"), tmp_path,
                on_event=events.append).run()
    assert r.state == TaskState.COMPLETE
    assert (tmp_path / "nota.txt").read_text(encoding="utf-8") == "feito de verdade"  # executou
    assert any(e["kind"] == "violation" for e in events)         # o backstop disparou 1x


def test_pure_chat_is_not_nudged(tmp_path):
    """Sem verbo de ação ('oi'), respond passa direto — nada de backstop (não vira tarefa)."""
    s = Script([J("respond", message="oi!")])
    r = Harness(s, Task(goal="oi tudo bem?"), tmp_path).run()
    assert r.state == TaskState.COMPLETE and s.calls == 1          # 1 turno só, sem re-prompt


# ------------------------------------------------------------------ happy path
def test_happy_path_completes(tmp_path):
    outputs = [
        J("write_file", path="hello.txt", content="oi"),
        J("task_complete", summary="feito"),
    ]
    t = Task(goal="criar hello.txt", exit_criteria=[{"type": "file_exists", "path": "hello.txt"}])
    r = Harness(Script(outputs), t, tmp_path).run()
    assert r.state == TaskState.COMPLETE
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "oi"


# ------------------------------------------------------------------ Action-or-Terminate
def test_promises_without_action_never_hang(tmp_path):
    s = Script([], default="Pera aí, já já eu faço, vou começar agora.")
    t = Task(goal="x")
    h = Harness(s, t, tmp_path, budget=Budget(max_consecutive_violations=3))
    r = h.run()
    assert r.state == TaskState.FAILED
    assert any("REJEITADO" in m["content"] for m in h.messages if m["role"] == "user")


# ------------------------------------------------------------------ anti-loop
def test_repeated_tool_call_breaks_loop(tmp_path):
    s = Script([], default=J("read_file", path="naoexiste.txt"))
    events = []
    t = Task(goal="x")
    r = Harness(s, t, tmp_path, on_event=events.append).run()
    assert r.state == TaskState.FAILED
    assert any(e["kind"] == "loop" for e in events)


# ------------------------------------------------------------------ exitCriteria verificados
def test_false_complete_is_rejected_then_real_complete(tmp_path):
    outputs = [
        J("task_complete", summary="(mentira, não fiz nada)"),
        J("write_file", path="hello.txt", content="oi"),
        J("task_complete", summary="agora sim"),
    ]
    events = []
    t = Task(goal="criar hello.txt", exit_criteria=[{"type": "file_exists", "path": "hello.txt"}])
    r = Harness(Script(outputs), t, tmp_path, on_event=events.append).run()
    assert r.state == TaskState.COMPLETE
    assert any(e["kind"] == "complete_rejected" for e in events)


# ------------------------------------------------------------------ grounding anti-alucinação
def test_grounding_blocks_overwrite_of_unread_file(tmp_path):
    (tmp_path / "exists.txt").write_text("old", encoding="utf-8")
    outputs = [
        J("write_file", path="exists.txt", content="novo"),  # bloqueado por grounding
        J("task_blocked", reason="não consegui sobrescrever sem ler"),
    ]
    r = Harness(Script(outputs), Task(goal="x"), tmp_path).run()
    assert r.state == TaskState.BLOCKED
    assert (tmp_path / "exists.txt").read_text(encoding="utf-8") == "old"


def test_escalation_to_stronger_model_when_stuck(tmp_path):
    # modelo "fraco" nunca emite ação → escala para o "forte", que conclui.
    weak = Script([], default="Vou pensar a respeito e já te respondo.")

    def strong(messages, schema=None):
        return J("task_complete", summary="resolvido pelo modelo forte")

    events = []
    t = Task(goal="x")
    h = Harness(weak, t, tmp_path, on_event=events.append, escalate=strong)
    r = h.run()
    assert r.state == TaskState.COMPLETE
    assert any(e["kind"] == "escalate" for e in events)


def test_approval_blocks_sensitive_write_when_denied(tmp_path):
    outputs = [
        J("write_file", path="SOUL.md", content="identidade sequestrada"),  # sensível → go/no-go
        J("task_blocked", reason="usuário negou"),
    ]
    events = []
    r = Harness(Script(outputs), Task(goal="x"), tmp_path,
                approve=lambda req: False, on_event=events.append).run()
    assert r.state == TaskState.BLOCKED
    assert not (tmp_path / "SOUL.md").exists()                 # bloqueado: não escreveu
    assert any(e["kind"] == "approval_request" for e in events)


def test_approval_allows_sensitive_write_when_granted(tmp_path):
    outputs = [
        J("write_file", path="SOUL.md", content="novo soul aprovado"),
        J("task_complete", summary="ok"),
    ]
    r = Harness(Script(outputs), Task(goal="x"), tmp_path, approve=lambda req: True).run()
    assert r.state == TaskState.COMPLETE
    assert (tmp_path / "SOUL.md").read_text(encoding="utf-8") == "novo soul aprovado"


def test_requires_approval_policy():
    from okami.core import approval
    assert approval.requires_approval("write_file", {"path": ".env"}) is not None
    assert approval.requires_approval("write_file", {"path": "src/app.tsx"}) is None
    assert approval.requires_approval("run_shell", {"cmd": "rm -rf build"}) is not None
    assert approval.requires_approval("run_shell", {"cmd": "ls -la"}) is None


def test_classify_categories():
    from okami.core import approval
    assert approval.classify("write_file", {"path": "SOUL.md"}).category == "identity_file"
    assert approval.classify("run_shell", {"cmd": "rm -rf x"}).risk == "critical"
    assert approval.classify("run_shell", {"cmd": "git push origin main"}).category == "git_push"


def test_approver_yolo_and_off_allow_all():
    from okami.core.approval import Approver
    for m in ("yolo", "off"):
        assert Approver(mode=m)({"category": "identity_file", "risk": "high"}) is True


def test_approver_manual_session_memory():
    from okami.core.approval import Approver
    calls = []
    a = Approver(mode="manual", prompt=lambda r: (calls.append(r["category"]) or "session"))
    assert a({"category": "env_file", "risk": "high"}) is True
    assert a({"category": "env_file", "risk": "high"}) is True   # lembrado → sem novo prompt
    assert calls == ["env_file"]


def test_approver_always_persists_and_smart_low_autoallows():
    from okami.core.approval import Approver
    persisted = []
    a = Approver(mode="manual", prompt=lambda r: "always", on_persist=persisted.append)
    assert a({"category": "git_push", "risk": "medium"}) is True
    assert persisted == ["git_push"]
    smart = Approver(mode="smart", prompt=lambda r: "deny")
    assert smart({"category": "x", "risk": "low"}) is True       # baixo risco → auto
    assert smart({"category": "y", "risk": "high"}) is False     # resto → prompt (deny)


def test_approver_fail_closed_without_prompt():
    from okami.core.approval import Approver
    assert Approver(mode="manual", prompt=None)({"category": "env_file", "risk": "high"}) is False


def test_ui_gate_blocks_ugly_then_passes_with_shadcn(tmp_path):
    contract = {
        "component_source": "@/components/ui",
        "forbid_inline_hex": True, "forbid_raw_css": True, "require_component_source": True,
    }
    bad = 'export const C = () => <div style={{color: "#abc"}}>hi</div>'
    good = 'import { Button } from "@/components/ui/button"\nexport const C = () => <Button>hi</Button>'
    outputs = [
        J("write_file", path="C.tsx", content=bad),
        J("task_complete", summary="(feio)"),
        J("write_file", path="C.tsx", content=good),
        J("task_complete", summary="agora com shadcn"),
    ]
    events = []
    t = Task(goal="UI", exit_criteria=[{"type": "ui_gate", "contract": contract, "path": "."}])
    r = Harness(Script(outputs), t, tmp_path, on_event=events.append).run()
    assert r.state == TaskState.COMPLETE
    assert any(e["kind"] == "complete_rejected" for e in events)  # o frontend feio foi barrado


def test_grounding_allows_overwrite_after_read(tmp_path):
    (tmp_path / "exists.txt").write_text("old", encoding="utf-8")
    outputs = [
        J("read_file", path="exists.txt"),
        J("write_file", path="exists.txt", content="novo"),
        J("task_complete", summary="atualizado"),
    ]
    t = Task(goal="x", exit_criteria=[{"type": "file_contains", "path": "exists.txt", "text": "novo"}])
    r = Harness(Script(outputs), t, tmp_path).run()
    assert r.state == TaskState.COMPLETE
    assert (tmp_path / "exists.txt").read_text(encoding="utf-8") == "novo"
