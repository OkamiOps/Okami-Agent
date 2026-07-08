"""/steer + injeção mid-turn (paridade Hermes): (a) /busy interrupt CANCELA e reinicia (já existia); (b)
/steer INJETA no turno EM CURSO sem cortar. Cobre harness (drena + anexa o marcador na observação certa,
defere quando não há mensagem pra anexar, cancel limpa o pendente) e gateway (/steer explícito, /busy
steer, fallbacks)."""
from __future__ import annotations

from okami.core import Harness, Task, TaskState
from okami.core.harness.loop import STEER_MARKER_CLOSE, STEER_MARKER_OPEN
from okami.llm.usage import Completion


def _gen_factory(calls, n_reads=2):
    def gen(messages, schema=None):
        calls["n"] += 1
        if calls["n"] <= n_reads:
            return Completion(text="", tool_calls=[
                {"id": f"r{calls['n']}", "name": "read_file", "arguments": f'{{"path":"f{calls["n"]}.txt"}}'}])
        return Completion(text="", tool_calls=[
            {"id": "d", "name": "task_complete", "arguments": '{"summary":"feito"}'}])
    return gen


# --------------------------------------------------------------------- harness: drena + anexa o marcador
def test_steer_source_drains_and_wraps_marker_on_tool_result(tmp_path):
    (tmp_path / "f1.txt").write_text("a", encoding="utf-8")
    (tmp_path / "f2.txt").write_text("b", encoding="utf-8")
    calls = {"n": 0}
    steer_calls = {"n": 0}

    def steer_source():
        steer_calls["n"] += 1
        if steer_calls["n"] == 1:                       # só injeta UMA vez (2ª chamada = drenado, None)
            return "muda de abordagem, foca no arquivo 2"
        return None

    h = Harness(_gen_factory(calls), Task(goal="leia f1 e f2"), tmp_path, steer_source=steer_source)
    t = h.run()
    assert t.state == TaskState.COMPLETE
    # a observação do PRIMEIRO passo (role user/tool, o que vier logo após a assistant) carrega o marcador
    # (pula o system prompt: ele CITA o marcador como instrução, não conta como injeção real)
    joined = "\n".join(str(m.get("content")) for m in h.messages[1:] if isinstance(m.get("content"), str))
    assert STEER_MARKER_OPEN in joined and STEER_MARKER_CLOSE in joined
    assert "muda de abordagem, foca no arquivo 2" in joined
    # só injetou 1x (2ª leitura de steer_source devolveu None) — o marcador aparece 1 única vez
    assert joined.count(STEER_MARKER_OPEN) == 1


def test_no_steer_source_is_noop(tmp_path):
    (tmp_path / "f1.txt").write_text("a", encoding="utf-8")
    (tmp_path / "f2.txt").write_text("b", encoding="utf-8")
    calls = {"n": 0}
    h = Harness(_gen_factory(calls), Task(goal="leia f1 e f2"), tmp_path)   # sem steer_source (CLI puro)
    t = h.run()
    assert t.state == TaskState.COMPLETE
    joined = "\n".join(str(m.get("content")) for m in h.messages[1:] if isinstance(m.get("content"), str))
    assert STEER_MARKER_OPEN not in joined


def test_steer_deferred_when_no_message_to_attach(tmp_path):
    """Sem mensagem tool/user string pra anexar (ex.: conteúdo multimodal, não é o caso comum de texto) —
    o texto do steer NÃO se perde: fica em _deferred_steer pro passo seguinte tentar de novo."""
    h = Harness(lambda *a, **k: Completion(text="oi"), Task(goal="oi"), tmp_path,
                steer_source=lambda: "texto pendente")
    h.messages = [{"role": "assistant", "content": None}]   # última msg NÃO é user/tool com content str
    h._inject_steer()
    assert h._deferred_steer == "texto pendente"             # empurrado de volta, não perdido
    assert not any(STEER_MARKER_OPEN in str(m.get("content")) for m in h.messages)


def test_steer_deferred_delivered_on_next_attachable_message(tmp_path):
    h = Harness(lambda *a, **k: Completion(text="oi"), Task(goal="oi"), tmp_path, steer_source=lambda: None)
    h._deferred_steer = "chegou depois"
    h.messages = [{"role": "user", "content": "observação do passo"}]
    h._inject_steer()
    assert h._deferred_steer is None
    assert STEER_MARKER_OPEN in h.messages[-1]["content"]
    assert "chegou depois" in h.messages[-1]["content"]


