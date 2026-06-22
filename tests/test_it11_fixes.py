"""Caça it.11: REGRESSÃO crítica (o agente não rodava) — run_task SEMPRE passa chat_id no _hkw, mas
Harness.__init__ não aceitava → TypeError 'unexpected keyword argument chat_id' a CADA turno do gateway/
chat. Coberto agora. + gh sem auth não some calado (vai pro log)."""
from __future__ import annotations

from types import SimpleNamespace


# ---------------------------------------------------------------- REGRESSÃO: Harness aceita chat_id
def test_harness_accepts_chat_id_and_threads_to_ctx(tmp_path):
    from okami.core import Harness, Task
    # antes do fix: Harness(chat_id=...) → TypeError e o agente NÃO rodava (gap de cobertura: os testes
    # do harness construíam Harness direto, nunca via run_task que injeta chat_id).
    h = Harness(lambda *a, **k: "ok", Task(goal="oi"), tmp_path, chat_id="telegram:123")
    assert h.ctx.chat_id == "telegram:123"               # chega no ToolContext → process_start notifica certo


def test_harness_chat_id_defaults_empty(tmp_path):
    from okami.core import Harness, Task
    h = Harness(lambda *a, **k: "ok", Task(goal="oi"), tmp_path)
    assert h.ctx.chat_id == ""                            # default não quebra quem não passa


# ---------------------------------------------------------------- #21 gh sem auth vai pro log
def test_gh_latest_run_logs_auth_failure(monkeypatch):
    import okami.core.readiness as rd
    logged: list = []
    monkeypatch.setattr("okami.log.dbg", lambda msg, **k: logged.append(msg))
    monkeypatch.setattr(rd.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="gh auth: token expired"))
    assert rd.gh_latest_run("ci.yml") is None             # degrada gracioso (None), não crasha
    assert any("token expired" in m for m in logged)      # MAS a falha de auth fica VISÍVEL no log
