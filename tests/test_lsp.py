"""#17 LSP (cliente): camadas puras — framing JSON-RPC, range-shift diff-aware, reporter, workspace."""
from __future__ import annotations

import asyncio


# ── protocol: framing Content-Length + envelopes + classify ──
def test_encode_message_frames_content_length():
    from okami.lsp.protocol import encode_message
    raw = encode_message({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert raw.startswith(b"Content-Length: ")
    assert b"\r\n\r\n" in raw and b'"method":"initialize"' in raw


def test_read_message_roundtrip():
    from okami.lsp.protocol import encode_message, read_message
    msg = {"jsonrpc": "2.0", "id": 7, "result": {"ok": True}}

    async def scenario():
        reader = asyncio.StreamReader()
        reader.feed_data(encode_message(msg))
        reader.feed_eof()
        return await read_message(reader)

    assert asyncio.run(scenario()) == msg


def test_read_message_clean_eof_returns_none():
    from okami.lsp.protocol import read_message

    async def scenario():
        reader = asyncio.StreamReader()
        reader.feed_eof()
        return await read_message(reader)

    assert asyncio.run(scenario()) is None


def test_read_message_rejects_bad_framing():
    import pytest

    from okami.lsp.protocol import LSPProtocolError, read_message

    async def scenario():
        reader = asyncio.StreamReader()
        reader.feed_data(b"Content-Length: notanumber\r\n\r\n{}")
        reader.feed_eof()
        await read_message(reader)

    with pytest.raises(LSPProtocolError):
        asyncio.run(scenario())


def test_classify_message():
    from okami.lsp.protocol import classify_message, make_notification, make_request, make_response
    assert classify_message(make_request(1, "m", None)) == ("request", 1)
    assert classify_message(make_response(1, {})) == ("response", 1)
    assert classify_message(make_notification("x", None)) == ("notification", "x")
    assert classify_message({"foo": 1})[0] == "invalid"


# ── range_shift: remap de linha diff-aware ──
def test_build_line_shift_identity_when_unchanged():
    from okami.lsp.range_shift import build_line_shift
    shift = build_line_shift("a\nb\nc\n", "a\nb\nc\n")
    assert shift(0) == 0 and shift(2) == 2


def test_build_line_shift_insertion_pushes_down():
    from okami.lsp.range_shift import build_line_shift
    # insere 2 linhas no topo → a linha 0 vira 2
    shift = build_line_shift("x\ny\n", "novo\nnovo2\nx\ny\n")
    assert shift(0) == 2 and shift(1) == 3


def test_build_line_shift_deleted_line_returns_none():
    from okami.lsp.range_shift import build_line_shift
    shift = build_line_shift("a\nDEL\nb\n", "a\nb\n")
    assert shift(1) is None                               # linha deletada → sem contraparte
    assert shift(0) == 0


def test_shift_baseline_drops_deleted_diagnostics():
    from okami.lsp.range_shift import build_line_shift, shift_baseline
    shift = build_line_shift("a\nDEL\nb\n", "a\nb\n")
    baseline = [
        {"message": "e1", "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 1}}},
        {"message": "del", "range": {"start": {"line": 1, "character": 0}, "end": {"line": 1, "character": 1}}},
    ]
    out = shift_baseline(baseline, shift)
    assert len(out) == 1 and out[0]["message"] == "e1"   # o diagnostic da linha deletada some


# ── reporter: formatação ──
def test_report_for_file_formats_errors_only():
    from okami.lsp.reporter import report_for_file
    diags = [
        {"severity": 1, "message": "undefined name 'x'", "code": "name-undefined", "source": "pyright",
         "range": {"start": {"line": 4, "character": 9}}},
        {"severity": 2, "message": "unused", "range": {"start": {"line": 1, "character": 0}}},
    ]
    block = report_for_file("/foo.py", diags)
    assert 'file="/foo.py"' in block
    assert "ERROR [5:10] undefined name 'x' [name-undefined] (pyright)" in block
    assert "unused" not in block                          # WARN filtrado por padrão


def test_report_for_file_empty_when_no_errors():
    from okami.lsp.reporter import report_for_file
    assert report_for_file("/x.py", [{"severity": 3, "message": "info", "range": {}}]) == ""


# ── workspace: gating por git ──
def test_workspace_gated_requires_git(tmp_path):
    from okami.lsp.workspace import find_git_worktree, workspace_gated
    f = tmp_path / "sub" / "a.py"
    f.parent.mkdir(parents=True)
    f.write_text("x=1", encoding="utf-8")
    assert workspace_gated(str(f)) is False              # sem .git → gateado off
    (tmp_path / ".git").mkdir()
    assert find_git_worktree(str(f)) == str(tmp_path)
    assert workspace_gated(str(f)) is True               # com .git → ativa


def test_nearest_root_finds_marker_and_respects_exclude(tmp_path):
    from okami.lsp.workspace import nearest_root
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    sub = tmp_path / "pkg"
    sub.mkdir()
    assert nearest_root(str(sub), ["pyproject.toml"]) == str(tmp_path)
    # exclude que casa antes → gateia off
    (sub / "deno.json").write_text("", encoding="utf-8")
    assert nearest_root(str(sub / "f.ts"), ["package.json"], excludes=["deno.json"]) is None


# ── servers: catálogo ──
def test_server_for_path_matches_extension():
    from okami.lsp.servers import server_for_path
    assert server_for_path("/x/foo.py").id == "pyright"
    assert server_for_path("/x/foo.rs").id == "rust-analyzer"
    assert server_for_path("/x/foo.unknown") is None


def test_server_status_reports_install_state():
    from okami.lsp.servers import server_status
    rows = server_status()
    assert any(r["id"] == "pyright" for r in rows)
    for r in rows:
        assert "installed" in r and isinstance(r["installed"], bool)


# ── CLI `okami lsp` ──
def test_cli_lsp_list_runs():
    from typer.testing import CliRunner

    from okami.cli import app
    res = CliRunner().invoke(app, ["lsp", "list"])
    assert res.exit_code == 0 and "pyright" in res.stdout


def test_cli_lsp_which_known_and_unknown():
    from typer.testing import CliRunner

    from okami.cli import app
    ok = CliRunner().invoke(app, ["lsp", "which", "pyright"])
    assert ok.exit_code == 0 and "pyright" in ok.stdout.lower()
    bad = CliRunner().invoke(app, ["lsp", "which", "naoexiste"])
    assert bad.exit_code != 0


def test_cli_lsp_status_json():
    import json

    from typer.testing import CliRunner

    from okami.cli import app
    res = CliRunner().invoke(app, ["lsp", "status", "--json"])
    assert res.exit_code == 0
    data = json.loads(res.stdout)
    assert any(s["id"] == "pyright" for s in data)


# ── BUG: truncate com limit < len(marker) produzia fatia NEGATIVA (saída MAIOR que o original) ──
def test_truncate_guards_tiny_limit():
    from okami.lsp.reporter import truncate
    out = truncate("x" * 100, limit=5)               # limit < len(marker)
    assert len(out) < 30 and "truncado" in out        # devolve só o marcador, não explode
    assert truncate("curto", limit=999) == "curto"    # menor que o limite → intacto


# ── CLI `okami lsp probe <file>` (usa o pool persistente; degrada sem servidor) ──
def test_cli_lsp_probe_graceful(tmp_path):
    from typer.testing import CliRunner

    from okami.cli import app
    f = tmp_path / "x.py"
    f.write_text("x = 1\n", encoding="utf-8")
    res = CliRunner().invoke(app, ["lsp", "probe", str(f)])
    assert res.exit_code == 0                              # nunca crasha (sem server/sem git → mensagem)
