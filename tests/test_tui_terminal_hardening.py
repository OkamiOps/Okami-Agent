"""Portas do audit da TUI: focus-report/bracketed-paste (prompt_toolkit), /redraw, verbos pt-BR e o
sufixo '[exit N]' no card de tool falha. Tudo testável sem TTY real."""

from __future__ import annotations

from okami import tui


# ---------------------------------------------------------------- WIN1: focus-report ANSI swallowing
def test_install_focus_report_ignore_registers_escape_sequences():
    n = tui.install_focus_report_ignore()
    try:
        from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES
        from prompt_toolkit.keys import Keys
    except Exception:                                   # sem prompt_toolkit instalado: função devolve 0
        assert n == 0
        return
    assert ANSI_SEQUENCES["\x1b[I"] == Keys.Ignore
    assert ANSI_SEQUENCES["\x1b[O"] == Keys.Ignore
    # idempotente: chamar de novo não muda nada (já registrado)
    assert tui.install_focus_report_ignore() == 0


# ---------------------------------------------------------------- WIN2: bracketed-paste timeout patch
def test_install_bracketed_paste_timeout_patch_is_idempotent_smoke():
    ok = tui.install_bracketed_paste_timeout_patch()
    try:
        import prompt_toolkit.input.vt100_parser as _vt100_mod
    except Exception:
        assert ok is False
        return
    assert ok is True
    assert getattr(_vt100_mod, "_okami_bp_timeout_patched", False) is True
    # segunda chamada: idempotente (não re-patcheia, mas continua reportando sucesso)
    assert tui.install_bracketed_paste_timeout_patch() is True


def test_bracketed_paste_timeout_flushes_stuck_paste():
    """Simula um paste sem o fim (ESC[201~ perdido) — depois do timeout, o conteúdo bufferizado é
    entregue como BracketedPaste em vez de travar pra sempre (upstream #16263)."""
    import time

    import prompt_toolkit.input.vt100_parser as _vt100_mod
    from prompt_toolkit.input.vt100_parser import Vt100Parser
    from prompt_toolkit.keys import Keys
    _vt100_mod._okami_bp_timeout_patched = False    # força reaplicar c/ timeout curto (idempotência trava o valor)
    tui.install_bracketed_paste_timeout_patch(timeout_s=0.01)

    received = []
    parser = Vt100Parser(lambda kp: received.append(kp))
    parser.feed("\x1b[200~")                              # início do bracketed paste
    parser.feed("conteudo colado sem fim")                 # SEM o ESC[201~ (marcador perdido)
    assert received == []                                  # ainda esperando (dentro do timeout)
    time.sleep(0.02)
    parser.feed("")                                        # próximo tick de input dispara o flush
    assert any(kp.key == Keys.BracketedPaste for kp in received)
    assert "conteudo colado sem fim" in received[-1].data


# ---------------------------------------------------------------- WIN3: /redraw + SIGWINCH
def test_redraw_sequence_is_home_and_erase():
    assert tui.redraw_sequence() == "\x1b[H\x1b[J"


def test_route_repl_line_redraw():
    assert tui._route_repl_line("/redraw", busy=False, pending_approval=False) == "redraw"
    assert tui._route_repl_line("/redraw", busy=True, pending_approval=False) == "redraw"   # funciona ocupado


# ---------------------------------------------------------------- WIN6: verbos pt-BR + [exit N]
def test_tool_verb_known_and_fallback():
    assert tui.tool_verb("run_shell") == "executando comando"
    assert tui.tool_verb("read_file") == "lendo arquivo"
    assert tui.tool_verb("mcp__custom__thing") == "mcp__custom__thing"   # desconhecida → nome cru


def test_running_tool_text_uses_verb_phrase():
    txt = tui.running_tool_text("read_file", {"path": "a.py"}).plain
    assert "lendo arquivo" in txt
    assert "read_file" not in txt


def test_exit_code_extraction():
    assert tui._exit_code_of("execute_code: exit=1\nboom") == 1
    assert tui._exit_code_of("status=exited exit=-9\nkilled") == -9
    assert tui._exit_code_of("no exit info here") is None
    assert tui._exit_code_of("") is None


def test_chat_command_module_imports_cleanly():
    """Smoke test import-time p/ o wiring de SIGWINCH/prompt_toolkit em chat.py (comportamento de
    terminal de verdade — paste/resize — só é observável com um TTY real; aqui garantimos que o módulo
    carrega sem side-effect quebrado, mesmo fora de um terminal)."""
    import importlib

    import okami.cli.commands.chat as chat_mod
    importlib.reload(chat_mod)
    assert hasattr(chat_mod, "_run_repl") and hasattr(chat_mod, "chat")


def test_event_line_shows_exit_code_suffix_on_failure():
    fail = {"kind": "step", "tool": "run_shell", "ok": False, "args": {"cmd": "false"},
            "out": "execute_code: exit=2\nsome output"}
    txt = tui.event_line(fail, "collapsed").plain
    assert "[exit 2]" in txt
    ok = {"kind": "step", "tool": "run_shell", "ok": True, "args": {"cmd": "true"},
          "out": "execute_code: exit=0\nok"}
    assert "[exit" not in tui.event_line(ok, "collapsed").plain     # sucesso não mostra o sufixo
    fail_no_code = {"kind": "step", "tool": "run_shell", "ok": False, "args": {}, "out": "sem código aqui"}
    assert "[exit" not in tui.event_line(fail_no_code, "collapsed").plain
