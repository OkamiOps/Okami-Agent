"""Modo silencioso de cron (paridade Hermes): job cujo resultado começa com [SILENT] é SALVO/registrado
mas NÃO entregue no chat — fim do spam de cron que 'não tinha nada novo', mantendo a trilha."""

from __future__ import annotations

from okami.automation.scheduler import delivery_decision


def test_normal_result_is_delivered():
    assert delivery_decision("resumo do dia: 3 PRs abertos") == (True, "resumo do dia: 3 PRs abertos")


def test_silent_prefix_suppresses_delivery():
    deliver, text = delivery_decision("[SILENT] nada mudou desde ontem")
    assert deliver is False and text == "nada mudou desde ontem"


def test_silent_with_newline():
    deliver, text = delivery_decision("[SILENT]\nlog interno só")
    assert deliver is False and text == "log interno só"


def test_silent_is_trimmed_leading_space():
    deliver, _ = delivery_decision("   [SILENT] x")
    assert deliver is False


def test_silent_case_insensitive():
    deliver, _ = delivery_decision("[silent] x")
    assert deliver is False


def test_empty_result_delivers_nothing_special():
    assert delivery_decision("") == (True, "")


def test_builders_execute_honors_silent(monkeypatch, tmp_path):
    """O _start_scheduler do gateway usa delivery_decision: job [SILENT] não manda nada pro chat."""
    from okami.core import Task, TaskState
    from okami.gateway import AgentEndpoint, builders
    from okami.automation.scheduler import Scheduler

    sent: list = []

    class Ch:
        name = "telegram"
        def send(self, cid, text): sent.append((cid, text))
        def allowed(self, c): return True
        def poll(self): return []

    captured = {}
    monkeypatch.setattr(builders.threading, "Thread",
                        lambda target=None, **k: captured.setdefault("loop", target) or
                        type("T", (), {"start": lambda s: None, "daemon": True})())

    def runner(cfg, ws, goal, **kw):
        t = Task(goal=goal)
        t.state, t.result = TaskState.COMPLETE, "[SILENT] nada novo"
        return t

    ep = AgentEndpoint("dev", cfg=None, ws=str(tmp_path), channel=Ch(), run_task=runner,
                       spawn=lambda fn: fn())
    ep.set_home("777")
    Scheduler(str(tmp_path)).add("1h", "verifique novidades", agent="dev")
    # captura o execute via tick determinístico em vez do loop de thread
    monkeypatch.setattr(builders.time, "sleep", lambda s: (_ for _ in ()).throw(SystemExit))
    try:
        builders._start_scheduler([ep], emit=lambda m: None, interval=999)
        if captured.get("loop"):
            captured["loop"]()                              # roda 1 iteração do loop → tick → execute
    except SystemExit:
        pass
    assert sent == []                                       # [SILENT] → nada foi pro chat
