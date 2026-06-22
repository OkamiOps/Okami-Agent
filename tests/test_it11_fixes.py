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


# ---------------------------------------------------------------- SMOKE: run_task ponta-a-ponta
def test_run_task_end_to_end_smoke(tmp_path, monkeypatch):
    """O teste que FALTAVA: exercita run_task → Harness → ToolContext como o gateway faz (com provider
    falso, sem rede). Teria pego o bug do chat_id — a suíte só construía Harness DIRETO."""
    import okami.llm.providers as prov
    from okami.config import build_config
    from okami.core import TaskState
    from okami.llm.usage import Completion
    from okami.runner import run_task

    def _fake(cfg, messages, **kw):
        return Completion(text='```json\n{"tool": "respond", "args": {"message": "oi!"}}\n```',
                          provider="p", model="m")
    monkeypatch.setattr(prov, "complete_messages_ex", _fake)
    monkeypatch.setattr(prov, "complete_messages", lambda *a, **k: _fake(*a, **k).text)

    cfg = build_config({"default_provider": "p", "providers": {"p": {"model": "m"}}})
    t = run_task(cfg, tmp_path, "oi tudo bem?", surface="telegram", chat_id="telegram:99999")
    assert t.state == TaskState.COMPLETE and "oi!" in (t.result or "")   # caminho REAL do gateway roda


# ---------------------------------------------------------------- E2E: fallback de stream sem traceback
def test_stream_fallback_warning_has_no_traceback():
    """Achado RODANDO o app: provider fora → o aviso 'stream instável; caindo no robusto' (fallback
    TRATADO) despejava o traceback inteiro (log.warn default exc_info=True) e o usuário achava que
    crashou. Garante exc_info=False nas 2 chamadas de fallback."""
    import inspect
    import okami.llm.providers as prov
    import okami.llm.streaming as st
    for mod in (prov, st):
        src = inspect.getsource(mod)
        idx = src.index("stream instável")
        call = src[idx - 40:idx + 200]                    # a chamada log.warn(...) em volta do texto
        assert "exc_info=False" in call, f"warn de 'stream instável' em {mod.__name__} sem exc_info=False"


# ---------------------------------------------------------------- #21 gh sem auth vai pro log
def test_gh_latest_run_logs_auth_failure(monkeypatch):
    import okami.core.readiness as rd
    logged: list = []
    monkeypatch.setattr("okami.log.dbg", lambda msg, **k: logged.append(msg))
    monkeypatch.setattr(rd.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="gh auth: token expired"))
    assert rd.gh_latest_run("ci.yml") is None             # degrada gracioso (None), não crasha
    assert any("token expired" in m for m in logged)      # MAS a falha de auth fica VISÍVEL no log
