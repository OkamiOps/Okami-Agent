"""Catálogo de advisories de supply-chain (pesquisa #6 item 15, paridade Hermes security_advisories).

Pacotes Python comprometidos conhecidos (ex.: worm Shai-Hulud) checados no boot via
importlib.metadata.version() — barato. Hits aparecem no doctor; podem ser reconhecidos (ack)
e param de aparecer. Catálogo é dado, não código.
"""
from __future__ import annotations

from okami.core import advisories as adv


def test_catalog_shape():
    assert adv.ADVISORIES, "catálogo não pode estar vazio"
    a = adv.ADVISORIES[0]
    assert {"id", "package", "versions", "severity", "why"} <= set(a)


def test_detect_compromised_hit(monkeypatch):
    monkeypatch.setattr(adv, "_installed_version", lambda pkg: "2.4.6" if pkg == "evilpkg" else None)
    monkeypatch.setattr(adv, "ADVISORIES", [
        {"id": "TEST-1", "package": "evilpkg", "versions": ["2.4.6"], "severity": "critical",
         "why": "worm de teste"}])
    hits = adv.detect_compromised()
    assert len(hits) == 1 and hits[0]["id"] == "TEST-1" and hits[0]["installed"] == "2.4.6"


def test_detect_skips_other_versions(monkeypatch):
    monkeypatch.setattr(adv, "_installed_version", lambda pkg: "1.0.0")
    monkeypatch.setattr(adv, "ADVISORIES", [
        {"id": "T", "package": "p", "versions": ["2.4.6"], "severity": "high", "why": "x"}])
    assert adv.detect_compromised() == []


def test_detect_skips_not_installed(monkeypatch):
    monkeypatch.setattr(adv, "_installed_version", lambda pkg: None)
    monkeypatch.setattr(adv, "ADVISORIES", [
        {"id": "T", "package": "p", "versions": ["2.4.6"], "severity": "high", "why": "x"}])
    assert adv.detect_compromised() == []


def test_ack_silences(monkeypatch, tmp_path):
    monkeypatch.setattr("okami.home.okami_home", lambda: tmp_path)
    monkeypatch.setattr(adv, "_installed_version", lambda pkg: "2.4.6")
    monkeypatch.setattr(adv, "ADVISORIES", [
        {"id": "ACK-1", "package": "p", "versions": ["2.4.6"], "severity": "high", "why": "x"}])
    assert len(adv.detect_compromised()) == 1
    assert len(adv.detect_compromised(include_acked=False)) == 1   # ainda não reconhecido
    adv.ack("ACK-1")
    assert adv.detect_compromised(include_acked=False) == []       # reconhecido → silenciado
    assert len(adv.detect_compromised(include_acked=True)) == 1    # mas ainda detectável


def test_version_match_ignores_build_suffix(monkeypatch):
    monkeypatch.setattr(adv, "_installed_version", lambda pkg: "2.4.6+local")
    monkeypatch.setattr(adv, "ADVISORIES", [
        {"id": "T", "package": "p", "versions": ["2.4.6"], "severity": "high", "why": "x"}])
    assert len(adv.detect_compromised()) == 1


def test_doctor_includes_advisories(monkeypatch):
    from okami.core import doctor
    from okami.config import build_config
    monkeypatch.setattr(adv, "_installed_version", lambda pkg: "2.4.6")
    monkeypatch.setattr(adv, "ADVISORIES", [
        {"id": "D", "package": "p", "versions": ["2.4.6"], "severity": "critical", "why": "x"}])
    cfg = build_config({"default_provider": "a", "providers": {"a": {"model": "m", "api_key": "k"}}})
    rep = doctor.build_report(cfg)
    assert rep["checks"].get("advisories")
    assert not doctor.health_ok(rep)        # advisory crítico não-reconhecido → não-saudável
