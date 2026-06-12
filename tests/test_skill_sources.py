"""Skills hub MULTI-FONTE (pesquisa #6 item 11, paridade Hermes skills_hub).

Fontes com TIERS de confiança (taps configuráveis), well-known endpoints, e a MATRIZ
confiança×verdict-do-scan que decide a política de instalação (auto / confirmar / bloquear).
Sobre a base que já existe (quarentena + scan + lockfile com hash)."""
from __future__ import annotations

from okami.skills import sources as src


# ------------------------------------------------------------------ classificação de fonte
def test_classify_github_owner_repo():
    s = src.classify_source("someuser/some-skill")
    assert s.kind == "github" and s.trust == "community" and not s.exec_on_fetch


def test_classify_trusted_github_org():
    # org no tap de confiança (anthropics/openai/NousResearch) → trusted
    s = src.classify_source("anthropics/skills")
    assert s.kind == "github" and s.trust == "trusted"


def test_classify_clawhub_exec_on_fetch():
    s = src.classify_source("clawhub:some-slug")
    assert s.kind == "clawhub" and s.exec_on_fetch and s.trust == "community"


def test_classify_local_path(tmp_path):
    (tmp_path / "s").mkdir()
    s = src.classify_source(str(tmp_path / "s"))
    assert s.kind == "local" and s.trust == "trusted"   # local é do dono → confiança alta


def test_classify_wellknown_url():
    s = src.classify_source("https://example.com/.well-known/skills/index.json")
    assert s.kind == "wellknown"


def test_custom_tap_makes_org_trusted(tmp_path, monkeypatch):
    monkeypatch.setattr("okami.home.okami_home", lambda: tmp_path)
    src.add_tap("github", "minha-org")
    assert src.classify_source("minha-org/x").trust == "trusted"
    assert "minha-org" in src.list_taps().get("github", [])


# ------------------------------------------------------------------ matriz confiança × verdict
def test_decision_trusted_clean_auto():
    assert src.install_decision("trusted", "INFO") == "auto"
    assert src.install_decision("builtin", "LOW") == "auto"


def test_decision_community_clean_confirm():
    assert src.install_decision("community", "LOW") == "confirm"


def test_decision_any_high_blocks():
    assert src.install_decision("trusted", "HIGH") == "block"
    assert src.install_decision("community", "CRITICAL") == "block"


def test_decision_unverified_medium_confirm_or_block():
    # MEDIUM de fonte não-confiável → ao menos confirmar (não auto)
    assert src.install_decision("community", "MEDIUM") in ("confirm", "block")
    assert src.install_decision("trusted", "MEDIUM") == "confirm"


# ------------------------------------------------------------------ well-known index
def test_fetch_wellknown_parses_index():
    payload = {"skills": [{"name": "deploy", "source": "org/deploy-skill", "version": "1.0"},
                          {"name": "lint", "source": "org/lint-skill"}]}
    entries = src.fetch_wellknown("https://x.com", http=lambda url: payload)
    assert len(entries) == 2
    assert entries[0]["name"] == "deploy" and entries[0]["source"] == "org/deploy-skill"


def test_fetch_wellknown_bad_payload_empty():
    assert src.fetch_wellknown("https://x.com", http=lambda url: {"nope": 1}) == []


def test_fetch_wellknown_fail_open():
    def boom(url):
        raise RuntimeError("rede")
    assert src.fetch_wellknown("https://x.com", http=boom) == []
