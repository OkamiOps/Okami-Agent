"""Paridade Hermes (#3 do sweep): truncar a saída do shell preservando HEAD+TAIL. Head-only jogava fora a
CAUDA — onde o erro/traceback quase sempre está. clean_output ja fazia head+tail; _cap (foreground) nao."""
from __future__ import annotations

from okami.core.sandbox import _cap


def test_cap_keeps_head_and_error_tail():
    text = "INICIO_DA_SAIDA\n" + ("linha de ruído\n" * 5000) + "Traceback: ERRO_NO_FIM"
    out = _cap(text, 2000)
    assert "INICIO_DA_SAIDA" in out                      # head preservado
    assert "ERRO_NO_FIM" in out                          # CAUDA (erro) preservada — era o bug
    assert "omitido" in out                              # marcador do meio


def test_cap_short_text_unchanged():
    assert _cap("saída curta", 2000) == "saída curta"


def test_run_shell_strips_ansi_color_codes(tmp_path):
    # foreground run_shell agora limpa códigos ANSI (igual ao log de background) — antes vazava \x1b[…m
    from okami.core.tools import RunShell, ToolContext
    r = RunShell().run({"cmd": r"printf '\033[31mVERMELHO\033[0m fim'"}, ToolContext(workspace=tmp_path))
    assert "VERMELHO" in r.output and "\x1b[" not in r.output and "[31m" not in r.output
