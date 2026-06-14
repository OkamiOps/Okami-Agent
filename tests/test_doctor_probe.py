"""Item 15b — sonda do doctor: distingue "endpoint off" de "modelo errado".

Quando o ping do endpoint responde E a lista de modelos vem junto, o doctor compara o `pc.model`
configurado (normalizado, sem prefixo de provider) com os ids retornados → `model_present`. Assim o
diagnóstico separa LMStudio desligado (ok=False) de um typo no nome do modelo (ok=True, present=False)."""

from __future__ import annotations

from okami.config import OkamiConfig, ProviderConfig
from okami.core.doctor import build_report


def _cfg(model: str) -> OkamiConfig:
    pc = ProviderConfig(name="local", model=model, api_base="http://localhost:1234/v1")
    return OkamiConfig(default_provider="local", providers={"local": pc})


def _ping_with_ids(ids):
    def ping(api_base):
        return True, f"{len(ids)} modelos", ids
    return ping


def test_model_present_true_on_match():
    cfg = _cfg("openai/qwen3.5-9b-mtp")
    rep = build_report(cfg, ping=_ping_with_ids(["qwen3.5-9b-mtp", "other-model"]))
    ep = rep["providers"][0]["endpoint"]
    assert ep["ok"] is True
    assert ep["model_present"] is True


def test_model_present_false_on_typo():
    cfg = _cfg("openai/qwen3.5-9b-mtpX")        # typo: não está na lista
    rep = build_report(cfg, ping=_ping_with_ids(["qwen3.5-9b-mtp", "other-model"]))
    ep = rep["providers"][0]["endpoint"]
    assert ep["ok"] is True
    assert ep["model_present"] is False         # endpoint vivo, mas modelo não existe lá


def test_endpoint_off_has_no_model_present():
    cfg = _cfg("openai/qwen3.5-9b-mtp")

    def ping_off(api_base):
        return False, "connection refused"

    rep = build_report(cfg, ping=ping_off)
    ep = rep["providers"][0]["endpoint"]
    assert ep["ok"] is False
    # endpoint off → não dá p/ saber do modelo; campo ausente ou None (não False enganoso).
    assert ep.get("model_present") is None


def test_legacy_ping_two_tuple_still_works():
    # ping antigo (ok, msg) sem ids → model_present None, sem quebrar (fail-open).
    cfg = _cfg("openai/qwen3.5-9b-mtp")

    def ping2(api_base):
        return True, "ok"

    rep = build_report(cfg, ping=ping2)
    ep = rep["providers"][0]["endpoint"]
    assert ep["ok"] is True
    assert ep.get("model_present") is None
