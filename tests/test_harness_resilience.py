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


def test_bail_punt_after_exploration_is_nudged_then_completes(tmp_path):
    # O CASO REAL: agente EXPLORA (read-only) e aí ENCERRA pedindo "responde 1 ou 2 que eu sigo" em vez de
    # concluir. Como já houve passo, o nudge de "sem ferramenta" não pega → o detector de BAIL pega (1x).
    (tmp_path / "x.py").write_text("print(1)", encoding="utf-8")
    calls = {"n": 0}

    def gen(messages, schema):
        calls["n"] += 1
        if calls["n"] == 1:
            return '{"tool": "read_file", "args": {"path": "x.py"}}'              # explorou (read-only)
        if calls["n"] == 2:                          # BAIL: pede permissão/menu em vez de entregar
            return '{"tool": "respond", "args": {"message": "Achei um bug. Responde com 1 ou 2 que eu sigo."}}'
        return '{"tool": "respond", "args": {"message": "Achei e corrigi o bug; rodei os testes, passam."}}'

    h = Harness(generate=gen, task=Task(goal="testa o projeto e acha bugs"), workspace=tmp_path)
    res = h.run()
    assert calls["n"] == 3                            # read → bail (nudge) → entrega
    assert res.state.name == "COMPLETE" and "corrigi" in (res.result or "")
    assert "1 ou 2" not in (res.result or "")         # a resposta final NÃO é o bail


def test_bail_nudge_only_once_then_accepts(tmp_path):
    # se INSISTIR no bail, NÃO entra em loop infinito — nudga 1x e aceita o 2º.
    (tmp_path / "x.py").write_text("x", encoding="utf-8")
    calls = {"n": 0}

    def gen(messages, schema):
        calls["n"] += 1
        if calls["n"] == 1:
            return '{"tool": "read_file", "args": {"path": "x.py"}}'
        return '{"tool": "respond", "args": {"message": "Posso seguir?"}}'      # insiste no bail

    h = Harness(generate=gen, task=Task(goal="conserta o bug X"), workspace=tmp_path)
    res = h.run()
    assert res.state.name == "COMPLETE"               # aceitou após 1 nudge (sem travar)
    assert calls["n"] <= 4


def test_real_delivery_after_inspection_is_not_nudged(tmp_path):
    # ENTREGA de verdade depois de olhar o código (read_file) NÃO é empurrada — completa.
    (tmp_path / "x.py").write_text("print(1)", encoding="utf-8")
    calls = {"n": 0}

    def gen(messages, schema):
        calls["n"] += 1
        if calls["n"] == 1:
            return '{"tool": "read_file", "args": {"path": "x.py"}}'
        return '{"tool": "respond", "args": {"message": "Analisei x.py: 3 bugs (P0 find --delete). Corrigi e testei."}}'

    h = Harness(generate=gen, task=Task(goal="analisa e acha bugs"), workspace=tmp_path)
    res = h.run()
    assert calls["n"] == 2 and res.state.name == "COMPLETE"   # read + entrega, sem nudge extra


def test_pure_talk_on_action_goal_is_nudged(tmp_path):
    # pediu AÇÃO e o agente respondeu de MEMÓRIA (zero ferramenta) → re-prompt 1x.
    calls = {"n": 0}

    def gen(messages, schema):
        calls["n"] += 1
        if calls["n"] == 1:
            return '{"tool": "respond", "args": {"message": "acho que tem uns bugs aí"}}'   # papo, sem olhar
        return '{"tool": "read_file", "args": {"path": "x.py"}}'

    (tmp_path / "x.py").write_text("x", encoding="utf-8")
    h = Harness(generate=gen, task=Task(goal="analisa o código e acha bugs"), workspace=tmp_path)
    h.run()
    assert calls["n"] >= 2                             # foi empurrado a usar ferramenta


