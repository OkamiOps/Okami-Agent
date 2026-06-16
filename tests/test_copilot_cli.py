"""#19 backend Copilot via CLI (paridade Hermes copilot_acp_client) — GitHub Copilot como provider."""
from __future__ import annotations

from types import SimpleNamespace


def _pc():
    return SimpleNamespace(name="copilot", model="gpt-5", transport="copilot_cli",
                           reasoning_effort=None)


def test_copilot_cli_flattens_and_parses():
    from okami.llm.transports import copilot_cli_complete
    captured = {}

    def _run(cmd, prompt):
        captured["cmd"] = cmd
        captured["prompt"] = prompt
        return SimpleNamespace(returncode=0, stdout="resposta do copilot", stderr="")

    comp = copilot_cli_complete(_pc(), [{"role": "system", "content": "seja breve"},
                                        {"role": "user", "content": "oi"}], None,
                                _run=_run, _binary="/usr/bin/copilot")
    assert comp.text == "resposta do copilot"
    assert "seja breve" in captured["prompt"] and "oi" in captured["prompt"]
    assert captured["cmd"][0] == "/usr/bin/copilot"


def test_copilot_cli_no_binary_raises():
    import pytest

    from okami.llm.transports import copilot_cli_complete
    with pytest.raises(RuntimeError, match="copilot"):
        copilot_cli_complete(_pc(), [{"role": "user", "content": "x"}], None,
                             _run=lambda c, p: None, _binary=None)


def test_copilot_cli_nonzero_exit_raises():
    import pytest

    from okami.llm.transports import copilot_cli_complete

    def _run(cmd, prompt):
        return SimpleNamespace(returncode=1, stdout="", stderr="boom")

    with pytest.raises(RuntimeError, match="falhou"):
        copilot_cli_complete(_pc(), [{"role": "user", "content": "x"}], None,
                             _run=_run, _binary="/usr/bin/copilot")


def test_dispatch_routes_copilot_cli(monkeypatch):
    from okami.llm import transports
    pc = SimpleNamespace(transport="copilot_cli", name="copilot", model="gpt-5")
    monkeypatch.setattr(transports, "copilot_cli_complete",
                        lambda pc, m, model, ov=None: SimpleNamespace(text="ROTEOU"))
    out = transports.dispatch(pc, [{"role": "user", "content": "x"}], None)
    assert out.text == "ROTEOU"
