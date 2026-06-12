"""Pool de credenciais PERSISTENTE (pesquisa #6 item 20, paridade Hermes credential_pool).

Status ok/exhausted/dead com TTL por classe de erro, PERSISTIDO em disco (sobrevive a restart e é
compartilhado entre processos gateway/cron/CLI). Segurança: guarda só o FINGERPRINT (sha256) da
chave, NUNCA o valor — fail-closed no limite do disco.
"""
from __future__ import annotations

import json

from okami.llm import cred_pool as cp


def _home(monkeypatch, tmp_path):
    monkeypatch.setattr("okami.home.okami_home", lambda: tmp_path)


def test_mark_and_available(monkeypatch, tmp_path):
    _home(monkeypatch, tmp_path)
    cp.mark("prov", "key-A", "rate_limit", now=1000.0)
    avail = cp.available("prov", ["key-A", "key-B"], now=1000.0)
    assert avail == ["key-B"]                          # A exausta → fora; B disponível


def test_ttl_per_error_class(monkeypatch, tmp_path):
    _home(monkeypatch, tmp_path)
    cp.mark("p", "k", "rate_limit", now=0.0)
    assert cp.available("p", ["k"], now=3000.0) == []        # < 1h ainda exausta
    assert cp.available("p", ["k"], now=4000.0) == ["k"]     # > 1h voltou


def test_billing_longer_ttl(monkeypatch, tmp_path):
    _home(monkeypatch, tmp_path)
    cp.mark("p", "k", "billing", now=0.0)
    assert cp.available("p", ["k"], now=3600.0 * 5) == []    # billing 6h: 5h ainda fora


def test_auth_permanent_is_dead(monkeypatch, tmp_path):
    _home(monkeypatch, tmp_path)
    cp.mark("p", "k", "auth_permanent", now=0.0)
    assert cp.status("p", "k", now=0.0) == "dead"
    assert cp.available("p", ["k"], now=3600.0 * 12) == []   # dead segura por muito tempo


def test_clear_revives(monkeypatch, tmp_path):
    _home(monkeypatch, tmp_path)
    cp.mark("p", "k", "rate_limit", now=0.0)
    cp.clear("p", "k")
    assert cp.available("p", ["k"], now=100.0) == ["k"]


def test_persists_across_instances(monkeypatch, tmp_path):
    _home(monkeypatch, tmp_path)
    cp.mark("p", "k", "billing", now=0.0)
    # novo "processo": lê do disco
    assert cp.available("p", ["k"], now=100.0) == []


def test_never_stores_raw_key(monkeypatch, tmp_path):
    _home(monkeypatch, tmp_path)
    cp.mark("p", "super-secret-key-value", "rate_limit", now=0.0)
    raw = (tmp_path / "cred_pool.json").read_text(encoding="utf-8")
    assert "super-secret-key-value" not in raw         # só o fingerprint no disco
    assert json.loads(raw)                              # JSON válido


def test_fail_open_on_corrupt(monkeypatch, tmp_path):
    _home(monkeypatch, tmp_path)
    (tmp_path / "cred_pool.json").write_text("{lixo", encoding="utf-8")
    assert cp.available("p", ["k1", "k2"], now=0.0) == ["k1", "k2"]   # corrompido → tudo disponível


def test_available_is_strict_but_usable_or_all_degrades(monkeypatch, tmp_path):
    # available() é ESTRITO (vazio se todas fora); usable_or_all() degrada p/ o pool cheio (não trava)
    _home(monkeypatch, tmp_path)
    cp.mark("p", "k1", "rate_limit", now=0.0)
    cp.mark("p", "k2", "rate_limit", now=0.0)
    assert cp.available("p", ["k1", "k2"], now=100.0) == []                      # estrito
    assert set(cp.usable_or_all("p", ["k1", "k2"], now=100.0)) == {"k1", "k2"}   # degradação
