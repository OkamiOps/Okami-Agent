"""Testes do forense de shutdown (gateway/shutdown_forensics.py).

Verifica o snapshot best-effort (pid/ppid reais, nome do sinal) e que o format_context
sempre devolve uma linha legível — nunca levanta, mesmo em ambiente degradado.
"""
from __future__ import annotations

import os
import signal

from okami.gateway.shutdown_forensics import format_context, snapshot_shutdown_context


def test_snapshot_tem_pid_e_ppid_reais():
    # pid/ppid vêm direto do os — devem bater com o processo de teste.
    ctx = snapshot_shutdown_context()
    assert ctx["pid"] == os.getpid()
    assert ctx["ppid"] == os.getppid()


def test_snapshot_com_signum_traduz_nome_do_sinal():
    # SIGTERM (15) é o sinal de shutdown gracioso — o nome deve aparecer.
    ctx = snapshot_shutdown_context(signum=signal.SIGTERM)
    assert "TERM" in ctx["signal"]


def test_snapshot_sem_signum_tem_signal_vazio():
    # Sem sinal informado, o campo fica string vazia (não None) — fácil de formatar.
    ctx = snapshot_shutdown_context()
    assert ctx["signal"] == ""


def test_snapshot_tem_chaves_esperadas():
    # Contrato do dict: o caller (gateway) lê estes campos.
    ctx = snapshot_shutdown_context()
    for chave in ("signal", "pid", "ppid", "parent_cmd", "under_systemd", "loadavg"):
        assert chave in ctx
    assert isinstance(ctx["under_systemd"], bool)
    assert isinstance(ctx["parent_cmd"], str)


def test_format_context_devolve_linha_nao_vazia():
    # Sempre uma linha legível — vira log na hora do shutdown.
    out = format_context(snapshot_shutdown_context(signum=signal.SIGTERM))
    assert isinstance(out, str)
    assert out.strip() != ""


def test_format_context_aceita_ctx_capenga_sem_levantar():
    # Fail-safe: dict incompleto não pode derrubar quem está morrendo.
    out = format_context({})
    assert isinstance(out, str)
