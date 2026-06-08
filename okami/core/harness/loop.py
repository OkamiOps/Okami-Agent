"""Harness — o loop ReAct confiável: Action-or-Terminate, watchdog/stall, anti-loop, exitCriteria.

Garante, por construção e independente da LLM: estado dono do harness, ação-ou-terminal, exitCriteria
verificados, watchdog/orçamentos, anti-loop (fingerprint+ciclo+breaker), anti-alucinação (grounding).
"""
from __future__ import annotations

import json
import re as _re
from collections import deque
from pathlib import Path
from typing import Callable

from okami.core import approval
from okami.core.harness.models import Budget, Generate, Step, Task, TaskState
from okami.core.harness.parsing import (
    FUTURE_INTENT, _ACTION_RE, Action, _action_from_tool_calls, _actions_from_tool_calls, action_schema,
    parse_action, parse_actions, prose_outside_action,
)
from okami.core.harness.prompt import (
    _TOOL_RESULT_BUDGET, _user_start, build_system_prompt, check_exit, format_observation,
    is_conversational,
)
from okami.core.tools import Tool, ToolContext, ToolResult, default_registry
from okami.llm.usage import as_completion
from okami.memory import compaction as _compaction


# BAIL: encerrar pedindo permissão / oferecendo um menu de próximos passos em vez de CONCLUIR. É o modo
# de falha clássico do modelo fraco ("Responde com 1 ou 2 que eu sigo", "quer que eu já aplique…?",
# "Posso seguir?"). Pego só os padrões DISTINTIVOS — não casa um relatório que de fato entregou.
_PUNT_RE = _re.compile(
    r"(respond[ae]\s+com\s+\d|manda\s+\d|\b\d\s*,?\s*(\d\s*,?\s*)*ou\s+\d\b|\bop[cç][ãa]o\s+\d\b|"
    r"\bposso\s+(seguir|continuar|prosseguir|ir|avan[çc]ar)\b|\bquer\s+que\s+eu\b|"
    r"\bprefere\b[^.\n]{0,40}\b(que\s+eu|avaliar|primeiro)\b|me\s+(diga|avisa|fala)\s+(se|qual|por\s+onde)|"
    r"por\s+onde\s+(voc[êe]\s+)?(quer|prefere)|\b(should|shall)\s+i\b|\bwant\s+me\s+to\b|"
    r"do\s+you\s+want\s+me\s+to|\blet\s+me\s+know\s+(if|whether|which)\b)", _re.I)


def _looks_like_punt(text: str) -> bool:
    """O texto final ENCERRA pedindo permissão / oferecendo menu de próximos passos (bail do modelo fraco)?"""
    return bool(_PUNT_RE.search(text or ""))


_REPORT_META = {"respond", "task_complete", "task_blocked", "need_input"}
_POLL_TOOLS = {"process_wait", "process_poll", "process_log"}   # ESPERAR processo ≠ loop inútil (é I/O)
_BATCHABLE_READONLY = {"read_file", "list_dir", "find_files"}   # leitura pura → seguro rodar em LOTE


def _is_batchable(action: Action) -> bool:
    """Ação SEGURA de rodar em lote: leitura pura (sem efeito, sem aprovação, não-terminal). run_shell só
    se for read-only (grep/cat/ls — shell_has_effect False). Tudo que muta/encerra/pede aprovação fica fora."""
    if action.tool in _BATCHABLE_READONLY:
        return True
    if action.tool == "run_shell":
        from okami.core.tools.base import shell_has_effect
        return not shell_has_effect(str(action.args.get("cmd", "")))
    return False


def _lead_readonly(actions: list[Action], first: Action | None) -> list[Action]:
    """A sequência LÍDER de leituras seguras (batchable), deduplicada (inclusive vs a 1ª ação). PARA na
    primeira ação que mute/encerre/peça aprovação — essa e as seguintes re-geram normalmente (1-por-turno)."""
    def _fp(a: Action) -> str:
        return f"{a.tool}:{json.dumps(a.args, sort_keys=True, ensure_ascii=False)}"
    seen = {_fp(first)} if first is not None else set()
    out: list[Action] = []
    for a in actions:
        if not _is_batchable(a):
            break
        if _fp(a) in seen:
            continue
        seen.add(_fp(a))
        out.append(a)
    return out

# Aliases comuns de nome de tool ALUCINADO (modelo fraco erra o nome) → nome real. Hermes _repair_tool_call.
_TOOL_ALIASES = {
    "read": "read_file", "readfile": "read_file", "cat": "read_file", "open": "read_file", "view": "read_file",
    "write": "write_file", "writefile": "write_file", "save": "write_file", "create_file": "write_file",
    "edit": "edit_file", "editfile": "edit_file", "patch": "edit_file", "replace": "edit_file",
    "ls": "list_dir", "listdir": "list_dir", "list": "list_dir", "dir": "list_dir",
    "find": "find_files", "search": "find_files", "grep": "find_files", "glob": "find_files",
    "search_files": "find_files", "find_file": "find_files",
    "shell": "run_shell", "bash": "run_shell", "sh": "run_shell", "exec": "run_shell", "terminal": "run_shell",
    "run": "run_shell", "command": "run_shell", "execute": "run_shell",
    "complete": "task_complete", "done": "task_complete", "finish": "task_complete", "answer": "respond",
    "reply": "respond", "message": "respond", "say": "respond", "blocked": "task_blocked",
    "ask": "need_input", "question": "need_input", "memory": "remember", "recall": "recall_memory",
}


