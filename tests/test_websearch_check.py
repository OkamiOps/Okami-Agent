"""web_search HONESTO sobre disponibilidade (fix do bug ao vivo): sem o pacote `ddgs`, a tool é
PODADA pelo prune_unavailable (item 27) em vez de aparecer e quebrar na cara do modelo."""
from __future__ import annotations

import importlib.util

from okami.core.tools.websearch import WebSearch


def test_check_reports_missing_ddgs(monkeypatch):
    real = importlib.util.find_spec

    def fake(name, *a, **k):
        return None if name == "ddgs" else real(name, *a, **k)

    monkeypatch.setattr(importlib.util, "find_spec", fake)
    reason = WebSearch().check()
    assert reason is not None and "ddgs" in reason


def test_check_ok_when_present(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a, **k: object())
    assert WebSearch().check() is None


def test_prune_removes_websearch_without_ddgs(monkeypatch):
    from okami.core.tool_policy import prune_unavailable
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda name, *a, **k: None if name == "ddgs" else real(name, *a, **k))
    from okami.core.tools import default_registry
    pruned = prune_unavailable(default_registry(), emit=lambda m: None)
    assert "web_search" not in pruned                    # some limpa — não aparece quebrada