def test_prompt_has_hermes_action_and_verification_gates():
    from okami.core.harness.prompt import build_system_prompt
    p = build_system_prompt(Task(goal="faz X"), {})
    low = p.lower()
    # gate de ESCOPO: análise/teste = RELATÓRIO; não mutar/consertar/apagar sem pedido explícito
    assert "<escopo>" in low and "relatório" in low
    assert "não conserte" in low and ("faxina" in low or "__pycache__" in low)
    # gate de ENTREGA: conteúdo INTEIRO + DETALHADO na resposta; formato (tabela/por-suíte); anti over-claim
    assert "<entrega>" in low and "over-claim" in low
    assert "detalhado no chat" in low and "entregue no chat anterior" in low   # over-claim ampliado
    assert "tabela" in low and "por suíte" in low                              # comparação=tabela, testes detalhados
    # gates de AÇÃO (Hermes): persistência + uso obrigatório de ferramenta + anti-bail
    assert "<persistencia>" in low and "<use_ferramenta>" in low
    assert "menu" in low and "permiss" in low and "memória" in low
    # gate de VERIFICAÇÃO (Hermes): correção (cada parte) + grounding (não inventar) + ESCOPO/segurança
    assert "<verificacao>" in low and "correção" in low and "grounding" in low
    assert "<contexto_faltando>" in low and "need_input" in low
    # SEGURANÇA preservada: destrutivo defere à aprovação go/no-go, nunca é forçado
    assert "destrutiva nunca é forçada" in low and ("go/no-go" in low or "aprovaç" in low)
    assert "segurança antes de autonomia" in low


def test_length_continuation_assembles_truncated_report(tmp_path):
    # LENGTH-CONTINUATION (Hermes): respond CORTADO pelo limite (finish_reason='length') → continua e
    # CONCATENA; a entrega final é o relatório INTEIRO, não a metade cortada. (read antes = trabalho real.)
    from okami.llm.usage import Completion
    (tmp_path / "x.py").write_text("print(1)", encoding="utf-8")
    calls = {"n": 0}

    def gen(messages, schema):
        calls["n"] += 1
        if calls["n"] == 1:
            return Completion(text='{"tool": "read_file", "args": {"path": "x.py"}}', finish_reason="tool_calls")
        if calls["n"] == 2:                          # json do respond CORTADO no meio da message
            return Completion(text='{"tool": "respond", "args": {"message": "Relatorio P1 do bug X...',
                              finish_reason="length")
        return Completion(text=' e P2: o conserto e mover regex. FIM."}}', finish_reason="stop")

    h = Harness(generate=gen, task=Task(goal="faça o relatório do bug"), workspace=tmp_path)
    res = h.run()
    assert calls["n"] == 3                            # read → respond truncado → continuação
    assert res.state.name == "COMPLETE"
    assert "Relatorio P1" in (res.result or "") and "FIM." in (res.result or "")   # juntou as 2 partes


def test_length_continuation_has_a_cap(tmp_path):
    # se o modelo NUNCA para de truncar, não entra em loop infinito — termina (bounded).
    from okami.llm.usage import Completion
    calls = {"n": 0}

    def gen(messages, schema):
        calls["n"] += 1
        return Completion(text=f'pedaco{calls["n"]} ', finish_reason="length")   # sempre cortado, sem json

    h = Harness(generate=gen, task=Task(goal="diga algo"), workspace=tmp_path)
    res = h.run()
    assert calls["n"] <= 40                           # bounded — não loopa pra sempre
    assert res.state.name in ("COMPLETE", "BLOCKED", "FAILED")


