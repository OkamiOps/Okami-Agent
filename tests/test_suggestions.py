"""Item 2 (#8): suggestions proativas CONSENT-FIRST — automação proposta, aceita com 1 toque.

Nada roda sem o dono aceitar; dispensar LATCHA (a mesma dedup_key nunca é re-oferecida); cap de 5
pendentes p/ não virar parede de nag; aceitar cria um cron job de verdade (reusa o Scheduler)."""
from __future__ import annotations


def test_add_and_list_pending(tmp_path):
    from okami.automation.suggestions import SuggestionStore
    s = SuggestionStore(tmp_path)
    sid = s.add(text="resumo diário às 8h?", schedule="0 8 * * *",
                prompt="faça o resumo do dia", dedup_key="daily-brief")
    assert sid
    p = s.pending()
    assert len(p) == 1 and p[0]["text"] == "resumo diário às 8h?"


def test_dismiss_latches_dedup(tmp_path):
    from okami.automation.suggestions import SuggestionStore
    s = SuggestionStore(tmp_path)
    sid = s.add(text="x", schedule="0 8 * * *", prompt="p", dedup_key="k")
    s.dismiss(sid)
    assert s.pending() == []
    assert s.add(text="x de novo", schedule="0 8 * * *", prompt="p", dedup_key="k") is None  # latched
    assert s.pending() == []


def test_cap_five_pending(tmp_path):
    from okami.automation.suggestions import SuggestionStore
    s = SuggestionStore(tmp_path)
    for i in range(7):
        s.add(text=f"t{i}", schedule="0 8 * * *", prompt="p", dedup_key=f"k{i}")
    assert len(s.pending()) == 5            # cap 5 — não vira parede de nag


def test_accept_creates_cron_job(tmp_path):
    from okami.automation.scheduler import Scheduler
    from okami.automation.suggestions import SuggestionStore
    s = SuggestionStore(tmp_path)
    sid = s.add(text="resumo", schedule="0 8 * * *", prompt="faça o resumo", dedup_key="daily")
    sched = Scheduler(str(tmp_path))
    job = s.accept(sid, sched)
    assert job and job["schedule"] == "0 8 * * *" and "resumo" in job["prompt"]
    assert s.pending() == []                                        # saiu da fila
    assert any("resumo" in j["prompt"] for j in sched.load())       # virou job de verdade


def test_accept_unknown_returns_none(tmp_path):
    from okami.automation.scheduler import Scheduler
    from okami.automation.suggestions import SuggestionStore
    s = SuggestionStore(tmp_path)
    assert s.accept("nope", Scheduler(str(tmp_path))) is None


def test_catalog_starters_seed_idempotent(tmp_path):
    from okami.automation.suggestions import STARTERS, SuggestionStore, seed_starters
    s = SuggestionStore(tmp_path)
    n = seed_starters(s)
    assert n == len(STARTERS) and len(s.pending()) == len(STARTERS)
    assert seed_starters(s) == 0            # dedup: re-seed não duplica


def test_suggest_automation_tool_adds_pending(tmp_path):
    from okami.automation.suggestions import SuggestionStore
    from okami.core.tools import ToolContext
    from okami.core.tools.suggest import SuggestAutomation
    ctx = ToolContext(workspace=tmp_path)
    r = SuggestAutomation().run({"text": "resumo diário?", "schedule": "0 8 * * *",
                                 "prompt": "faça o resumo do dia", "dedup_key": "daily"}, ctx)
    assert r.ok and SuggestionStore(tmp_path).pending()


def test_suggest_automation_in_registry():
    from okami.core.tools import default_registry
    assert "suggest_automation" in default_registry()
