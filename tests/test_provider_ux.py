"""Status de provider sem vazar segredo e com detalhes úteis para custom."""

from types import SimpleNamespace
from unittest.mock import patch


def test_provider_finish_reports_custom_endpoint_transport_and_env_ref():
    import okami.cli.commands.provider as provider

    pc = SimpleNamespace(
        model="openai/vendor-model",
        api_base="https://vendor.example/v1",
        transport="litellm",
        api_key_env="VENDOR_API_KEY",
        ready=True,
    )
    with patch.object(provider, "_load", return_value=SimpleNamespace(provider=lambda _: pc)), \
         patch.object(provider.console, "print") as printed:
        provider._provider_finish("vendor", {"model": "openai/vendor-model"}, made_default=False)

    output = " ".join(str(call.args[0]) for call in printed.call_args_list)
    assert "https://vendor.example/v1" in output
    assert "litellm" in output
    assert "VENDOR_API_KEY" in output
    assert "secret" not in output.lower()
