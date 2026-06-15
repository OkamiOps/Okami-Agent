"""Testes do desktop_notify (pesquisa #7 item 4) — notificação desktop best-effort.

Sonda em ordem (terminal-notifier -> notify-send -> fallback OSC-9 no stdout). Nunca levanta.
Redige segredos e trunca o corpo antes de qualquer envio externo.
"""
from __future__ import annotations

import sys

from okami.core import desktop


def test_fallback_osc9_when_no_binary(monkeypatch, capsys):
    """Sem terminal-notifier nem notify-send -> emite sequência OSC-9 no stdout e devolve True."""
    monkeypatch.setattr(desktop.shutil, "which", lambda _name: None)
    ok = desktop.desktop_notify("Okami", "tudo certo por aqui")
    assert ok is True
    out = capsys.readouterr().out
    # OSC 9: ESC ] 9 ; <texto> BEL
    assert "\x1b]9;" in out
    assert "tudo certo por aqui" in out
    assert out.endswith("\x07") or "\x07" in out


def test_terminal_notifier_argv(monkeypatch):
    """Com terminal-notifier no PATH -> chama subprocess.run com o argv certo e devolve True."""
    monkeypatch.setattr(
        desktop.shutil, "which",
        lambda name: "/usr/local/bin/terminal-notifier" if name == "terminal-notifier" else None,
    )
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs

        class _R:
            returncode = 0

        return _R()

    monkeypatch.setattr(desktop.subprocess, "run", fake_run)
    ok = desktop.desktop_notify("Título", "Corpo da mensagem")
    assert ok is True
    argv = captured["argv"]
    assert argv[0] == "terminal-notifier"
    assert "-title" in argv
    assert argv[argv.index("-title") + 1] == "Título"
    assert "-message" in argv
    assert argv[argv.index("-message") + 1] == "Corpo da mensagem"
    # best-effort: não deve travar indefinidamente
    assert captured["kwargs"].get("timeout") == 5
    assert captured["kwargs"].get("capture_output") is True


def test_notify_send_argv(monkeypatch):
    """Sem terminal-notifier, mas com notify-send -> chama notify-send com title+body e devolve True."""
    def which(name):
        if name == "notify-send":
            return "/usr/bin/notify-send"
        return None

    monkeypatch.setattr(desktop.shutil, "which", which)
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv

        class _R:
            returncode = 0

        return _R()

    monkeypatch.setattr(desktop.subprocess, "run", fake_run)
    ok = desktop.desktop_notify("Aviso", "olá")
    assert ok is True
    assert captured["argv"][0] == "notify-send"
    assert "Aviso" in captured["argv"]
    assert "olá" in captured["argv"]


def test_never_raises_when_all_sinks_raise(monkeypatch):
    """Se TODOS os sinks levantam, desktop_notify engole o erro e devolve False (nunca propaga)."""
    monkeypatch.setattr(
        desktop.shutil, "which",
        lambda name: "/bin/" + name,  # finge que ambos existem
    )

    def boom(*_a, **_k):
        raise OSError("explodiu")

    monkeypatch.setattr(desktop.subprocess, "run", boom)

    # stdout também explode -> nem o fallback OSC-9 funciona
    class _BadOut:
        def write(self, _s):
            raise OSError("stdout morto")

        def flush(self):
            raise OSError("stdout morto")

    monkeypatch.setattr(sys, "stdout", _BadOut())
    ok = desktop.desktop_notify("x", "y")
    assert ok is False  # nunca levanta, só sinaliza falha


def test_body_redacted_before_send(monkeypatch):
    """O corpo passa por redact() antes de ir pro sink — segredo não vaza pra notificação."""
    monkeypatch.setattr(
        desktop.shutil, "which",
        lambda name: "/usr/local/bin/terminal-notifier" if name == "terminal-notifier" else None,
    )
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv

        class _R:
            returncode = 0

        return _R()

    monkeypatch.setattr(desktop.subprocess, "run", fake_run)
    ok = desktop.desktop_notify("Build", "API_KEY=sk-abcdef0123456789abcd terminou")  # pragma: allowlist secret
    assert ok is True
    msg = captured["argv"][captured["argv"].index("-message") + 1]
    assert "sk-abcdef0123456789abcd" not in msg  # pragma: allowlist secret
    assert "«redacted»" in msg


def test_body_truncated_to_300(monkeypatch):
    """Corpo > 300 chars é truncado em 300 (proteção do canal de notificação)."""
    monkeypatch.setattr(
        desktop.shutil, "which",
        lambda name: "/usr/local/bin/terminal-notifier" if name == "terminal-notifier" else None,
    )
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv

        class _R:
            returncode = 0

        return _R()

    monkeypatch.setattr(desktop.subprocess, "run", fake_run)
    ok = desktop.desktop_notify("T", "a" * 500)
    assert ok is True
    msg = captured["argv"][captured["argv"].index("-message") + 1]
    assert len(msg) <= 300


def test_returns_false_when_subprocess_nonzero(monkeypatch, capsys):
    """terminal-notifier presente mas falha (returncode != 0) e sem outro binário -> cai pro fallback."""
    def which(name):
        return "/usr/local/bin/terminal-notifier" if name == "terminal-notifier" else None

    monkeypatch.setattr(desktop.shutil, "which", which)

    def fake_run(argv, **kwargs):
        class _R:
            returncode = 1

        return _R()

    monkeypatch.setattr(desktop.subprocess, "run", fake_run)
    ok = desktop.desktop_notify("T", "corpo")
    # caiu no fallback OSC-9 (que funciona) -> True
    assert ok is True
    assert "\x1b]9;" in capsys.readouterr().out
