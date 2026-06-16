"""#12 Onda A: instalador de dependência opcional em runtime (port do Hermes tools/lazy_deps.py).

Backend opcional (TTS, search, provider) chama ensure('feature') no 1º import; se falta, instala no
venv (allowlist + spec seguro + venv-scoped + opt-out). Resolve a fragilidade do extra [all] e o bloat.
"""
from __future__ import annotations

from types import SimpleNamespace


def test_spec_safety_rejects_dangerous():
    from okami.core.lazy_deps import _spec_is_safe
    assert _spec_is_safe("edge-tts==7.0.0") is True
    assert _spec_is_safe("pkg[extra]>=1.0,<2") is True
    for bad in ("git+https://x/y", "../evil", "-rrequirements.txt", "pkg; rm -rf /",
                "pkg && curl x", "http://x", "pkg`whoami`", "/abs/path", "pkg@1.0"):
        assert _spec_is_safe(bad) is False, bad


def test_unknown_feature_raises():
    from okami.core.lazy_deps import FeatureUnavailable, ensure
    try:
        ensure("nao.existe", prompt=False)
        raise AssertionError("deveria ter levantado")
    except FeatureUnavailable as e:
        assert "allowlist" in str(e).lower() or "nao.existe" in str(e)


def test_ensure_noop_when_satisfied(monkeypatch):
    from okami.core import lazy_deps
    monkeypatch.setitem(lazy_deps.LAZY_DEPS, "test.feat", ("pytest>=1.0",))   # pytest já está instalado
    called = {"n": 0}
    monkeypatch.setattr(lazy_deps, "_venv_pip_install", lambda *a, **k: called.__setitem__("n", 1))
    lazy_deps.ensure("test.feat", prompt=False)
    assert called["n"] == 0                                    # já satisfeito → não instala


def test_ensure_blocked_when_disabled(monkeypatch):
    from okami.core import lazy_deps
    monkeypatch.setitem(lazy_deps.LAZY_DEPS, "test.x", ("pacote-inexistente-okami==9.9.9",))
    monkeypatch.setenv("OKAMI_DISABLE_LAZY_INSTALLS", "1")
    try:
        lazy_deps.ensure("test.x", prompt=False)
        raise AssertionError("deveria ter levantado")
    except lazy_deps.FeatureUnavailable as e:
        assert "disabled" in str(e).lower() or "desabilit" in str(e).lower()


def test_ensure_installs_missing(monkeypatch):
    from okami.core import lazy_deps
    monkeypatch.setitem(lazy_deps.LAZY_DEPS, "test.y", ("pacote-inexistente-okami==9.9.9",))
    monkeypatch.delenv("OKAMI_DISABLE_LAZY_INSTALLS", raising=False)
    seen = {}
    monkeypatch.setattr(lazy_deps, "_allow_lazy_installs", lambda: True)
    # fake install: registra os specs e marca como satisfeito (pós-check passa)
    monkeypatch.setattr(lazy_deps, "_venv_pip_install",
                        lambda specs, **k: seen.update(specs=specs) or SimpleNamespace(success=True, stdout="", stderr=""))
    monkeypatch.setattr(lazy_deps, "feature_missing",
                        lambda f: () if seen.get("specs") else ("pacote-inexistente-okami==9.9.9",))
    lazy_deps.ensure("test.y", prompt=False)
    assert seen["specs"] == ("pacote-inexistente-okami==9.9.9",)   # tentou instalar o que faltava


def test_known_features_present():
    from okami.core.lazy_deps import LAZY_DEPS
    # features reais do Okami declaradas (TTS, search, provider)
    assert any(k.startswith("tts.") or k.startswith("provider.") or k.startswith("search.") for k in LAZY_DEPS)


def test_deps_cli_list_runs():
    from typer.testing import CliRunner
    from okami.cli import app
    r = CliRunner().invoke(app, ["deps", "list"])
    assert r.exit_code == 0 and "provider." in r.output      # lista as features da allowlist
