"""#11 Onda 4: CLI/ops — tool-output limits config-driven, okami logs com filtro multi-eixo,
shell-completion."""
from __future__ import annotations

from types import SimpleNamespace


# ── tool-output limits config-driven ──
def test_output_limit_default_when_no_config():
    from okami.core.tool_output_limits import output_limit
    assert output_limit(None, "max_bytes", 100_000) == 100_000          # sem cfg → default
    assert output_limit(SimpleNamespace(tools={}), "max_bytes", 100_000) == 100_000


def test_output_limit_reads_config():
    from okami.core.tool_output_limits import output_limit
    cfg = SimpleNamespace(tools={"tool_output": {"max_bytes": 250_000, "max_lines": 5000}})
    assert output_limit(cfg, "max_bytes", 100_000) == 250_000
    assert output_limit(cfg, "max_lines", 2000) == 5000
    assert output_limit(cfg, "max_line_length", 4000) == 4000           # ausente → default


def test_output_limit_ignores_malformed():
    from okami.core.tool_output_limits import output_limit
    cfg = SimpleNamespace(tools={"tool_output": {"max_bytes": "muito"}})  # valor não-int → default
    assert output_limit(cfg, "max_bytes", 100_000) == 100_000


# ── okami logs filtro multi-eixo ──
def test_filter_log_lines_by_level_and_component():
    from okami.cli.log_filter import filter_log_lines
    lines = [
        "2026-06-16T10:00:00 INFO gateway: subiu",
        "2026-06-16T10:01:00 ERROR agent: caiu",
        "2026-06-16T10:02:00 WARNING tools: lento",
    ]
    assert filter_log_lines(lines, level="ERROR") == ["2026-06-16T10:01:00 ERROR agent: caiu"]
    assert len(filter_log_lines(lines, component="gateway")) == 1


def test_filter_log_lines_since():
    from okami.cli.log_filter import filter_log_lines
    # now = epoch grande; só linhas com timestamp dentro da janela passam
    lines = ["2020-01-01T00:00:00 INFO x: velho", "2030-01-01T00:00:00 INFO x: novo"]
    out = filter_log_lines(lines, since="1h", now=1893456000.0)          # 2030-01-01
    assert any("novo" in line for line in out) and not any("velho" in line for line in out)


def test_parse_since_duration():
    from okami.cli.log_filter import parse_duration
    assert parse_duration("30m") == 1800
    assert parse_duration("2h") == 7200
    assert parse_duration("1d") == 86400
    assert parse_duration("lixo") is None


# ── shell-completion ──
def test_completion_script_per_shell():
    from okami.cli.completion import completion_script
    for sh in ("bash", "zsh", "fish"):
        s = completion_script(sh)
        assert "_OKAMI_COMPLETE" in s and sh in s
    assert completion_script("tcsh") is None        # shell não suportado → None
