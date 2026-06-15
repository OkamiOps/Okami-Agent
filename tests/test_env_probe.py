"""#10: env_probe — UMA linha no system prompt SÓ quando o ambiente Python está torto (pip ausente,
PEP-668 externally-managed). Silencioso (zero tokens) quando saudável; cacheado por processo."""
from __future__ import annotations


def test_probe_empty_when_healthy():
    from okami.core.env_probe import probe_python_env
    line = probe_python_env(_run=lambda argv: (0, "pip 24.0"), _externally_managed=lambda: False, _cache={})
    assert line == ""


def test_probe_flags_missing_pip():
    from okami.core.env_probe import probe_python_env
    line = probe_python_env(_run=lambda argv: (1, "No module named pip"),
                            _externally_managed=lambda: False, _cache={})
    assert "pip" in line.lower() and line.startswith("⚠")


def test_probe_flags_externally_managed():
    from okami.core.env_probe import probe_python_env
    line = probe_python_env(_run=lambda argv: (0, "pip 24.0"), _externally_managed=lambda: True, _cache={})
    assert "pep" in line.lower() or "externally" in line.lower()


def test_probe_caches_per_process():
    from okami.core.env_probe import probe_python_env
    cache = {}
    calls = []

    def run(argv):
        calls.append(1)
        return (1, "No module named pip")
    probe_python_env(_run=run, _externally_managed=lambda: False, _cache=cache)
    probe_python_env(_run=run, _externally_managed=lambda: False, _cache=cache)
    assert len(calls) == 1                                # 2ª chamada usa o cache (não re-sonda)