def test_thin_deliverable_helper():
    from okami.core.harness.loop import _deliverable_too_thin as thin
    # comparação pedida + trabalho feito mas SEM tabela → raso
    assert thin("compara okami com hermes", "Okami é melhor em X, Hermes em Y.", real_steps=10)
    # comparação COM tabela markdown → ok
    assert not thin("compara okami com hermes", "| aspecto | okami | hermes |\n|--|--|--|\n| x | a | b |", 10)
    # muito trabalho + entrega curta → raso
    assert thin("analisa e acha bugs", "achei 1 bug", real_steps=15)
    # trabalho pequeno (papo) → NÃO é raso (não confunde resposta curta legítima)
    assert not thin("oi", "oi, tudo bem?", real_steps=0)
    # comparação mas SEM trabalho (só 2 passos) → não cobra tabela ainda
    assert not thin("compara x e y", "resumo", real_steps=2)


def test_thin_report_is_reprompted_for_full_version(tmp_path):
    # ESTRUTURAL: fez muito trabalho de comparação e entregou um parágrafo sem tabela → harness re-pede
    # o relatório COMPLETO 1x; aí o modelo manda a tabela e conclui.
    for i in range(8):
        (tmp_path / f"f{i}.txt").write_text("x", encoding="utf-8")
    calls = {"n": 0}

    def gen(messages, schema):
        calls["n"] += 1
        if calls["n"] <= 8:                          # 8 passos de "trabalho" (read)
            return f'{{"tool": "read_file", "args": {{"path": "f{calls["n"]-1}.txt"}}}}'
        if calls["n"] == 9:                          # entrega RASA: parágrafo, sem tabela
            return '{"tool": "respond", "args": {"message": "Okami ganha do Hermes em X e Y."}}'
        return ('{"tool": "respond", "args": {"message": '
                '"| aspecto | Okami | Hermes |\\n|--|--|--|\\n| sandbox | sim | sim |"}}')   # agora com tabela

    h = Harness(generate=gen, task=Task(goal="compara o okami com o hermes e acha bugs"), workspace=tmp_path)
    res = h.run()
    assert calls["n"] == 10                           # foi re-pedido 1x
    assert res.state.name == "COMPLETE" and "|" in (res.result or "")   # entrega final tem TABELA


def test_thin_nudge_fires_only_once(tmp_path):
    # se insistir no raso, não loopa: nudga 1x e aceita.
    for i in range(13):
        (tmp_path / f"f{i}.txt").write_text("x", encoding="utf-8")
    calls = {"n": 0}

    def gen(messages, schema):
        calls["n"] += 1
        if calls["n"] <= 13:
            return f'{{"tool": "read_file", "args": {{"path": "f{calls["n"]-1}.txt"}}}}'
        return '{"tool": "respond", "args": {"message": "curto"}}'   # sempre raso

    h = Harness(generate=gen, task=Task(goal="analisa tudo e acha bugs"), workspace=tmp_path)
    res = h.run()
    assert res.state.name == "COMPLETE" and calls["n"] <= 16   # nudga 1x, aceita o 2º (sem loop)


def _patch_running_process(monkeypatch):
    from okami.core.processes import ProcessManager       # processo bg SEMPRE 'running' (ok=True, não é falha)
    monkeypatch.setattr(ProcessManager, "poll", lambda self, pid: {"status": "running"})
    monkeypatch.setattr(ProcessManager, "log", lambda self, pid, tail=0, **k: "...rodando...")


def test_process_wait_loop_does_not_kill_turn(tmp_path, monkeypatch):
    # O CASO REAL: agente espera um processo lento (vitest do openclaw pendurou 24min). process_poll com
    # os mesmos args bate o mesmo fingerprint — ANTES isso virava "loop persistente" e MATAVA o turno sem
    # entregar. Agora ganha budget próprio + nudge p/ entregar; não FALHA.
    _patch_running_process(monkeypatch)
    calls = {"n": 0}

    def gen(messages, schema):
        calls["n"] += 1
        if calls["n"] <= 6:                               # espera o processo VÁRIAS vezes (mesma ação)
            return '{"tool": "process_poll", "args": {"id": "p1"}}'
        return ('{"tool": "respond", "args": {"message": "| item | Okami | Hermes | OpenClaw |\\n|--|--|--|--|\\n'
                '| testes | ok | ok | nao concluiu no tempo |"}}')

    h = Harness(generate=gen, task=Task(goal="rode os testes e compare"), workspace=tmp_path)
    res = h.run()
    assert res.state.name == "COMPLETE", f"esperar processo matou o turno: {res.reason!r}"
    assert "nao concluiu" in (res.result or "")           # entregou (não morreu em 'loop persistente')


