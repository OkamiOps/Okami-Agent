"""Modelos do harness: TaskState · Step · Task · Budget — o estado dono do harness (§3.1)."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

Generate = Callable[[list[dict], "dict | None"], str]  # (messages, action_schema) -> texto


class TaskState(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    BLOCKED = "BLOCKED"
    NEEDS_INPUT = "NEEDS_INPUT"
    FAILED = "FAILED"


@dataclass
class Step:
    n: int
    tool: str
    args: dict
    output: str
    effect: bool
    ok: bool = True     # sucesso da tool (res.ok) — usado pelo nudge de verify-on-stop (§WIN2: achar um
    #                     run_shell bem-sucedido DEPOIS do último efeito, não só "rodou algo")


@dataclass
class Task:
    goal: str
    exit_criteria: list[dict] = field(default_factory=list)
    state: TaskState = TaskState.PENDING
    steps: list[Step] = field(default_factory=list)
    result: str | None = None
    reason: str | None = None
    stats: dict = field(default_factory=dict)   # sinais p/ reflexão (§7): violations/loops/...


@dataclass
class Budget:
    max_steps: int = 200         # passos (ações) por tarefa — alto p/ trabalho longo de verdade (review/refactor)
    max_consecutive_violations: int = 3
    # WARN-BEFORE-BLOCK (paridade Hermes agent/tool_guardrails.py warn_after/hard_stop_after): repetir a
    # MESMA ação não é mais bloqueio seco na 3ª tentativa — a 2ª repetição (warn_repeat) injeta uma
    # OBSERVAÇÃO de aviso ("você repetiu — mude a abordagem ou explique por quê") mas a tool RODA normal;
    # só bloqueia de verdade quando a repetição chega em max_repeat (default 5, como o
    # same_tool_failure_halt_after do Hermes). ABAB (cycle) continua bloqueando na hora — é um padrão
    # mais claramente patológico que uma simples repetição.
    warn_repeat: int = 2         # repetição Nº → injeta aviso (não bloqueia)
    max_repeat: int = 5          # repetição Nº → bloqueia de vez (era hard-block na 3ª; agora dá mais corda)
    stall_limit: int = 4         # passos sem efeito observável → quebra
    max_loop_breaks: int = 3     # quebras de loop antes de FAILED
    # AGREGAÇÃO unificada (paridade Hermes tool_guardrails.py:298-319 same_tool_failure_*): nome de tool
    # ALUCINADO e args FALTANDO são hoje contadores DISJUNTOS (_consecutive_violations vs
    # _consecutive_arg_fails) — cada um só zera quando o OUTRO tipo de erro acontece, então um modelo
    # que ALTERNA entre "nome errado" e "nome certo sem arg obrigatório" nunca deixa nenhum dos dois
    # isolado bater o próprio teto. Este teto SOMA as duas falhas (nesta ordem ou naquela); zera só
    # quando alguma tool de fato DISPACHA de verdade (_handle_tool_result).
    max_tool_failures: int = 6
    # ANTI-MARTELO (2026-07-08, uso real): chamar a MESMA tool dezenas de vezes numa tarefa (args mudando a
    # cada chamada → o fingerprint/anti-loop acima NÃO pega) é o padrão nº1 de "agente burro": logs reais
    # mostraram 134× execute_code (200 passos, bateu o teto), 67× move_path, 46× run_shell numa única tarefa.
    # Um agente esperto percebe cedo que travou e PARA/PERGUNTA. Nudge de consciência em warn/push (não bloqueia,
    # só faz o modelo repensar/fazer em lote); corte forçado (task_complete/blocked) em max_same_tool.
    warn_same_tool: int = 12     # Nª chamada da mesma tool → 1º nudge "isso costuma ser abordagem travada/dá lote"
    push_same_tool: int = 25     # 2º nudge mais forte
    max_same_tool: int = 40      # martelou demais → força ENTREGAR ou PERGUNTAR (raro num refactor legítimo)
    max_poll_waits: int = 8      # ESPERAS repetidas num processo em background (process_wait/poll/log) antes de
    #                              cobrar como loop — esperar um build/teste lento NÃO é loop inútil, é I/O
    max_total_turns: int = 1000  # backstop bem acima de max_steps → o limite que vale é o de passos
    max_context_chars: int = 64000  # dispara auto-compaction (§6.4). Produção SOBRESCREVE com o teto real
    #   do modelo (prov.compaction_threshold_chars); este default só vale p/ testes diretos de Harness. Subiu
    #   de 24000→64000 porque o próprio system-prompt (lista de tools) já beira 24K — a 24000 qualquer turno
    #   multi-passo disparava compaction espúria. Testes que EXIGEM compaction passam max_context_chars=24000.
    # Teto AGREGADO de tool-output do turno (Hermes: 200K chars). O teto por-resultado (8K) não
    # impede N resultados médios de inundar o contexto; estourou o agregado → outputs passam a ser
    # persistidos com preview CURTO mesmo abaixo do teto individual.
    max_turn_tool_chars: int = 200_000
    # NÃO é teto de relógio do turno (isso matava trabalho longo legítimo — review de 1M linhas, pytest de 10min).
    # É um detector de TRAVAMENTO: tempo MÁXIMO sem CONCLUIR um passo. Reseta a cada passo executado, então
    # durante atividade nunca dispara — só quando a agente fica de fato parada (provider pendurado/spinning).
    # 0 = desliga. Hang de uma chamada já tem timeout por-chamada no transporte; isto é a rede de segurança.
    max_stall_seconds: float = 300.0
    # Backstop de tokens de OUTPUT do turno (runaway de geração): protege provider POR-TOKEN (OpenAI/DeepSeek/
    # Qwen/Grok) de um turno disparado queimar orçamento. Generoso (trabalho legítimo longo não chega perto);
    # 0 = desligado. max_steps já bound o nº de chamadas; este pega o caso de poucas chamadas GIGANTES.
    max_turn_output_tokens: int = 4_000_000


# Teto de RELÓGIO p/ um LOTE de tools em paralelo (run_parallel, porta Hermes agent/tool_executor.py
# _resolve_concurrent_tool_timeout). Sem isto, UMA tool travada (ex.: run_shell sem timeout próprio,
# processo que nunca sai) segura o lote inteiro até o watchdog de 300s do TURNO — que só dispara bem
# depois e derruba o turno inteiro, não só a tool travada. 420s: folgado o bastante p/ lote de leituras
# legítimas (grep grande, N reads), curto o bastante p/ não parecer travado antes do watchdog do turno.
PARALLEL_BATCH_TIMEOUT_S: float = 420.0


# ----------------------------------------------------------------------------- protocolo
