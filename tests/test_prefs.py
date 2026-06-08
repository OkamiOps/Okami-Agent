"""Preferências de UI unificadas (prefs.json) — merge-safe, atômico, nunca levanta."""
from __future__ import annotations


def test_prefs_persist_and_merge(tmp_path, monkeypatch):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    from okami import prefs
    # /skin grava tema; /details grava verbosidade — um NÃO clobbera o outro
    assert prefs.set_pref("theme", "dracula") is True
    assert prefs.set_pref("repl_details", "expanded") is True
    assert prefs.get_pref("repl_details") == "expanded"
    assert prefs.get_pref("theme") == "dracula", "set_pref clobberou outra chave (não fez merge)"
    assert prefs.get_pref("ausente", "fallback") == "fallback"


def test_prefs_corrupt_file_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    (tmp_path).mkdir(parents=True, exist_ok=True)
    (tmp_path / "prefs.json").write_text("{lixo não-json", encoding="utf-8")
    from okami import prefs
    assert prefs.get_pref("repl_details", "collapsed") == "collapsed"   # corrompido → default, sem levantar
    assert prefs.set_pref("repl_details", "hidden") is True             # e consegue regravar por cima
    assert prefs.get_pref("repl_details") == "hidden"