def test_process_wait_budget_is_bounded(tmp_path, monkeypatch):
    # se NUNCA parar de esperar (modelo ignora o nudge), o budget de espera é finito → depois disso volta
    # a contar como loop normal e o turno encerra (não fica esperando pra sempre).
    _patch_running_process(monkeypatch)

    def gen(messages, schema):
        return '{"tool": "process_poll", "args": {"id": "p1"}}'   # só espera, pra sempre

    h = Harness(generate=gen, task=Task(goal="rode e espere"), workspace=tmp_path)
    res = h.run()
    assert res.state.name in ("FAILED", "BLOCKED")        # encerra (bounded), não loopa infinito


def test_non_poll_action_resets_wait_budget(tmp_path):
    from okami.core.harness.loop import _POLL_TOOLS
    assert "process_wait" in _POLL_TOOLS and "process_poll" in _POLL_TOOLS and "process_log" in _POLL_TOOLS


def test_failure_after_work_salvages_a_deliverable(tmp_path):
    # REDE GERAL: agente faz TRABALHO (vários passos) e depois entra em loop → ANTES morria MUDO (FAILED,
    # nada entregue). Agora o harness faz 1 chamada final pedindo a entrega PARCIAL → o usuário recebe algo.
    for i in range(6):
        (tmp_path / f"f{i}.py").write_text("x", encoding="utf-8")
    calls = {"n": 0}

    def gen(messages, schema):
        calls["n"] += 1
        # detecta o pedido de SALVAGE pelo conteúdo da última msg
        if messages and "ENTREGA final" in str(messages[-1].get("content", "")):
            return '{"tool": "respond", "args": {"message": "RELATORIO PARCIAL: achei bug X em f1.py; faltou rodar testes."}}'
        if calls["n"] <= 5:                               # 5 passos de trabalho real (read)
            return f'{{"tool": "read_file", "args": {{"path": "f{calls["n"]-1}.py"}}}}'
        return '{"tool": "spawn", "args": {"goal": "loop"}}'   # ação repetida → vira loop persistente

    h = Harness(generate=gen, task=Task(goal="analisa e ache bugs"), workspace=tmp_path)
    res = h.run()
    assert res.state.name == "FAILED"                     # honesto: não concluiu 100%
    assert "RELATORIO PARCIAL" in (res.result or "")      # MAS entregou o parcial (não morreu mudo)
    assert res.reason                                     # guarda o motivo do corte


def test_no_salvage_when_almost_no_work(tmp_path):
    # falha LOGO no começo (sem trabalho) → não há o que salvar; falha honesta e muda, sem chamada extra.
    def gen(messages, schema):
        return "sem json nenhum"                          # violação atrás de violação → FAILED cedo

    h = Harness(generate=gen, task=Task(goal="crie o arquivo x"), workspace=tmp_path)
    res = h.run()
    assert res.state.name == "FAILED" and not (res.result or "")   # nada de trabalho → nada salvo


def test_salvage_skipped_on_provider_failure(tmp_path):
    # provider morto → chamar de novo é inútil; salvage é pulado (não pendura).
    from okami.core.harness.loop import Harness as H
    h = H(generate=lambda m, s: '{"tool":"respond","args":{"message":"oi"}}',
          task=Task(goal="oi"), workspace=tmp_path)
    h.task.steps = [type("S", (), {"tool": "read_file", "effect": False})() for _ in range(5)]
    out = h._salvage(h.task, "provider falhou: timeout")
    assert out == ""                                      # pulou (reason começa com 'provider')
