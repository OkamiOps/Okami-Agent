"""Correções dos findings REAIS (triados por workflow adversarial): jitter de retry + falhas silenciosas."""
from __future__ import annotations

from pathlib import Path


# ── group.py: retry backoff com jitter + crescimento (anti thundering-herd) ──
def test_group_retry_backoff_jitter_growth_and_cap():
    from okami.gateway.group import _retry_backoff
    assert _retry_backoff(1, _rand=lambda: 0.0) == 3.0           # base na 1ª falha
    assert _retry_backoff(1, _rand=lambda: 1.0) > 3.0            # jitter empurra pra cima
    assert _retry_backoff(3, _rand=lambda: 0.0) > _retry_backoff(1, _rand=lambda: 0.0)  # cresce
    assert _retry_backoff(99, _rand=lambda: 0.0) == 30.0         # capado em 30s
    # jitter fica dentro de 30% do base
    b = _retry_backoff(2, _rand=lambda: 1.0)
    assert 6.0 <= b <= 6.0 * 1.3


# ── plugins.py: falha de import/entry-point AVISA (não engole em silêncio) ──
def test_plugin_roots_warns_on_home_failure(monkeypatch):
    from okami import plugins
    warned = []
    monkeypatch.setattr(plugins, "warn", lambda msg, **k: warned.append(msg))
    monkeypatch.setattr("okami.home.okami_home",
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    roots = plugins.plugin_roots()
    assert roots[0] == Path(".")                                # projeto ainda presente (fail-open no home)
    assert warned                                               # mas AVISOU (não silencioso)
    from okami.builtin import builtin_root
    assert builtin_root() in roots                              # nativos seguem (independem do home)


def test_discover_plugins_warns_on_entrypoint_failure(monkeypatch):
    from okami import plugins
    warned = []
    monkeypatch.setattr(plugins, "warn", lambda msg, **k: warned.append(msg))
    monkeypatch.setattr("importlib.metadata.entry_points",
                        lambda **k: (_ for _ in ()).throw(RuntimeError("boom")))
    out = plugins.discover_plugins([], entry_points=None)       # entry_points=None → lê do ambiente
    assert out == [] and warned                                 # degrada mas avisa


# ── plugins NATIVOS empacotados (viajam no pacote; demonstram o discovery) ──
def test_example_plugins_discoverable():
    from okami.builtin import builtin_root
    from okami.plugins import discover_plugins
    found = discover_plugins([builtin_root()], entry_points=())
    names = {p.name for p in found}
    assert names, "nenhum plugin nativo descoberto no pacote"
