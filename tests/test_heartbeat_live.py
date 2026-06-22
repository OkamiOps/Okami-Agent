"""Visibilidade AO VIVO em turno longo (queixa do dono: esperou 10min vendo só '~N min', sem saber o que
o agente fazia nem o custo). O heartbeat agora carrega passo atual + tokens acumulados, vindos dos eventos
'step'/'llm_call' que o harness já emite."""
from __future__ import annotations

from okami.gateway.heartbeat import heartbeat_message


def test_heartbeat_plain_unchanged():
    # compat: sem extras → string idêntica à antiga (não quebra testes/usuário acostumado)
    assert heartbeat_message(elapsed_s=60) == "⏳ ainda trabalhando nisso, ~1 min…"


def test_heartbeat_with_step_and_tokens():
    out = heartbeat_message(elapsed_s=600, steps=4, tokens=12800, tool="generate_pdf")
    assert out == "⏳ ainda trabalhando nisso, ~10 min… · passo 4 (generate_pdf) · ~13k tok"


def test_heartbeat_small_token_count():
    out = heartbeat_message(elapsed_s=120, steps=1, tokens=300)
    assert "passo 1" in out and "~300 tok" in out


def test_live_tracker_accumulates_from_events():
    """O wrapper de on_event soma passos e tokens dos eventos do harness (sem depender de canal)."""
    live = {"steps": 0, "tokens": 0, "tool": ""}

    def track(e):  # espelha a lógica do endpoint._run
        k = e.get("kind")
        if k == "step":
            live["steps"] += 1
            live["tool"] = e.get("tool") or live["tool"]
        elif k == "llm_call":
            live["tokens"] += int(e.get("tokens_in", 0) or 0) + int(e.get("tokens_out", 0) or 0)

    track({"kind": "llm_call", "tokens_in": 1000, "tokens_out": 200})
    track({"kind": "step", "tool": "read_file"})
    track({"kind": "llm_call", "tokens_in": 800, "tokens_out": 100})
    track({"kind": "step", "tool": "generate_pdf"})
    assert live == {"steps": 2, "tokens": 2100, "tool": "generate_pdf"}
