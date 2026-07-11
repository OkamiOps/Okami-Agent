import pytest

from okami.config import build_config
from okami.llm import providers
from okami.llm.request import RequestCancelled, RequestContext, RequestTimeouts
from okami.llm.target_resolver import TargetResolver
from okami.llm.usage import Completion


def fallback_cfg(entries):
    return build_config({
        "default_provider": "primary",
        "providers": {
            "primary": {"model": "primary/default", "max_retries": 1, "fallback": entries},
            "backup": {"model": "backup/default", "max_retries": 1},
        },
    })


def test_legacy_provider_string_uses_destination_default_model():
    cfg = fallback_cfg(["backup"])
    chain = TargetResolver().fallback_targets(cfg, TargetResolver().resolve(cfg))
    assert [(t.provider, t.model) for t in chain] == [("backup", "backup/default")]


def test_structured_fallback_preserves_exact_model_base_and_api_mode():
    cfg = fallback_cfg([{"provider": "backup", "model": "vendor/exact",
                         "base_url": "https://fallback.example/v1",
                         "api_mode": "chat_completions"}])
    target = TargetResolver().fallback_targets(cfg, TargetResolver().resolve(cfg))[0]
    assert (target.model, target.base_url, target.api_mode) == (
        "vendor/exact", "https://fallback.example/v1", "chat_completions")


def test_fallback_deduplicates_effective_destination():
    cfg = fallback_cfg(["backup", {"provider": "backup", "model": "backup/default"}])
    assert len(TargetResolver().fallback_targets(cfg, TargetResolver().resolve(cfg))) == 1


def test_fallback_cycle_and_self_are_skipped():
    cfg = fallback_cfg(["primary", "backup"])
    chain = TargetResolver().fallback_targets(cfg, TargetResolver().resolve(cfg))
    assert [t.provider for t in chain] == ["backup"]


def test_cancelled_primary_never_enters_fallback(monkeypatch):
    calls = []
    monkeypatch.setattr(providers, "_complete_target", lambda target, *a, **k: calls.append(target.provider))
    ctx = RequestContext(RequestTimeouts(total_s=10))
    ctx.cancel("user")
    with pytest.raises(RequestCancelled):
        providers.complete_messages_ex(fallback_cfg(["backup"]), [], request=ctx)
    assert calls == []


def test_completion_reports_actual_fallback_provider_and_model(monkeypatch):
    def fake_one(pc, messages, model, response_schema, overrides):
        if pc.name == "primary":
            raise RuntimeError("provider overloaded")
        return Completion(text="ok", provider=pc.name, model=model or pc.model)

    monkeypatch.setattr(providers, "_complete_one", fake_one)
    result = providers.complete_messages_ex(fallback_cfg(["backup"]), [], _sleep=lambda seconds: None)
    assert (result.provider, result.model) == ("backup", "backup/default")


def test_fallback_attempts_two_models_from_same_provider(monkeypatch):
    cfg = build_config({
        "default_provider": "primary",
        "providers": {
            "primary": {"model": "primary/default", "max_retries": 1,
                         "fallback": [{"provider": "backup", "model": "backup/first"},
                                       {"provider": "backup", "model": "backup/second"}]},
            "backup": {"model": "backup/default", "max_retries": 1},
        },
    })
    seen = []

    def fake_one(pc, messages, model, response_schema, overrides):
        seen.append(model)
        if model == "backup/second":
            return Completion(text="ok", provider=pc.name, model=model)
        raise RuntimeError("provider overloaded")

    monkeypatch.setattr(providers, "_complete_one", fake_one)
    result = providers.complete_messages_ex(cfg, [], _sleep=lambda seconds: None)

    assert result.model == "backup/second"
    assert seen == ["primary/default", "backup/first", "backup/second"]
