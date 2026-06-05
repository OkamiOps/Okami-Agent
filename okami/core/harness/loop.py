"""Harness — o loop ReAct confiável: Action-or-Terminate, watchdog/stall, anti-loop, exitCriteria.

Garante, por construção e independente da LLM: estado dono do harness, ação-ou-terminal, exitCriteria
verificados, watchdog/orçamentos, anti-loop (fingerprint+ciclo+breaker), anti-alucinação (grounding).
"""
from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Callable

from okami.core import approval
from okami.core.harness.models import Budget, Generate, Step, Task, TaskState
from okami.core.harness.parsing import (
    FUTURE_INTENT, _ACTION_RE, Action, _action_from_tool_calls, action_schema, parse_action,
)
from okami.core.harness.prompt import (
    _TOOL_RESULT_BUDGET, _user_start, build_system_prompt, check_exit, format_observation,
    is_conversational,
)
from okami.core.tools import Tool, ToolContext, ToolResult, default_registry
from okami.llm.usage import as_completion
from okami.memory import compaction as _compaction


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
                               checkpoints=checkpoints, spawn=spawn, sandbox=sandbox)
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
            {"role": "system", "content": build_system_prompt(t, self.registry, extra)},
            {"role": "user", "content": first},
        ]
        self._emit("start", goal=t.goal)

        step_n = 0
        turns = 0
        while True:
            turns += 1
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
            try:
                out = self.generate(self.messages, self._action_schema)
            except Exception as e:  # noqa: BLE001 — transporte esgotou retry/failover do provider
                from okami.core.errors import Action as _Act
                from okami.core.errors import classify_provider
                fail = classify_provider(e)
                self.events.emit("failure", scope="generate", kind=fail.kind.value,
                                 action=fail.action.value, reason=fail.reason, status=fail.status)
                if fail.action in (_Act.RETRY, _Act.ESCALATE) and self._try_escalate(f"provider: {fail.reason}"):
                    continue                      # tenta no modelo mais forte (resiliência, não crash)
                return self._fail(t, f"provider falhou: {fail.reason}")
            comp = as_completion(out)              # tolera str (JSON-em-texto) E Completion (nativo)
            _u = comp.usage                         # usage POR CHAMADA no trajeto (P2 observabilidade)
            self.events.emit("llm_call", provider=comp.provider, model=comp.model,
                             finish_reason=getattr(comp, "finish_reason", ""),
                             tokens_in=getattr(_u, "input_tokens", 0),
                             tokens_out=getattr(_u, "output_tokens", 0),
                             cache=getattr(_u, "cache_read_tokens", 0),
                             tool_call=bool(comp.tool_calls))
            self.messages.append({"role": "assistant", "content": comp.text})
            action = _action_from_tool_calls(comp.tool_calls) or parse_action(comp.text)

            # --- Action-or-Terminate (§3.2) ---
            if action is None or action.tool not in self.registry:
                # CONVERSA: o modelo só FALOU (prosa, sem envelope JSON) e não havia nada a executar
                # → isso É a resposta dele. Não rejeita nem mostra "emita JSON" (seria UX de robô num
                # papo). Só vale em conversa pura, sem ação pedida e sem tentativa de tool malformada.
                if (action is None and is_conversational(t) and not self._action_expected
                        and not FUTURE_INTENT.search(comp.text)  # promessa "vou fazer" NÃO é resposta
                        and '"tool"' not in comp.text and len(comp.text.strip()) >= 2):
                    t.state = TaskState.COMPLETE
                    t.result = comp.text.strip()
                    self._emit("complete", summary=t.result)
                    return t
                self._consecutive_violations += 1
                self._stats["violations"] += 1
                hint = ""
                if action is None and FUTURE_INTENT.search(comp.text):
                    hint = " Você descreveu intenção em vez de agir."
                self._emit("violation", n=self._consecutive_violations, text=comp.text[:200])
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
                self._loop_breaks += 1
                self._stats["loops"] += 1
                self._emit("loop", fingerprint=fp, repeats=repeats + 1, cycle=cycle)
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
            t.steps.append(Step(step_n, action.tool, action.args, res.output, res.effect))
            self._emit("step", n=step_n, tool=action.tool, args=action.args, ok=res.ok, effect=res.effect)
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
            # backstop: pediram AÇÃO mas ele só falou sem executar NADA com efeito → re-prompt 1x.
            if (self._action_expected and not self._nudged_action
                    and not any(s.effect for s in t.steps)):
                self._nudged_action = True
                self._emit("violation", n=0, text="respondeu sem executar a ação pedida")
                self.messages.append({"role": "user", "content":
                    "Você respondeu SEM executar nada. O pedido exige uma ferramenta de verdade "
                    "(ex.: write_file p/ criar arquivo, run_shell p/ rodar). Faça a AÇÃO agora "
                    "(um bloco json com a ferramenta certa) — depois confirme com respond."})
                return None
            t.state = TaskState.COMPLETE
            t.result = action.args.get("message") or action.args.get("summary") or ""
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
                t.state = TaskState.COMPLETE
                t.result = action.args.get("summary", "(sem resumo)")
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
        """Extract (§6.2 passo 4): promove o resumo da tarefa para memória + MEMORY.md."""
        if self.memory is None or not t.result:
            return
        from okami.memory import files as _mfiles
        from okami.memory.policy import prepare
        item = prepare(f"{t.goal} → {t.result}", source="task", kind="summary")   # passa pela política
        if item is not None:
            self.memory.write(item)
            self.events.emit("memory_write", kind=item.kind, text=item.text[:200])
        _mfiles.append_fact(self.ctx.workspace, f"{t.goal} → {t.result}")

    def _fail(self, t: Task, reason: str) -> Task:
        t.state = TaskState.FAILED
        t.reason = reason
        self._emit("failed", reason=reason)
        return t