def test_steer_source_kwarg_exists_in_run_task():
    import inspect
    from okami.runner import run_task
    assert "steer_source" in inspect.signature(run_task).parameters
    assert "steer_source" in inspect.signature(Harness.__init__).parameters


# --------------------------------------------------------------------- endpoint: /steer + /busy steer
class _Ch:
    def __init__(self):
        self.sent = []

    def poll(self):
        return []

    def send(self, cid, text):
        self.sent.append((str(cid), text))

    def allowed(self, cid):
        return True


def _busy_ep():
    from okami.gateway import AgentEndpoint
    import tempfile
    # spawn no-op → o _run nunca executa → s.busy fica True após o 1º envio (simula agente ocupado)
    return AgentEndpoint("dev", cfg=None, ws=tempfile.mkdtemp(), channel=_Ch(),
                         run_task=lambda *a, **k: None, spawn=lambda fn: None)


def test_steer_command_while_busy_sets_pending_without_cancel_or_queue():
    ep = _busy_ep()
    s = ep.session("7")
    ep.handle("7", "start")                              # busy=True (spawn no-op)
    ep.handle("7", "/steer muda a abordagem")
    assert s.pending_steer == "muda a abordagem"
    assert s.cancel is False                              # NÃO cancela — /steer nunca corta o turno
    assert s.queued == []                                 # NÃO vai pra fila — é injeção mid-turn


def test_steer_command_concats_multiple_calls():
    ep = _busy_ep()
    s = ep.session("7")
    ep.handle("7", "start")
    ep.handle("7", "/steer primeiro")
    ep.handle("7", "/steer segundo")
    assert s.pending_steer == "primeiro\nsegundo"


def test_steer_command_empty_arg_shows_usage():
    ep = _busy_ep()
    ep.handle("7", "start")
    ep.handle("7", "/steer")
    assert any("usage" in t.lower() or "uso" in t.lower() for _, t in ep.channel.sent)


def test_steer_command_without_busy_falls_back_to_normal_message():
    """Sem turno rodando, /steer <texto> vira mensagem normal (dispara o dispatch de sempre)."""
    seen = []

    def _spawn(fn):
        seen.append(fn)

    from okami.gateway import AgentEndpoint
    import tempfile
    ep = AgentEndpoint("dev", cfg=None, ws=tempfile.mkdtemp(), channel=_Ch(),
                       run_task=lambda *a, **k: None, spawn=_spawn)
    ep.handle("7", "/steer oi tudo bem?")
    s = ep.session("7")
    assert s.busy is True                                  # tratado como mensagem normal → iniciou o turno
    assert len(seen) == 1


def test_busy_mode_steer_routes_new_messages_to_pending_steer():
    ep = _busy_ep()
    s = ep.session("7")
    s.busy_mode = "steer"
    ep.handle("7", "start")                                # busy=True
    ep.handle("7", "mais um detalhe importante")            # msg comum enquanto busy_mode=steer
    assert s.pending_steer == "mais um detalhe importante"
    assert s.cancel is False
    assert s.queued == []


def test_busy_command_sets_steer_mode():
    ep = _busy_ep()
    s = ep.session("7")
    ep.handle("7", "/busy steer")
    assert s.busy_mode == "steer"


# --------------------------------------------------------------------- cancel supersedes steer
def test_stop_clears_pending_steer():
    ep = _busy_ep()
    s = ep.session("7")
    s.busy_mode = "steer"
    ep.handle("7", "start")
    ep.handle("7", "algo pra injetar")
    assert s.pending_steer
    ep.handle("7", "/stop")
    assert s.pending_steer is None


def test_interrupt_clears_pending_steer():
    ep = _busy_ep()
    s = ep.session("7")
    ep.handle("7", "start")                                # busy=True
    s.busy_mode = "interrupt"
    s.pending_steer = "sobrou de antes"                    # simula um steer que ficou pendente (busy_mode mudou)
    ep.handle("7", "corta essa")
    assert s.cancel is True
    assert s.pending_steer is None                          # não pode vazar pra próxima iteração
