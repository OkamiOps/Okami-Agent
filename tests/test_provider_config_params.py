import pytest

from okami.config import ProviderConfig, build_config


def test_unknown_provider_keys_are_preserved_under_params_and_warn_once(monkeypatch):
    import okami.config as config

    warning_calls = []

    def warning(message, *args, **kwargs):
        warning_calls.append((message, args, kwargs))

    monkeypatch.setattr(config, "_WARNED_PROVIDER_EXTRAS", set())
    monkeypatch.setattr(config._logger, "warning", warning)
    raw = {"default_provider": "p", "providers": {"p": {
        "model": "m", "future_knob": {"enabled": True},
    }}}
    first = build_config(raw).provider()
    second = build_config(raw).provider()
    assert first.params["future_knob"] == {"enabled": True}
    assert second.params["future_knob"] == {"enabled": True}
    assert warning_calls == [
        ("unknown provider key '%s' preserved under params", ("future_knob",), {}),
    ]


def test_params_conflicting_with_known_provider_field_fails_clearly():
    with pytest.raises(ValueError, match="params.*model"):
        ProviderConfig(name="p", model="m", params={"model": "other"})