def _repair_tool_name(name: str, registry: dict) -> str | None:
    """Nome de tool ALUCINADO (modelo fraco erra) → nome REAL, se houver correspondência confiável.
    Hermes repara antes de tratar como erro. Ordem: alias conhecido → match por prefixo/substring → fuzzy."""
    if not name:
        return None
    low = name.strip().lower()
    if low in registry:
        return low
    if _TOOL_ALIASES.get(low) in registry:
        return _TOOL_ALIASES[low]
    keys = list(registry)
    for k in keys:                                      # 'read'→'read_file', 'process'→? (só se único)
        if k.startswith(low) or low.startswith(k):
            return k
    import difflib
    hit = difflib.get_close_matches(low, keys, n=1, cutoff=0.82)   # typo: 'raed_file'→'read_file'
    return hit[0] if hit else None


def _deliverable_too_thin(goal: str, msg: str, real_steps: int) -> bool:
    """A entrega ficou RASA pro que foi pedido? (1) pediu COMPARAÇÃO e não veio TABELA; (2) muito trabalho
    (≥12 passos) e resposta curta (<1000 chars). O harness re-pede o relatório COMPLETO — modelo fraco
    tende a fazer o trabalho e resumir num parágrafo. NÃO confunde papo curto: exige trabalho substancial."""
    g, m = (goal or "").lower(), msg or ""
    if any(k in g for k in ("compar", "comparativo", " vs ", "versus")) and real_steps >= 6 and m.count("|") < 4:
        return True                                   # comparação pedida + trabalho feito, mas SEM tabela
    if real_steps >= 8 and len(m) > 1200 and "##" not in m and m.count("|") < 4:
        return True                                   # PAREDÃO: relatório longo sem seção (##) nem tabela
    return real_steps >= 12 and len(m) < 1000         # trabalho grande, entrega curta


_THIN_NUDGE = (
    "Você fez bastante trabalho ({n} passos) mas a entrega ficou CURTA/rasa e/ou em parágrafo corrido. "
    "REESCREVA AGORA em MARKDOWN ESTRUTURADO (a TUI renderiza tabela/seção/cor), preenchendo este esqueleto "
    "com o REAL:\n\n## <título>\n### Resumo\n<2-3 linhas>\n### Testes rodados\n| suíte | passou | falhou |\n"
    "|---|---|---|\n### Comparação\n| aspecto | Okami | Hermes | OpenClaw |\n|---|---|---|---|\n"
    "### Achados (arquivo:linha)\n- **<achado>** (`arquivo:linha`) — <porquê>\n\nUse TUDO que levantou; "
    "liste as falhas reais (não só 'X/Y'). PROIBIDO parágrafo corrido sem seções/tabela.")


