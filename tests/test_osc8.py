"""Hyperlinks OSC-8 (pesquisa #7 item 8): emite só com TTY/FORCE, some com NO_COLOR, #L<linha>."""
from __future__ import annotations

import okami.cli._osc8 as osc8
from okami.cli._osc8 import link, supports_hyperlinks


def test_plain_quando_nao_suportado(monkeypatch):
    monkeypatch.delenv("FORCE_HYPERLINK", raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(osc8.sys, "stdout", type("S", (), {"isatty": staticmethod(lambda: False)})())
    assert link("/tmp/a.py", "a.py") == "a.py"          # sem TTY → texto puro, sem escape
    assert "\x1b" not in link("/tmp/a.py", "a.py")


def test_no_color_suprime(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("FORCE_HYPERLINK", raising=False)
    assert supports_hyperlinks() is False
    assert link("/tmp/a.py", "a.py") == "a.py"


def test_force_emite_osc8(monkeypatch):
    monkeypatch.setenv("FORCE_HYPERLINK", "1")
    out = link("/tmp/a.py", "a.py")
    assert out.startswith("\x1b]8;;file://")            # abre o hyperlink
    assert "a.py" in out                                # com o rótulo
    assert out.endswith("\x1b]8;;\x1b\\")               # fecha o hyperlink


def test_sufixo_de_linha(monkeypatch):
    monkeypatch.setenv("FORCE_HYPERLINK", "1")
    out = link("/tmp/a.py", "a.py", line=42)
    assert "#L42" in out


def test_path_absoluto_resolvido(monkeypatch, tmp_path):
    monkeypatch.setenv("FORCE_HYPERLINK", "1")
    f = tmp_path / "x.py"
    f.write_text("x = 1\n")
    out = link(str(f), "x.py")
    assert f"file://{f.resolve()}" in out               # vira caminho absoluto resolvido


def test_label_default_eh_o_target(monkeypatch):
    monkeypatch.setenv("FORCE_HYPERLINK", "1")
    out = link("/tmp/a.py")
    assert "/tmp/a.py" in out                           # sem `text` → usa o próprio path como rótulo
