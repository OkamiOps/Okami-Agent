"""Regressão: `okami chat -p <provider>` tem que MUDAR quem roda o turno de verdade, não só o
banner. O bug original (fixed em a99985a) era: -p resolvia mas só a closure `run_task` recebia o
override — cfg.default_provider (banner, model_label, pc=cfg.provider(), sessões do endpoint)
continuava no default do yaml. O teste de subprocess (test_chat_boot_smoke.py) só olha o TEXTO do
banner; aqui a asserção é no que efetivamente CHEGA no turno: os kwargs passados pro run_task
(session/turn config) — sem precisar de rede/credenciais reais.
"""
from __future__ import annotations

import threading

import pytest


def _write_min_config(path, default_provider: str) -> None:
    path.write_text(
        f"""
default_provider: {default_provider}
providers:
  alpha:
    name: Alpha
    model: openai/alpha-model
    tier: local
    api_key: dummy
  minimax:
    name: MiniMax
    model: openai/MiniMax-M3
    tier: weak
    api_key: dummy
""".strip() + "\n",
        encoding="utf-8",
    )


@pytest.fixture
def chat_fn():
    from okami.cli.commands.chat import chat
    return chat


def test_chat_provider_flag_reaches_run_task_kwargs(tmp_path, monkeypatch, chat_fn):
    """`-p minimax` com default_provider=alpha no yaml: o kwarg `provider` que chega no run_task
    (a chamada que de fato dispara o turno/LLM) tem que ser 'minimax', não o default do arquivo."""
    _write_min_config(tmp_path / "okami.yaml", default_provider="alpha")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)

    captured: dict = {}
    done = threading.Event()

    def fake_run_task(cfg, ws, goal, **kw):
        captured["provider"] = kw.get("provider")
        captured["model"] = kw.get("model")
        captured["cfg_default_provider"] = cfg.default_provider  # session-level config na hora do turno
        from okami.core.harness.models import Task, TaskState
        t = Task(goal=goal, state=TaskState.COMPLETE, result="ok",
                 stats={"usage": {}, "served_by": f"{kw.get('provider')}/x"})
        done.set()
        return t

    import okami.runner
    monkeypatch.setattr(okami.runner, "run_task", fake_run_task)

    chat_fn(message="oi", agent=None, workspace="workspaces/default", provider="minimax", model=None,
            new=True, yolo=False, use_tui=False)

    assert done.wait(10), "run_task nunca foi chamado — a sessão nem tentou o turno."
    assert captured["provider"] == "minimax", (
        f"o -p NAO chegou no run_task (turno de verdade): kwargs={captured}")
    # regressão específica: banner/cfg.default_provider tambem tem que refletir o override (fonte única)
    assert captured["cfg_default_provider"] == "minimax", (
        f"cfg.default_provider ficou no valor do yaml em vez do -p: {captured}")


def test_chat_no_flag_keeps_yaml_default(tmp_path, monkeypatch, chat_fn):
    """Sem -p, o turno tem que usar o default_provider do yaml (sanity check do teste acima)."""
    _write_min_config(tmp_path / "okami.yaml", default_provider="alpha")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)

    captured: dict = {}
    done = threading.Event()

    def fake_run_task(cfg, ws, goal, **kw):
        captured["provider"] = kw.get("provider")
        captured["cfg_default_provider"] = cfg.default_provider
        from okami.core.harness.models import Task, TaskState
        t = Task(goal=goal, state=TaskState.COMPLETE, result="ok",
                 stats={"usage": {}, "served_by": "alpha/x"})
        done.set()
        return t

    import okami.runner
    monkeypatch.setattr(okami.runner, "run_task", fake_run_task)

    chat_fn(message="oi", agent=None, workspace="workspaces/default", provider=None, model=None,
            new=True, yolo=False, use_tui=False)

    assert done.wait(10)
    assert captured["provider"] in (None, "alpha")
    assert captured["cfg_default_provider"] == "alpha"