class Harness:
    def __init__(
        self,
        generate: Generate,
        task: Task,
        workspace: Path,
        registry: dict[str, Tool] | None = None,
        budget: Budget | None = None,
        on_event: Callable[[dict], None] | None = None,
        escalate: Generate | None = None,
        system_extra: str = "",
        memory=None,
        core_block: str = "",
        approve: Callable[[dict], bool] | None = None,
        skills: dict | None = None,
        cancel: Callable[[], bool] | None = None,
        checkpoints=None,
        hooks=None,
        spawn=None,
        images=None,
        prelearned_files=None,
        sandbox=None,
        skills_dir=None,
    ):
        self.images = images or []      # caminhos/URLs de imagens (vision §6) — exige modelo multimodal
        self.generate = generate
        self.escalate = escalate  # gerador de modelo mais forte (§3.5 cascata)
        # go/no-go (§12) FAIL-CLOSED: sem approver explícito, ação sensível é NEGADA (não auto-OK).
        # Sem humano (cron/spawn/lib) → bloqueia e instrui o modelo a achar alternativa. Auto-aprovar
        # exige passar approve explícito (ex.: yolo do gateway). Não-sensível roda normal (não chama isto).
        self.approve = approve if approve is not None else (lambda req: False)
        self.cancel = cancel or (lambda: False)       # /stop do gateway (§13)
        self.system_extra = system_extra  # skills forçadas / sections (§4.2, §8)
        self.core_block = core_block      # .md sempre injetados: AGENTS/USER/MEMORY (§6 tier core)
        self.memory = memory  # backend de memória (§6) — opcional
        self.task = task
        self.registry = registry or default_registry()
        self.budget = budget or Budget()
        self.hooks = hooks                 # event hooks (§11): before_tool pode VETAR
        self.ctx = ToolContext(workspace=workspace, memory=memory, skills=skills or {},
                               checkpoints=checkpoints, spawn=spawn, sandbox=sandbox, skills_dir=skills_dir)
        # Arquivos já "conhecidos" (ex.: stubs de identidade na gênese): podem ser sobrescritos sem
        # exigir read antes — o grounding anti-alucinação não faz sentido p/ placeholders que NÓS criamos.
        self.ctx.read_files.update(prelearned_files or [])
        self.on_event = on_event or (lambda e: None)
        import secrets
        from okami.observability.events import EventLog
        # trace_id por turno (P2): amarra todos os eventos desta execução no timeline (replay/debug)
        self.events = EventLog(workspace, trace_id=secrets.token_hex(4))
        self.messages: list[dict] = []
        self._action_schema = action_schema(self.registry)
        self._fingerprints: deque[str] = deque(maxlen=12)
        self._failures: dict[str, int] = {}
        self._consecutive_violations = 0
        self._steps_without_effect = 0
        self._loop_breaks = 0
        self._escalated = False
        self._stats = {"violations": 0, "loops": 0, "gate_rejections": 0, "denials": 0}
        # backstop anti-preguiça (modelo fraco): pedido com verbo de ação exige EXECUTAR, não só falar
        self._action_expected = bool(_ACTION_RE.search(task.goal or ""))
        self._nudged_action = False
        self._empty_nudged = False                     # respondeu VAZIO → re-pede a resposta de verdade (1x)
        self._punt_nudged = False                      # encerrou pedindo permissão/menu → empurra a concluir (1x)
        self._thin_nudged = False                      # entrega rasa vs trabalho feito → re-pede o relatório (1x)
        self._poll_waits = 0                           # esperas repetidas num processo bg (não é loop de FAIL)
        self._salvaged = False                         # já tentou a entrega-parcial antes de falhar? (1x)
        self._batch: list[Action] = []                 # leituras restantes da MESMA geração (batch — Hermes)
        self._truncated_parts: list[str] = []          # length-continuation (Hermes): partes de resposta cortada
        self._MAX_LENGTH_CONT = 6                      # teto de continuações por entrega (anti-loop)

    def _emit(self, kind: str, **data):
        self.on_event({"kind": kind, **data})
        self.events.emit(kind, **data)      # persiste o timeline (start/step/loop/compact/complete/…)

    # --- audit + budget de resultado de tool (Sprint 2) ---------------------
    def _audit(self, **fields) -> None:
        """Trilha append-only de TODA tool + decisão de aprovação (.okami/audit.jsonl). Best-effort."""
        try:
            import time as _t
            from okami.core.redact import redact
            d = self.ctx.workspace / ".okami"
            d.mkdir(parents=True, exist_ok=True)
            line = json.dumps({"ts": _t.time(), **fields}, ensure_ascii=False, default=str)
            with (d / "audit.jsonl").open("a", encoding="utf-8") as f:
                f.write(redact(line) + "\n")        # mascara segredos na trilha de auditoria
        except Exception:  # noqa: BLE001 — auditoria nunca derruba o turno
            pass

    @staticmethod
    def _args_brief(args: dict) -> str:
        """Resumo curto e NÃO-sensível dos args p/ o audit (path/cmd/query — nunca o content inteiro)."""
        if not isinstance(args, dict):
            return ""
        for k in ("path", "cmd", "query", "url", "name", "goal"):
            v = args.get(k)
            if isinstance(v, str) and v:
                return f"{k}={v[:120]}"
        return ""

    def _persist_large_output(self, step_n: int, text: str) -> str:
        """Output grande → .okami/tool_outputs/step_<n>.txt; devolve o caminho relativo p/ referência."""
        try:
            from okami.core.redact import redact
            d = self.ctx.workspace / ".okami" / "tool_outputs"
            d.mkdir(parents=True, exist_ok=True)
            p = d / f"step_{step_n}.txt"
            p.write_text(redact(text), encoding="utf-8")   # output grande pode ter segredo → mascara
            return str(p.relative_to(self.ctx.workspace))
        except Exception:  # noqa: BLE001
            return "(falha ao persistir)"

    @staticmethod
    def _fingerprint(action: Action) -> str:
        return f"{action.tool}:{json.dumps(action.args, sort_keys=True, ensure_ascii=False)}"

    def run(self) -> Task:
        t = self.task
        t.state = TaskState.IN_PROGRESS
        t.stats = self._stats  # acumulado por referência → usado na reflexão/auto-aprimoramento (§7)
        # Context Engine (§P2 #9): UMA camada decide o contexto, com orçamento e citação de origem.
        # Identidade/core é PROTEGIDA (nunca truncada); memória/skills cabem no que sobra. Ordem
        # preservada (core → memória → skills) → sob tamanhos normais a saída é idêntica à de antes.
        from okami.core.context import ContextEngine
        eng = ContextEngine(budget_chars=self.budget.max_context_chars)
        eng.add("core", self.core_block, protected=True)        # SOUL/VOICE/PERSONA + AGENTS/USER/MEMORY
        if self.memory is not None:
            eng.add("memory", self.memory.inject(t.goal))       # recall já vem citado (#11)
        eng.add("skills", self.system_extra)
        extra, _ctx_manifest = eng.build()
        self.events.emit("context", sections=_ctx_manifest,
                         total_chars=sum(m["chars"] for m in _ctx_manifest))
        # Em CONVERSA a fala da pessoa é o turno do usuário (não um "Comece." sintético → mata o
        # "Comecei." de execução de tarefa). Em TRABALHO o objetivo já está no system prompt.
        first = _user_start(self.images, text=t.goal) if is_conversational(t) else _user_start(self.images)
        self.messages = [
            {"role": "system", "content": build_system_prompt(t, self.registry, extra,
                                                              workspace=self.ctx.workspace)},
            {"role": "user", "content": first},
        ]
        self._emit("start", goal=t.goal)

        step_n = 0
        turns = 0
        import time as _wt
        # NÃO é teto de relógio (matava trabalho longo). É anti-TRAVAMENTO: mede o tempo desde o ÚLTIMO
        # passo concluído. Reseta a cada passo (ver `_last_progress = …` abaixo) → durante atividade nunca
        # dispara; só quando a agente fica parada de verdade. 0 = desliga (confia no timeout por-chamada).
        _last_progress = _wt.monotonic()
        self._shrunk_retry = False                        # recuperação por encolhimento: 1x por episódio de falha
        while True:
            turns += 1
            _stall = self.budget.max_stall_seconds
            if _stall > 0 and _wt.monotonic() - _last_progress > _stall:   # travou (sem concluir passo) → para LIMPO
                t.state = TaskState.BLOCKED
                t.reason = (f"travei: ~{int(_wt.monotonic() - _last_progress)}s sem concluir nenhum passo "
                            "(provável travamento, não trabalho — durante atividade eu não paro). Tenta de novo "
                            "que eu sigo.")
                # ENTREGA PARCIAL antes de desistir mudo (mesmo no stall): a última geração pendurou (=
                # contexto grande), então COMPACTA forte e tenta UMA vez entregar o que já levantou. Best-
                # effort com timeout por-chamada: se pendurar/falhar de novo, fica só o BLOCKED seco.
                try:
                    self.messages, _pr = _compaction.compact(self.messages, self.memory, keep_tail=4)
                except Exception:  # noqa: BLE001
                    pass
                _sv = self._salvage(t, t.reason)
                if _sv:
                    t.result = _sv
                    self._emit("salvaged", reason="stall", chars=len(_sv))
                self._emit("blocked", reason=t.reason)
                return t
            if turns > self.budget.max_total_turns:
                return self._fail(t, "backstop de turnos do harness atingido")
            if step_n >= self.budget.max_steps:
                return self._fail(t, f"orçamento de {self.budget.max_steps} passos esgotado")
            if self.cancel():                        # /stop do usuário (§13)
                t.state = TaskState.BLOCKED
                t.reason = "cancelado pelo usuário (/stop)"
                self._emit("cancelled")
                return t
            # Auto-compaction (§6.4): promove à memória + ponteiro, antes de comprimir.
            if _compaction.estimate_chars(self.messages) > self.budget.max_context_chars:
                self.messages, promoted = _compaction.compact(self.messages, self.memory)
                self._emit("compact", promoted=promoted)
            # LOTE (batch — Hermes roda VÁRIAS por turno): se sobraram LEITURAS da mesma geração, roda a
            # próxima SEM nova chamada ao modelo — corta os round-trips (o gargalo de velocidade vs Hermes).
            # Só leitura entra no lote; ação que muta/encerra/pede aprovação segue 1-por-turno.
            if self._batch:
                action = self._batch.pop(0)
                text = ""
            else:
                _g0 = _wt.monotonic()                  # cronômetro da geração → torna o gargalo VISÍVEL
                try:
                    out = self.generate(self.messages, self._action_schema)
                except Exception as e:  # noqa: BLE001 — transporte esgotou retry/failover do provider
                    from okami.core.errors import Action as _Act
                    from okami.core.errors import classify_provider
                    fail = classify_provider(e)
                    self.events.emit("failure", scope="generate", kind=fail.kind.value,
                                     action=fail.action.value, reason=fail.reason, status=fail.status)
                    # RECUPERAÇÃO 1ª: timeout/lento ≈ CONTEXTO GRANDE. ENCOLHE forte (keep_tail=3) e re-gera 1x —
                    # chamada menor = mais rápida, cabe até no fallback local. Antes só escalava p/ modelo mais
                    # forte com o MESMO contexto gigante → pendurava de novo e morria.
                    if fail.action in (_Act.RETRY, _Act.ESCALATE) and not self._shrunk_retry:
                        self._shrunk_retry = True
                        before = _compaction.estimate_chars(self.messages)
                        self.messages, promoted = _compaction.compact(self.messages, self.memory, keep_tail=3)
                        if _compaction.estimate_chars(self.messages) < before:
                            self._emit("compact", promoted=promoted)
                            continue              # re-gera com contexto MENOR (mais rápido, sem trocar modelo)
                    # RECUPERAÇÃO 2ª: escala p/ modelo mais forte (resiliência, não crash)
                    if fail.action in (_Act.RETRY, _Act.ESCALATE) and self._try_escalate(f"provider: {fail.reason}"):
                        continue
                    return self._fail(t, f"provider falhou: {fail.reason}")
                comp = as_completion(out)          # tolera str (JSON-em-texto) E Completion (nativo)
                self._shrunk_retry = False         # gerou com sucesso → libera novo encolhimento p/ falha futura
                _u = comp.usage                     # usage POR CHAMADA no trajeto (P2 observabilidade)
                self.events.emit("llm_call", provider=comp.provider, model=comp.model,
                                 finish_reason=getattr(comp, "finish_reason", ""),
                                 tokens_in=getattr(_u, "input_tokens", 0),
                                 tokens_out=getattr(_u, "output_tokens", 0),
                                 cache=getattr(_u, "cache_read_tokens", 0),
                                 tool_call=bool(comp.tool_calls),
                                 secs=round(_wt.monotonic() - _g0, 1))   # quanto a CHAMADA demorou
                self.messages.append({"role": "assistant", "content": comp.text})

                # LENGTH-CONTINUATION (Hermes): resposta CORTADA pelo limite (finish_reason='length') →
                # continua EXATAMENTE de onde parou e CONCATENA, em vez de aceitar a entrega pela metade.
                if getattr(comp, "finish_reason", "") == "length" and len(self._truncated_parts) < self._MAX_LENGTH_CONT:
                    self._truncated_parts.append(comp.text)
                    self._emit("length_continue", part=len(self._truncated_parts))
                    self.messages.append({"role": "user", "content":
                        "[Sua resposta foi CORTADA pelo limite de tamanho. Continue EXATAMENTE de onde parou, "
                        "SEM repetir o que já escreveu, e TERMINE a entrega. Se estava no meio do bloco json de "
                        "ação, complete-o.]"})
                    continue
                text = "".join(self._truncated_parts) + comp.text if self._truncated_parts else comp.text
                self._truncated_parts = []             # episódio de truncamento fechado → texto completo
                _acts = _actions_from_tool_calls(comp.tool_calls) or parse_actions(text)
                action = _acts[0] if _acts else None
                self._batch = _lead_readonly(_acts[1:], action)   # resto = leituras seguras → rodam sem nova call

            # --- Reparo de nome de tool ALUCINADO (Hermes): 'read'→'read_file' etc. antes de violar ---
            if action is not None and action.tool not in self.registry:
                _fix = _repair_tool_name(action.tool, self.registry)
                if _fix:
                    self._emit("tool_repaired", **{"from": action.tool, "to": _fix})
                    action = Action(_fix, action.args)

            # --- Action-or-Terminate (§3.2) ---
            if action is None or action.tool not in self.registry:
                # CONVERSA: o modelo só FALOU (prosa, sem envelope JSON) e não havia nada a executar
                # → isso É a resposta dele. Não rejeita nem mostra "emita JSON" (seria UX de robô num
                # papo). Só vale em conversa pura, sem ação pedida e sem tentativa de tool malformada.
                if (action is None and is_conversational(t) and not self._action_expected
                        and not FUTURE_INTENT.search(text)  # promessa "vou fazer" NÃO é resposta
                        and '"tool"' not in text and len(text.strip()) >= 2):
                    t.state = TaskState.COMPLETE
                    t.result = text.strip()
                    self._emit("complete", summary=t.result)
                    return t
                self._consecutive_violations += 1
                self._stats["violations"] += 1
                hint = ""
                if action is None and FUTURE_INTENT.search(text):
                    hint = " Você descreveu intenção em vez de agir."
                elif action is not None:                   # nome de tool ALUCINADO e sem reparo → diz quais existem
                    hint = (f" '{action.tool}' não existe. Ferramentas REAIS: "
                            f"{', '.join(sorted(self.registry))}.")
                self._emit("violation", n=self._consecutive_violations, text=text[:200])
                if self._consecutive_violations >= self.budget.max_consecutive_violations:
                    if self._try_escalate("violações de Action-or-Terminate"):
                        continue
                    return self._fail(t, "violações repetidas de Action-or-Terminate")
                self.messages.append({"role": "user", "content":
                    f"REJEITADO: nenhuma ação válida.{hint} Emita UM bloco ```json "
                    f'{{"tool": "...", "args": {{...}}}}``` agora — ou task_blocked.'})
                continue
            self._consecutive_violations = 0

            # --- Anti-loop (§3.6) ---
            fp = self._fingerprint(action)
            repeats = self._fingerprints.count(fp)
            cycle = (len(self._fingerprints) >= 4
                     and self._fingerprints[-1] == self._fingerprints[-3]
                     and self._fingerprints[-2] == self._fingerprints[-4])
            if repeats >= self.budget.max_repeat - 1 or cycle:
                self._batch = []                          # repetiu → descarta o resto do lote, re-planeja limpo
                self._emit("loop", fingerprint=fp, repeats=repeats + 1, cycle=cycle)
                # ESPERAR um processo em background (build/teste lento, server) NÃO é loop inútil — é I/O.
                # process_wait/poll/log com os mesmos args batem o mesmo fingerprint e matavam o turno
                # INTEIRO sem entregar nada (o caso do vitest do openclaw que pendurou 24min). Aqui ganham
                # um budget PRÓPRIO e um nudge p/ ENTREGAR/seguir — só viram loop-de-verdade depois disso.
                if action.tool in _POLL_TOOLS and self._poll_waits < self.budget.max_poll_waits:
                    self._poll_waits += 1
                    self.messages.append({"role": "user", "content":
                        "Esse processo está DEMORANDO. NÃO fique só esperando (process_wait/poll): ou mate "
                        "com process_kill e SIGA, ou ENTREGUE o relatório com o que já tem (marque esse "
                        "processo como 'não concluiu no tempo'). Os outros resultados já valem a entrega."})
                    self._fingerprints.append(fp)
                    continue
                self._loop_breaks += 1
                self._stats["loops"] += 1
                if self._loop_breaks >= self.budget.max_loop_breaks:
                    if self._try_escalate("loop persistente"):
                        continue
                    return self._fail(t, "loop persistente de tool-calling")
                self.messages.append({"role": "user", "content":
                    "LOOP DETECTADO: você já repetiu essa ação. NÃO repita — faça algo "
                    "diferente ou declare task_blocked com a razão."})
                self._fingerprints.append(fp)
                continue

            tool = self.registry[action.tool]

            # --- Tools terminais ---
            if tool.terminal:
                # RECUPERA a fala perdida: modelo fraco escreve a resposta em PROSA e manda respond/
                # task_complete com message/summary VAZIO → usa a prosa (fora do JSON) em vez de virar
                # '(COMPLETE)' mudo. (Era o bug de "pergunta o nome → só completed".)
                if action.tool in ("respond", "task_complete"):
                    _key = "message" if action.tool == "respond" else "summary"
                    if not str(action.args.get(_key, "")).strip():
                        _prose = prose_outside_action(text)   # `text` = concatenação (length-continuation)
                        if len(_prose) >= 2:
                            action.args[_key] = _prose
                result = self._handle_terminal(t, action)
                if result is not None:
                    return result
                continue  # task_complete rejeitado → segue

            # --- Validação de args: ação malformada NÃO quebra o harness, vira re-prompt ---
            missing = [a for a in tool.required if a not in action.args]
            if missing:
                self._stats["violations"] += 1
                self._fingerprints.append(fp)
                self.messages.append({"role": "user", "content":
                    f"Ação '{action.tool}' sem argumento(s) obrigatório(s): {missing}. Reenvie completa."})
                continue

            # --- Go/No-Go para ação sensível (§12): identidade, .env, segredos, shell destrutivo ---
            sens = approval.classify(action.tool, action.args)
            if sens is None:                                  # #8/#11: tool MCP de terceiro — manifesto/trust store
                _t = self.registry.get(action.tool)
                _caps = getattr(_t, "capabilities", None) or set()
                _pol = getattr(_t, "approval_policy", "auto")
                _dang = _caps & {"write", "shell", "network", "secret-access", "external-side-effect"}
                if _pol == "always":                          # manifesto exige aprovação explícita
                    sens = approval.Sensitive(f"MCP {action.tool}: aprovação exigida no manifesto", "mcp_manifest", "high")
                elif _pol == "never" or getattr(_t, "trusted", False):
                    pass                                      # liberada no manifesto / servidor confiável
                elif getattr(_t, "unverified", False):        # #11: untrusted sem manifesto → não confia no nome
                    sens = approval.Sensitive(
                        f"MCP {action.tool}: tool não revisada (capabilities não declaradas)", "mcp_unverified", "medium")
                elif _dang:
                    _risk = "high" if (_caps & {"shell", "secret-access"}) else "medium"
                    sens = approval.Sensitive(f"MCP {action.tool} ({', '.join(sorted(_caps))})", "mcp_capability", _risk)
            if sens is not None:
                self._emit("approval_request", tool=action.tool, reason=sens.reason, category=sens.category)
                args_hash = approval.args_hash(action.args)   # amarra a aprovação aos ARGS EXATOS (#1/#7/#9)
                req = {"tool": action.tool, "args": action.args, "args_hash": args_hash,
                       "reason": sens.reason, "category": sens.category, "risk": sens.risk}
                approved = self.approve(req)
                self._audit(event="approval", tool=action.tool, args_hash=args_hash, category=sens.category,
                            risk=sens.risk, args=self._args_brief(action.args),
                            decision="allow" if approved else "deny")
                if not approved:
                    self._stats["denials"] += 1
                    self._fingerprints.append(fp)
                    step_n += 1
                    _last_progress = _wt.monotonic()      # passo concluído (mesmo negado) = atividade → reseta o anti-travamento
                    t.steps.append(Step(step_n, action.tool, action.args, "negado (go/no-go)", False))
                    self._emit("step", n=step_n, tool=action.tool, args=action.args, ok=False, effect=False)
                    self.messages.append({"role": "user", "content":
                        f"AÇÃO NEGADA (go/no-go): o usuário recusou — {sens.reason}. Proponha "
                        "alternativa, peça confirmação com outra abordagem, ou declare task_blocked."})
                    continue

            # --- Hook before_tool (§11): política externa pode VETAR a tool ---
            if self.hooks is not None and not self.hooks.fire(
                    "before_tool", {"tool": action.tool, "args": action.args}):
                step_n += 1
                _last_progress = _wt.monotonic()          # passo concluído (vetado) = atividade → reseta o anti-travamento
                t.steps.append(Step(step_n, action.tool, action.args, "vetado por hook", False))
                self._emit("step", n=step_n, tool=action.tool, args=action.args, ok=False, effect=False)
                self.messages.append({"role": "user", "content":
                    f"AÇÃO BLOQUEADA por um hook de política: '{action.tool}'. Tente outra "
                    "abordagem ou declare task_blocked."})
                continue

            # --- Tool normal ---
            self._fingerprints.append(fp)
            try:
                res = tool.run(action.args, self.ctx)
            except Exception as e:  # noqa: BLE001 — uma tool NUNCA derruba o harness
                res = ToolResult(False, f"erro na tool {action.tool}: {e}")
            step_n += 1
            _last_progress = _wt.monotonic()              # passo executado = ATIVIDADE → reseta o anti-travamento (trabalho longo nunca expira)
            t.steps.append(Step(step_n, action.tool, action.args, res.output, res.effect))
            self._emit("step", n=step_n, tool=action.tool, args=action.args, ok=res.ok, effect=res.effect)
            if action.tool not in _POLL_TOOLS:            # fez algo ≠ esperar processo → zera o budget de espera
                self._poll_waits = 0
            self._audit(event="tool", step=step_n, tool=action.tool, args=self._args_brief(action.args),
                        ok=res.ok, effect=res.effect, out_chars=len(res.output))
            if self.hooks is not None:
                self.hooks.fire("after_tool", {"tool": action.tool, "ok": res.ok, "effect": res.effect})

            # circuit breaker de falha repetida
            if not res.ok:
                from okami.core.errors import FailureKind, classify_tool
                fail = classify_tool(res)
                self.events.emit("failure", scope="tool", tool=action.tool, kind=fail.kind.value,
                                 action=fail.action.value, reason=fail.reason)
                key = f"{action.tool}:{res.output[:60]}"
                self._failures[key] = self._failures.get(key, 0) + 1
                # determinístico (sandbox/bad_request) NÃO melhora repetindo → corta logo; senão, 3x.
                deterministic = fail.kind in (FailureKind.SANDBOX_DENY, FailureKind.BAD_REQUEST)
                if deterministic or self._failures[key] >= 3:
                    why = ("BLOQUEADO (determinístico/sandbox): repetir não resolve."
                           if deterministic else
                           "CIRCUIT BREAKER: essa abordagem falhou 3x com o mesmo erro.")
                    self.messages.append({"role": "user", "content":
                        f"{why} Mude de estratégia ou declare task_blocked."})

            # watchdog / stall (§3.3)
            self._steps_without_effect = 0 if res.effect else self._steps_without_effect + 1
            if self._steps_without_effect >= self.budget.stall_limit:
                self._emit("stall", steps=self._steps_without_effect)
                self.messages.append({"role": "user", "content":
                    "SEM PROGRESSO: vários passos sem efeito observável. Tome uma ação "
                    "concreta (escreva/rode algo) ou declare task_blocked."})
                self._steps_without_effect = 0

            obs_res = res                                # budget de contexto: trunca output gigante (persiste o completo)
            if len(res.output) > _TOOL_RESULT_BUDGET:
                saved = self._persist_large_output(step_n, res.output)
                obs_res = ToolResult(res.ok, res.output[:_TOOL_RESULT_BUDGET]
                                     + f"\n\n[… truncado: {len(res.output)} chars no total; "
                                       f"completo em {saved} (use read_file p/ ver mais) …]", res.effect)
            self.messages.append({"role": "user", "content": format_observation(step_n, action.tool, obs_res)})

        return self._fail(t, f"orçamento de {self.budget.max_steps} passos esgotado")

    def _handle_terminal(self, t: Task, action: Action) -> Task | None:
        if action.tool == "respond":                     # FALA com o usuário (ReAct: ramo "texto")
            # backstop: pediram AÇÃO mas ele FALOU sem rodar NENHUMA ferramenta (puro papo de memória) →
            # re-prompt 1x. Conta passo read-only (list/read) como "olhou": tarefa de análise não exige
            # EFEITO, exige ter LIDO o que precisa antes de responder (senão era 'not any(effect)' barrando
            # todo relatório de análise — falso-positivo).
            if self._action_expected and not self._nudged_action and not t.steps:
                self._nudged_action = True
                self._emit("violation", n=0, text="respondeu sem rodar nenhuma ferramenta")
                self.messages.append({"role": "user", "content":
                    "Você respondeu SEM usar nenhuma ferramenta. O pedido exige agir de verdade: leia/liste/"
                    "rode o que for preciso (read_file, list_dir, find_files, run_shell) e ENTREGUE o "
                    "resultado real — não responda de memória."})
                return None
            msg = (action.args.get("message") or action.args.get("summary") or "").strip()
            if not msg and not self._empty_nudged:       # respondeu VAZIO (nem prosa) → pede a resposta 1x
                self._empty_nudged = True
                self._emit("violation", n=0, text="respondeu vazio")
                self.messages.append({"role": "user", "content":
                    'Sua resposta veio VAZIA. Responda o usuário de verdade no campo message: '
                    '{"tool": "respond", "args": {"message": "<sua resposta aqui>"}}.'})
                return None
            # backstop anti-BAIL (modelo fraco): pediram AÇÃO e ele ENCERROU pedindo permissão / oferecendo
            # menu ("responde 1 ou 2", "quer que eu…?", "posso seguir?") em vez de concluir → empurra 1x.
            if self._action_expected and not self._punt_nudged and _looks_like_punt(msg):
                self._punt_nudged = True
                self._emit("violation", n=0, text="bail: pediu permissão/menu em vez de concluir")
                self.messages.append({"role": "user", "content":
                    "Você ENCERROU pedindo permissão/menu ('1 ou 2', 'quer que eu…?', 'posso seguir?') em "
                    "vez de CONCLUIR. Para próximos passos SEGUROS (ler/rodar/analisar/progredir) não peça "
                    "permissão — faça e entregue o resultado COMPLETO. Ação destrutiva/sensível segue "
                    "passando pela aprovação normal (chame a ferramenta, NÃO force). Se falta um dado que "
                    "SÓ a pessoa tem, use need_input com UMA pergunta específica."})
                return None
            # backstop anti-RASO (modelo fraco faz o trabalho e RESUME): fez muito passo mas a entrega
            # ficou curta / sem tabela na comparação → re-pede o relatório COMPLETO 1x (estrutural, força).
            _real = len([s for s in t.steps if s.tool not in _REPORT_META])
            if (self._action_expected and not self._thin_nudged
                    and _deliverable_too_thin(t.goal, msg, _real)):
                self._thin_nudged = True
                self._emit("violation", n=0, text="entrega rasa vs trabalho feito")
                self.messages.append({"role": "user", "content": _THIN_NUDGE.format(n=_real)})
                return None
            t.state = TaskState.COMPLETE
            t.result = msg or "(sem resposta)"
            self._emit("complete", summary=t.result)     # sem _extract: conversa não polui a memória
            return t
        if action.tool == "task_blocked":
            t.state = TaskState.BLOCKED
            t.reason = action.args.get("reason", "(sem razão)")
            self._emit("blocked", reason=t.reason)
            return t
        if action.tool == "need_input":
            t.state = TaskState.NEEDS_INPUT
            t.reason = action.args.get("question", "(sem pergunta)")
            self._emit("need_input", question=t.reason)
            return t
        if action.tool == "task_complete":
            ok, missing = check_exit(t.exit_criteria, self.ctx)
            if ok:
                _summary = str(action.args.get("summary", "")).strip()
                _real = len([s for s in t.steps if s.tool not in _REPORT_META])
                if (self._action_expected and not self._thin_nudged
                        and _deliverable_too_thin(t.goal, _summary, _real)):   # entrega rasa → re-pede 1x
                    self._thin_nudged = True
                    self._emit("complete_rejected", missing=["entrega rasa vs trabalho feito"])
                    self.messages.append({"role": "user", "content": _THIN_NUDGE.format(n=_real)})
                    return None
                t.state = TaskState.COMPLETE
                t.result = _summary or "(sem resumo)"
                self._extract_on_complete(t)
                self._emit("complete", summary=t.result)
                return t
            # rejeitado: 'concluído' falso (§3.4)
            self._stats["gate_rejections"] += 1
            self._emit("complete_rejected", missing=missing)
            self.messages.append({"role": "user", "content":
                "task_complete REJEITADO — critérios de saída não satisfeitos:\n"
                + "\n".join(f"  - {m}" for m in missing)
                + "\nContinue trabalhando para satisfazê-los."})
            return None
        return None  # não deveria acontecer

    def _try_escalate(self, why: str) -> bool:
        """Cascata (§3.5): troca para o modelo mais forte uma vez antes de falhar."""
        if not self.escalate or self._escalated:
            return False
        self._escalated = True
        self.generate = self.escalate
        self._loop_breaks = 0
        self._consecutive_violations = 0
        self._fingerprints.clear()
        self._emit("escalate", why=why)
        self.messages.append({"role": "user", "content":
            "Trocando para um modelo mais forte. Reavalie o estado e tome a PRÓXIMA "
            "ação concreta (um bloco json), ou declare task_blocked."})
        return True

    def _extract_on_complete(self, t: Task) -> None:
        """Extract (§6.2 passo 4): promove o resumo da tarefa para memória + MEMORY.md.

        SÓ p/ tarefa que fez TRABALHO durável (≥1 passo com efeito) — papo/exploração read-only não
        viram 'fato' de memória (era a mesma fábrica de lixo da skill/reflexão, ancorada na frase)."""
        if self.memory is None or not t.result:
            return
        if not any(s.effect for s in t.steps):       # nada durável aconteceu → não persiste resumo
            return
        from okami.memory import files as _mfiles
        from okami.memory.policy import prepare
        item = prepare(f"{t.goal} → {t.result}", source="task", kind="summary")   # passa pela política
        if item is not None:
            self.memory.write(item)
            self.events.emit("memory_write", kind=item.kind, text=item.text[:200])
        _mfiles.append_fact(self.ctx.workspace, f"{t.goal} → {t.result}")

    def _fail(self, t: Task, reason: str) -> Task:
        # REDE DE SEGURANÇA GERAL (não-específica da tarefa): qualquer que seja o motivo do corte
        # (loop, violações, passos, falha repetida), se já houve TRABALHO substancial, NÃO descarta tudo —
        # faz UMA última chamada p/ o modelo ENTREGAR o que levantou + o que faltou. Era o padrão que se
        # repetia: agente trabalha, algo trava no fim, e o turno morria MUDO. (Hermes _handle_max_iterations.)
        t.state = TaskState.FAILED
        t.reason = reason
        salvage = self._salvage(t, reason)
        if salvage:
            t.result = salvage                       # entrega parcial → o gateway mostra com ⚠ (não ❌ mudo)
            self._emit("salvaged", reason=reason, chars=len(salvage))
        self._emit("failed", reason=reason)
        return t

    def _salvage(self, t: Task, reason: str) -> str:
        """Última tentativa de ENTREGAR antes de falhar: pede o relatório do que já foi feito. '' se não há
        trabalho a salvar, se o provider é que falhou (chamá-lo de novo é inútil), ou se já tentou."""
        if self._salvaged or reason.startswith("provider"):
            return ""
        self._salvaged = True
        if len([s for s in t.steps if s.tool not in _REPORT_META]) < 3:   # quase nada feito → falha honesta
            return ""
        try:
            # Anti-alucinação (Hermes): entregar ≠ inventar. Pede o relatório HONESTO do que REALMENTE
            # aconteceu + o bloqueio — proíbe fabricar resultado que não foi produzido de verdade.
            self.messages.append({"role": "user", "content":
                f"O turno vai ENCERRAR sem concluir 100% (motivo: {reason}). NÃO termine calado, mas também "
                "NÃO invente nada. Escreva AGORA um relatório HONESTO: só o que você de FATO fez e o que as "
                "ferramentas REALMENTE retornaram (resultados parciais reais), e diga CLARAMENTE o que ficou "
                "faltando e por quê (o bloqueio). NUNCA fabrique dado, conteúdo de arquivo, número ou "
                "resultado de teste que você não produziu — reportar o bloqueio honestamente é melhor que "
                "inventar. Texto puro, sem json de ação. Esta é a ENTREGA final."})
            comp = as_completion(self.generate(self.messages, self._action_schema))
            txt = comp.text or ""
            cands = [prose_outside_action(txt), txt]
            act = _action_from_tool_calls(comp.tool_calls) or parse_action(txt)
            if act and act.tool in ("respond", "task_complete"):   # modelo embrulhou o relatório num respond
                cands.insert(0, str(act.args.get("message") or act.args.get("summary") or ""))
            best = max((c.strip() for c in cands), key=len, default="")
            return best if len(best) >= 40 else ""
        except Exception:  # noqa: BLE001 — salvage é best-effort; se falhar, cai no FAILED mudo normal
            return ""
