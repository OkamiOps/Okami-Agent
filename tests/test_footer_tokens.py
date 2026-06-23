"""Rodapé de custo SEMPRE mostra tokens (queixa do dono) + tempo legível. Modelo local não reporta usage
→ runner estima por chars (~) → o rodapé imprime '~Nk tok … est.' em vez de só os segundos."""
from __future__ import annotations

import json
import tempfile

import pytest

from okami.gateway.endpoint import AgentEndpoint, _fmt_elapsed


def test_fmt_elapsed_short_and_long():
    assert _fmt_elapsed(12.3) == "12.3s"
    assert _fmt_elapsed(628.3) == "10m28s"          # o caso do dono: 628s vira '10m28s', não '628.3s'
    assert _fmt_elapsed(60.0) == "60.0s"


def _ep():
    return AgentEndpoint.__new__(AgentEndpoint)     # só p/ chamar _turn_footer (método puro)


def _footer(usage_dict, elapsed):
    ep = _ep()
    ep.cfg = None
    s = type("S", (), {})()
    return ep._turn_footer(s, {"usage": usage_dict}, elapsed)


def test_footer_shows_estimated_tokens():
    from okami.llm.usage import estimate_usage
    u = estimate_usage("x" * 4000, "y" * 800)        # ~1000↑ ~200↓, estimated
    out = _footer(u.to_dict(), 628.3)
    assert "tok" in out and "~" in out and "est." in out and "10m28s" in out


def test_footer_real_tokens_no_estimate_marker():
    from okami.llm.usage import CanonicalUsage
    u = CanonicalUsage(input_tokens=1200, output_tokens=300)   # provider reportou de verdade
    out = _footer(u.to_dict(), 5.0)
    assert "tok" in out and "~" not in out and "est." not in out


def test_runner_estimates_when_provider_reports_zero(monkeypatch):
    """Ponta a ponta: provider local devolve usage zerado → t.stats['usage'] sai ESTIMADO e não-zero."""
    import okami.llm.providers as prov
    from okami.llm.usage import Completion
    from okami.config import build_config
    from okami.runner import run_task
    cfg = build_config({"default_provider": "p", "providers": {"p": {"model": "m"}}})

    def gen(c, m, **k):
        return Completion(text="```json\n" + json.dumps({"tool": "respond", "args": {"message": "oi"}}) + "\n```",
                          provider="p", model="m")   # SEM usage (default CanonicalUsage zerado)
    monkeypatch.setattr(prov, "complete_messages_ex", gen)        # monkeypatch → auto-restaura (sem poluir)
    monkeypatch.setattr(prov, "complete_messages", lambda *a, **k: gen(*a, **k).text)
    from pathlib import Path
    t = run_task(cfg, Path(tempfile.mkdtemp()), "oi", surface="cli", chat_id="c")
    u = t.stats.get("usage") or {}
    assert u.get("estimated") is True and (int(u.get("input", 0)) + int(u.get("output", 0))) > 0


@pytest.fixture(autouse=True)
def _pt():
    import okami.i18n as _i18n
    _i18n.set_lang("pt")
    yield
    _i18n.set_lang(None)
