"""Resiliência do harness contra TRAVAMENTO (o agente não pode pendurar ~6min e morrer).

Cobre: timeout classificado p/ encolher+failover, recuperação por compactação+retry quando uma
geração falha (era o que faltava), e o teto de relógio do turno (para LIMPO em vez de travar)."""

from __future__ import annotations

import okami.core.harness.loop as loop_mod
from okami.core import Task
from okami.core.harness import Harness
from okami.core.harness.models import Budget
from okami.llm.errors import classify


def test_timeout_classified_as_fallback_and_compress():
    # timeout ≈ contexto grande/modelo lento → tem que ENCOLHER (compress) e TROCAR de provider (fallback),
    # não só re-tentar o mesmo no mesmo tamanho (o que pendurava e morria).
    ce = classify(RuntimeError("read timed out"))
    assert ce.reason == "timeout"
    assert ce.retryable and ce.fallback and ce.compress


def test_generate_timeout_recovers_via_shrink_and_retry(tmp_path, monkeypatch):
    """1ª geração dá timeout → harness COMPACTA forte e RE-GERA (menor/mais rápido) → conclui.
    Antes: só escalava p/ modelo mais forte com o MESMO contexto gigante → pendurava de novo."""
    calls = {"gen": 0, "compact": 0}

    def gen(messages, schema):
        calls["gen"] += 1
        if calls["gen"] == 1:
            raise RuntimeError("read timed out")           # provider pendurou (esgotou retry/failover)
        return '{"tool": "task_complete", "args": {"summary": "feito"}}'

    def fake_compact(messages, memory, *, keep_tail=6, source="compaction"):
        calls["compact"] += 1
        return [messages[0]], 0                              # encolhe drasticamente (system só)

    # estimate: depois da compactação (1 msg) < antes → o caminho de retry dispara
    monkeypatch.setattr(loop_mod._compaction, "compact", fake_compact)
    monkeypatch.setattr(loop_mod._compaction, "estimate_chars", lambda m: 100 if len(m) <= 1 else 5000)

    h = Harness(generate=gen, task=Task(goal="diga oi"), workspace=tmp_path)
    res = h.run()
    assert calls["gen"] == 2, "não re-gerou após encolher"
    assert calls["compact"] >= 1, "não compactou na falha"
    assert res.state.name == "COMPLETE"


def test_shrink_retry_happens_only_once_per_episode(tmp_path, monkeypatch):
    # se ENCOLHER e ainda falhar, NÃO fica encolhendo p/ sempre — cai p/ escalar/desistir (1x por episódio).
    calls = {"gen": 0}

    def gen(messages, schema):
        calls["gen"] += 1
        raise RuntimeError("read timed out")               # sempre falha

    monkeypatch.setattr(loop_mod._compaction, "compact", lambda m, mem, **k: ([m[0]], 0))
    monkeypatch.setattr(loop_mod._compaction, "estimate_chars", lambda m: 100 if len(m) <= 1 else 5000)

    h = Harness(generate=gen, task=Task(goal="oi"), workspace=tmp_path)
    res = h.run()
    # 1ª gen (timeout) → encolhe+retry → 2ª gen (timeout) → sem mais encolher → escala/desiste.
    assert calls["gen"] <= 4                                 # não fica num loop infinito de encolher
    assert res.state.name in ("FAILED", "BLOCKED")


def test_empty_respond_recovers_prose(tmp_path):
    # modelo fraco escreve a resposta em PROSA e manda respond com message VAZIO → usa a prosa
    # (era o bug "pergunta o nome → só (COMPLETE)" mudo).
    def gen(messages, schema):
        return 'Meu nome é Minerva, prazer 💜\n{"tool": "respond", "args": {"message": ""}}'

    h = Harness(generate=gen, task=Task(goal="qual seu nome?"), workspace=tmp_path)
    res = h.run()
    assert res.state.name == "COMPLETE"
    assert "Minerva" in (res.result or ""), f"perdeu a fala: {res.result!r}"


def test_truly_empty_respond_reprompts_then_answers(tmp_path):
    # respond vazio SEM prosa → re-pede a resposta 1x → modelo responde de verdade.
    calls = {"n": 0}

    def gen(messages, schema):
        calls["n"] += 1
        if calls["n"] == 1:
            return '{"tool": "respond", "args": {"message": ""}}'      # vazio total
        return '{"tool": "respond", "args": {"message": "Sou a Minerva"}}'

    h = Harness(generate=gen, task=Task(goal="qual seu nome?"), workspace=tmp_path)
    res = h.run()
    assert calls["n"] == 2
    assert res.state.name == "COMPLETE" and "Minerva" in (res.result or "")


def test_stall_blocks_only_when_no_step_completes(tmp_path, monkeypatch):
    # ANTI-TRAVAMENTO (não teto de turno): se a agente fica sem CONCLUIR passo além do limite → BLOCKED.
    import time as _time
    clock = [0.0]
    monkeypatch.setattr(_time, "monotonic", lambda: clock[0])

    def gen(messages, schema):
        clock[0] += 200                               # cada chamada "gasta" 200s e NÃO produz ação válida
        return "só conversa, sem json nenhum"          # → violação, nenhum passo executado

    # goal com verbo de ação → não cai no atalho de "conversa pura"; violações altas p/ isolar o stall.
    h = Harness(generate=gen, task=Task(goal="crie o arquivo x.txt"), workspace=tmp_path,
                budget=Budget(max_stall_seconds=300, max_consecutive_violations=999))
    res = h.run()
    assert res.state.name == "BLOCKED"
    assert "travei" in (res.reason or "") and "sem concluir" in (res.reason or "")


def test_long_active_work_never_stalls(tmp_path, monkeypatch):
    # O PONTO da mudança: trabalho longo de VERDADE (muitos passos com efeito) NÃO expira por tempo —
    # mesmo "gastando" horas de relógio — porque cada passo reseta o anti-travamento.
    import time as _time
    clock = [0.0]
    monkeypatch.setattr(_time, "monotonic", lambda: clock[0])
    n = [0]

    def gen(messages, schema):
        clock[0] += 200                               # 200s POR passo → 30 passos = 6000s (100min) de relógio
        n[0] += 1
        if n[0] <= 30:                                # 30 escritas DISTINTAS (efeito real, sem loop)
            return f'{{"tool": "write_file", "args": {{"path": "f{n[0]}.txt", "content": "{n[0]}"}}}}'
        return '{"tool": "task_complete", "args": {"summary": "feito"}}'

    h = Harness(generate=gen, task=Task(goal="crie 30 arquivos"), workspace=tmp_path,
                budget=Budget(max_stall_seconds=300, max_steps=90))
    res = h.run()
    assert res.state.name == "COMPLETE", f"trabalho longo foi morto indevidamente: {res.reason!r}"
    assert n[0] >= 31 and (tmp_path / "f30.txt").exists()


def test_stall_guard_disabled_when_zero(tmp_path, monkeypatch):
    # max_stall_seconds=0 → desliga o anti-travamento (confia no timeout por-chamada do transporte).
    import time as _time
    clock = [0.0]
    monkeypatch.setattr(_time, "monotonic", lambda: clock[0])

    def gen(messages, schema):
        clock[0] += 10_000                            # tempo enorme, mas guard desligado
        return '{"tool": "respond", "args": {"message": "oi"}}'

    h = Harness(generate=gen, task=Task(goal="diga oi"), workspace=tmp_path,
                budget=Budget(max_stall_seconds=0))
    res = h.run()
    assert res.state.name == "COMPLETE"               # não bloqueou por tempo
