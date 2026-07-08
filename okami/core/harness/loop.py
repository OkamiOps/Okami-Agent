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
from okami.core.harness.parallel import paths_collide, run_parallel
from okami.core.harness.parsing import (
    FUTURE_INTENT, _ACTION_RE, Action, _action_from_tool_calls, _actions_from_tool_calls, action_schema,
    detect_malformed, parse_action, parse_actions, prose_outside_action, strip_think_blocks,
    truncated_action_name,
)
from okami.core.harness.prompt import (
    _user_start, budget_for_context_window, build_system_prompt, check_exit, format_observation,
    is_conversational,
)
from okami.core.tools import Tool, ToolContext, ToolResult, default_registry
from okami.core.tools.base import coerce_args
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


def _resolve_context_window_tokens(cfg, model: str) -> int:
    """Janela de contexto (tokens) do modelo EM USO, best-effort — alimenta budget_for_context_window
    (escala do orçamento de tool-result). Tenta o nome EXPLÍCITO do modelo (model_catalog: mais
    específico, cobre override de `-m`) e cai pro provider default do cfg (okami/llm/providers.py,
    que já resolve tier→janela). 0 = desconhecida (cfg de teste sem provider, modelo não catalogado) —
    o chamador cai nos defaults históricos, fail-open (nunca derruba o boot do turno por isso).

    Modelo ABERTO/LOCAL (is_weak_open_model): a janela do model_catalog é ARQUITETURAL (ex.: minimax
    catalogado com 1M) — mesma ressalva de providers.py `_LOCAL_WINDOW_CAP`: um deploy local (LMStudio/
    Ollama) não serve essa janela nominal rápido de verdade. Aplica o MESMO teto aqui (reconcilia com
    o valor de providers.py em vez de duplicar um número mágico solto)."""
    if model:
        try:
            from okami.core.harness.style import is_weak_open_model
            from okami.llm.model_catalog import model_info
            info = model_info(model)
            if info:
                win = info.context_window
                if is_weak_open_model(model):
                    from okami.llm.providers import _LOCAL_WINDOW_CAP
                    win = min(win, _LOCAL_WINDOW_CAP)
                return win
        except Exception:  # noqa: BLE001 — best-effort, nunca quebra o turno por causa de janela desconhecida
            pass
    try:
        if cfg is not None:
            from okami.llm.providers import context_window_tokens
            return context_window_tokens(cfg.provider())
    except Exception:  # noqa: BLE001 — idem (cfg de teste pode não ter .provider())
        pass
    return 0


_REPORT_META = {"respond", "task_complete", "task_blocked", "need_input"}
_POLL_TOOLS = {"process_wait", "process_poll", "process_log"}   # ESPERAR processo ≠ loop inútil (é I/O)
_BATCHABLE_READONLY = {"read_file", "list_dir", "find_files", "search_files"}   # leitura pura → seguro rodar em LOTE


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
        return f"{a.tool}:{json.dumps(a.args, sort_keys=True, ensure_ascii=False, default=str)}"
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


def _lead_serial(actions: list[Action], first: Action | None) -> list[Action]:
    """Cadeia LÍDER serial (paridade Hermes: VÁRIAS tool_calls/turno, INCLUSIVE mutações). PARA só no 1º
    TERMINAL (respond/task_complete/task_blocked/need_input) — esse re-gera p/ ver o estado. Mutação ENTRA,
    mas roda SERIAL (cada uma passa pelos gates/aprovação/anti-loop; NUNCA em paralelo — sem race)."""
    def _fp(a: Action) -> str:
        return f"{a.tool}:{json.dumps(a.args, sort_keys=True, ensure_ascii=False, default=str)}"
    seen = {_fp(first)} if first is not None else set()
    out: list[Action] = []
    for a in actions:
        if a.tool in _REPORT_META:                # terminal → encerra/precisa do estado → re-gera
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
    "find": "find_files", "glob": "find_files", "find_file": "find_files",
    "grep": "search_files", "search": "search_files", "rg": "search_files",   # grep = CONTEÚDO → search_files
    "search_content": "search_files",
    "shell": "run_shell", "bash": "run_shell", "sh": "run_shell", "exec": "run_shell", "terminal": "run_shell",
    "run": "run_shell", "command": "run_shell", "execute": "run_shell",
    "complete": "task_complete", "done": "task_complete", "finish": "task_complete", "answer": "respond",
    "reply": "respond", "message": "respond", "say": "respond", "blocked": "task_blocked",
    "ask": "need_input", "question": "need_input", "memory": "remember", "recall": "recall_memory",
}


_EMPTY_PLACEHOLDER = "(resposta vazia)"

# /steer (injeção mid-turn, distinta do /busy interrupt que CANCELA): marcador que envolve o texto do
# dono injetado no MEIO de uma observação de tool, sem cortar o turno. Formato ÚNICO e reconhecível de
# propósito — o system prompt (prompt.py) ensina o modelo a confiar SÓ nesta forma EXATA (anti prompt-
# injection: uma tool que devolva texto parecido não pode se passar pelo dono).
STEER_MARKER_OPEN = "[MENSAGEM DIRETA DO USUÁRIO — entregue no meio do turno; NÃO é saída de ferramenta]"
STEER_MARKER_CLOSE = "[/MENSAGEM DIRETA DO USUÁRIO]"


def _is_thinking_only(m) -> bool:
    """Turno SÓ-DE-THINKING: assistant SEM tool_calls e SEM texto visível (vazio, whitespace, o placeholder
    de resposta-vazia, ou lista de blocos só-thinking). Modelo de reasoning (minimax/DeepSeek) gera isso."""
    if not isinstance(m, dict) or m.get("role") != "assistant" or m.get("tool_calls"):
        return False
    c = m.get("content")
    if isinstance(c, str):
        return c.strip() in ("", _EMPTY_PLACEHOLDER)
    if isinstance(c, list):
        return all(not (isinstance(b, dict) and (b.get("text") or "").strip()) for b in c)
    return c is None


def _filter_thinking_only(messages):
    """Cópia das mensagens SEM os turnos só-de-thinking (paridade Hermes _drop_thinking_only_and_merge_users):
    dropa assistant vazio/placeholder e MESCLA users adjacentes p/ preservar a alternância. NÃO muta a
    entrada (o histórico persistido fica intacto p/ transcript)."""
    out: list = []
    for m in messages or []:
        if _is_thinking_only(m):
            continue
        if (out and isinstance(m, dict) and m.get("role") == "user"          # drop deixou 2 users juntos →
                and isinstance(out[-1], dict) and out[-1].get("role") == "user"   # funde p/ não quebrar a
                and isinstance(out[-1].get("content"), str) and isinstance(m.get("content"), str)):  # alternância
            out[-1] = {**out[-1], "content": out[-1]["content"] + "\n\n" + m["content"]}
            continue
        out.append(m)
    return out


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


def _verified_since_last_effect(steps: list) -> bool:
    """Heurística do verify-on-stop mínimo (WIN2): achou um `run_shell` BEM-SUCEDIDO (ok=True) DEPOIS
    do último passo com EFEITO? Sem passo com efeito, não há o que verificar → True (não bloqueia papo
    puro nem tarefa read-only). `run_shell` é o sinal — é o jeito universal de rodar teste/lint/build;
    outra tool de leitura (read_file) NÃO conta como "comprovação" no espírito do nudge."""
    last_effect = -1
    for i, s in enumerate(steps):
        if s.effect:
            last_effect = i
    if last_effect < 0:
        return True                                   # nada com efeito ainda → nada a verificar
    return any(s.tool == "run_shell" and s.ok for s in steps[last_effect + 1:])


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
        plugin_hooks=None,              # HookBus unificada (okami/plugins.py): pre/post_tool_call,
                                        # pre/post_llm_call, pre_verify, ... None = sem plugin de hook novo (no-op)
        spawn=None,
        images=None,
        prelearned_files=None,
        sandbox=None,
        skills_dir=None,
        open_fs: bool = False,
        surface: str = "cli",
        chat_id: str = "",              # chat de ORIGEM → ToolContext → process_start notifica o chat certo
        model: str = "",
        allow_paths: list | None = None,
        agent_home=None,                # CASA do agente (memória/identidade) — ≠ workspace (onde mexe)
        stage_writes: bool = False,     # escrita de memória → fila de aprovação (review + write_approval)
        cfg=None,                       # config (p/ tools que roteiam ao modelo auxiliar: web_extract/vision)
        notify=None,                    # hook de mensagem-ao-dono FORA do turno (item 3); None = sem canal
        clarify=None,                   # hook BLOQUEANTE: pergunta ao dono e devolve a resposta (#8 item 1)
        remote=None,                    # alvo de execução remoto (RemoteTarget) — FS/shell rodam LÁ
        set_remote=None,                # hook p/ persistir o alvo remoto na sessão (sobrevive ao turno)
        set_no_interrupt=None,          # hook p/ marcar fase NÃO-interruptível na sessão (compactação/subagente):
                                        # enquanto True o gateway demota /busy interrupt → queue (não corta no meio
                                        # de um passo sensível). None = sem sessão (CLI puro) → no-op.
        stream_tokens: bool = False,    # #16: streaming token-a-token → emite eventos 'token' ao gerar
        native_tools: bool = False,     # provider honra function-calling NATIVO (probe confirmou) → ramo nativo do prompt
        steer_source: Callable[[], str | None] | None = None,   # /steer: POLLA+DRENA o texto pendente do
                                        # dono na sessão (o gateway é o DONO do lock/estado — o harness só
                                        # chama, mesmo padrão de `cancel`). None = sem sessão (CLI puro) → no-op.
    ):
        self.stream_tokens = stream_tokens
        self._native_proto = native_tools   # protocolo: nativo (function-calling) vs JSON-em-texto (default)
        self.surface = surface          # canal de entrega → hint de formato (Telegram sem tabela, etc.)
        self.model = model              # nome do modelo → guidance por família (gpt/gemini/qwen…)
        self.images = images or []      # caminhos/URLs de imagens (vision §6) — exige modelo multimodal
        self.generate = generate
        self.escalate = escalate  # gerador de modelo mais forte (§3.5 cascata)
        # go/no-go (§12) FAIL-CLOSED: sem approver explícito, ação sensível é NEGADA (não auto-OK).
        # Sem humano (cron/spawn/lib) → bloqueia e instrui o modelo a achar alternativa. Auto-aprovar
        # exige passar approve explícito (ex.: yolo do gateway). Não-sensível roda normal (não chama isto).
        self.approve = approve if approve is not None else (lambda req: False)
        self.cancel = cancel or (lambda: False)       # /stop do gateway (§13)
        self._set_no_interrupt = set_no_interrupt or (lambda v: None)   # marca fase sensível na sessão (no-op no CLI)
        self._steer_source = steer_source or (lambda: None)   # drena o /steer pendente da sessão (no-op no CLI)
        self._deferred_steer: str | None = None   # steer drenado mas SEM mensagem tool/user pra anexar ainda
        #                                            (ex.: observação multimodal) → entregue no PRÓXIMO passo
        self.system_extra = system_extra  # skills forçadas / sections (§4.2, §8)
        self.core_block = core_block      # .md sempre injetados: AGENTS/USER/MEMORY (§6 tier core)
        self.memory = memory  # backend de memória (§6) — opcional
        self.task = task
        self.registry = registry or default_registry()
        self.budget = budget or Budget()
        self.hooks = hooks                 # event hooks (§11): before_tool pode VETAR
        self.plugin_hooks = plugin_hooks   # HookBus unificada (§unify): pre/post_tool_call, pre/post_llm_call, ...
        self.ctx = ToolContext(workspace=workspace, memory=memory, skills=skills or {},
                               checkpoints=checkpoints, spawn=spawn, sandbox=sandbox, skills_dir=skills_dir,
                               open_fs=open_fs, allow_paths=list(allow_paths or []),
                               agent_home=agent_home, stage_writes=stage_writes,
                               registry=self.registry,   # tool_search: schema sob demanda (item 27)
                               cfg=cfg,                   # web_extract/vision_analyze: roteamento aux
                               notify=notify,             # mensagem-ao-dono fora do turno (item 3)
                               clarify=clarify,           # pergunta ao dono antes de agir (#8 item 1)
                               surface=surface,           # superfície real → allowlist do remote_connect
                               chat_id=chat_id,           # chat de origem → process_start notifica o chat certo
                               remote=remote, set_remote=set_remote)  # ambiente remoto (SSH/Tailscale)
        # Arquivos já "conhecidos" (ex.: stubs de identidade na gênese): podem ser sobrescritos sem
        # exigir read antes — o grounding anti-alucinação não faz sentido p/ placeholders que NÓS criamos.
        self.ctx.read_files.update(prelearned_files or [])
        self.on_event = on_event or (lambda e: None)
        import secrets
        from okami.observability.events import EventLog
        # trace_id por turno (P2): amarra todos os eventos desta execução no timeline (replay/debug)
        self._trace_id = secrets.token_hex(4)
        self.events = EventLog(workspace, trace_id=self._trace_id)
        # CHECKPOINTS por-TURNO (item 17): se o backend de checkpoints suporta begin_turn, marca o início
        # deste turno (reuso do MESMO trace_id) p/ permitir rollback do turno inteiro. Guard getattr — o
        # agente de checkpoints adiciona begin_turn/rollback_turn; se ausente, no-op (fail-open, aditivo).
        _begin = getattr(checkpoints, "begin_turn", None)
        if callable(_begin):
            try:
                _begin(self._trace_id)
            except Exception:  # noqa: BLE001 — checkpoint é best-effort, nunca derruba o boot do turno
                pass
        self.messages: list[dict] = []
        self._action_schema = action_schema(self.registry)
        self._fingerprints: deque[str] = deque(maxlen=12)
        self._failures: dict[str, int] = {}
        self._consecutive_violations = 0
        self._consecutive_arg_fails = 0                # ações parseáveis mas SEM arg obrigatório, seguidas
        self._steps_without_effect = 0
        self._loop_breaks = 0
        self._stall_breaks = 0                          # quantas vezes o watchdog de SEM-PROGRESSO disparou
        self._stall_exceeded = False                    # estourou o teto → main loop escala/falha (não nudga ∞)
        self._escalated = False
        self._empty_responses = 0                       # respostas vazias seguidas (reasoning-only content='')
        self._turn_output_tokens = 0                    # tokens de OUTPUT acumulados no turno (backstop runaway)
        self._token_grace_used = False
        self._json_recoveries = 0                       # rodadas de RECUPERAÇÃO de formato (modelo fraco erra JSON)
        self._MAX_JSON_RECOVERIES = 2
        self._stats = {"violations": 0, "loops": 0, "gate_rejections": 0, "denials": 0}
        # backstop anti-preguiça (modelo fraco): pedido com verbo de ação exige EXECUTAR, não só falar
        self._action_expected = bool(_ACTION_RE.search(task.goal or ""))
        self._nudged_action = False
        self._empty_nudged = False                     # respondeu VAZIO → re-pede a resposta de verdade (1x)
        self._punt_nudged = False                      # encerrou pedindo permissão/menu → empurra a concluir (1x)
        self._blocked_nudged = False                   # desistiu CEDO (task_blocked prematuro) → empurra a tentar (1x)
        # Preview INLINE de saída grande persistida: em modelo LOCAL/fraco o custo por-passo é a observação
        # reenviada → encolhe (full no disco, relido com read_file/offset). Forte mantém o cheio. Ambos os
        # orçamentos (por-resultado e o preview do fraco) escalam pela JANELA REAL do modelo (porte Hermes
        # tools/budget_config.py budget_for_context_window) — um teto fixo de 8K/1.5K era cego à janela:
        # sub-usava modelos de 200K+ ctx e, pro caso oposto, um preview de 1500 chars fixo era migalha até
        # p/ modelo local de 32K ctx. Janela desconhecida (cfg/model_catalog sem entrada) → cai nos
        # defaults históricos (byte-idêntico ao comportamento anterior a esta escala).
        from okami.core.harness.style import is_weak_open_model
        _window_tokens = _resolve_context_window_tokens(cfg, model)
        self._tool_result_budget, _per_turn_budget, _preview_weak = budget_for_context_window(_window_tokens)
        # só sobrescreve o teto agregado do turno se o caller não passou um customizado (guardrails/config) —
        # reconcilia com o campo JÁ EXISTENTE (models.py) em vez de duplicar um novo teto paralelo.
        if self.budget.max_turn_tool_chars == Budget().max_turn_tool_chars:
            self.budget.max_turn_tool_chars = _per_turn_budget
        self._preview_cap = _preview_weak if is_weak_open_model(model) else self._tool_result_budget
        self._thin_nudged = False                      # entrega rasa vs trabalho feito → re-pede o relatório (1x)
        self._poll_waits = 0                           # esperas repetidas num processo bg (não é loop de FAIL)
        self._exec_refunds = 0                         # item 5: passos devolvidos p/ execute_code read-only (bounded)
        self._salvaged = False                         # já tentou a entrega-parcial antes de falhar? (1x)
        self._batch: list[Action] = []                 # leituras restantes da MESMA geração (batch — Hermes)
        self._truncated_parts: list[str] = []          # length-continuation (Hermes): partes de resposta cortada
        self._MAX_LENGTH_CONT = 6                      # teto de continuações por entrega (anti-loop)
        self._truncated_action_reemits = 0             # teto de re-emissões de AÇÃO truncada (review #2b)
        self._next_max_tokens: int | None = None       # teto de tokens p/ a PRÓXIMA geração (boost de length)
        self._grace_used = False                       # 1 iteração extra no limite de passos (grace, Hermes)
        from okami.core.harness.loopguard import ProgressTracker
        self._progress = ProgressTracker()             # não-progresso por OUTPUT (OpenClaw): poll/read que não muda
        self._stall_nudged: set[str] = set()           # já avisei que ESTA tool não anda? (1x por tool)
        self._MAX_SAME_OUTPUT = 2                       # 3ª saída idêntica seguida da mesma tool → nudge
        self._low_gain_compactions = 0                 # anti-thrashing: compactações seguidas com <10% de ganho
        self._obs_chars = 0                            # teto AGREGADO de tool-output do turno (Hermes: 200K)
        self._loop_warned: set[str] = set()             # fingerprints já AVISADOS (warn-before-block, WIN1)
        self._pending_loop_warn: str | None = None      # aviso a anexar DEPOIS do próximo tool-result (WIN1)
        # AGREGAÇÃO de falha PRÉ-dispatch (WIN1, paridade Hermes tool_guardrails.py:298-319): nome
        # ALUCINADO e args FALTANDO são hoje contadores DISJUNTOS (_consecutive_violations vs
        # _consecutive_arg_fails), cada um resetado pelo OUTRO modo de erro — um modelo que ALTERNA entre
        # os dois nunca deixa nenhum dos dois isolados bater o próprio teto. Este é o contador UNIFICADO:
        # soma as duas falhas, na ORDEM que vierem, e só zera quando uma tool de fato DISPACHA de verdade.
        self._consecutive_action_failures = 0
        self._verify_nudged = False                    # verify-on-stop (WIN2): já empurrei p/ verificar? (1x)

    def _note_compact_gain(self, before: int, after: int) -> bool:
        """Anti-thrashing de compactação (pesquisa #5 item 2): compactação PESADA que rende <10% não
        está resolvendo — o contexto está saturado de conteúdo incompressível (tail gigante). Duas
        seguidas = thrash; True = pare de insistir e encerre honesto sugerindo /new."""
        if before <= 0 or (before - after) >= 0.10 * before:
            self._low_gain_compactions = 0
            return False
        self._low_gain_compactions += 1
        return self._low_gain_compactions >= 2

    def _append_user_note(self, note: str) -> None:
        """Nota do harness como mensagem 'user', FUNDIDA na última se ela já for user — Anthropic
        exige alternância user/assistant (duas 'user' seguidas = erro de API)."""
        if self.messages and self.messages[-1].get("role") == "user":
            last = self.messages[-1]
            self.messages[-1] = {**last, "content": (last.get("content") or "") + "\n\n" + note}
        else:
            self.messages.append({"role": "user", "content": note})

    def _emit(self, kind: str, **data):
        self.on_event({"kind": kind, **data})
        self.events.emit(kind, **data)      # persiste o timeline (start/step/loop/compact/complete/…)

    def _length_max_tokens(self, attempt: int) -> int:
        """Teto de tokens da continuação de length (paridade Hermes `_boost_base*(n+1)`, piso 32K): cresce
        a cada tentativa pra a continuação ter ESPAÇO de fechar — senão re-trunca no mesmo ponto. Capado ao
        que CABE (multi-vendor: num provider de contexto pequeno, pedir 200K de output = 400 na hora)."""
        return self._cap_output_tokens(min(32768 * (max(0, int(attempt)) + 1), 200_000))

    def _cap_output_tokens(self, want: int) -> int:
        """Não pede mais output do que cabe na janela: available ≈ (teto de contexto − prompt atual)/4 tokens.
        AGNÓSTICO: Ollama/LMStudio/etc com janela pequena estouravam pedindo output gigante. Piso de 1024."""
        try:
            avail = (self.budget.max_context_chars - _compaction.estimate_chars(self.messages)) // 4 - 256
        except Exception:  # noqa: BLE001 — estimativa falhou → não capa (comportamento antigo)
            return want
        return max(1024, min(want, int(avail))) if avail > 0 else 1024

    def _do_generate(self, messages, schema):
        """Gera. Com stream_tokens, passa on_token (emite 'token' por delta) — mas tolera generate de 2
        args (stubs de teste) via TypeError. `_next_max_tokens` (boost de length) é passado e CONSUMIDO."""
        mt = self._next_max_tokens
        self._next_max_tokens = None                  # consome: o boost vale só pra ESTA geração
        messages = _filter_thinking_only(messages)    # dropa turno só-de-thinking/placeholder da CÓPIA enviada
        kw = {"max_tokens": mt} if mt else {}
        _pre_llm = getattr(self.plugin_hooks, "invoke", None)   # pre/post_llm_call (bus unificada, §unify)
        if callable(_pre_llm):
            _pre_llm("pre_llm_call", messages=messages, schema=schema)
        if self.stream_tokens:
            try:
                res = self.generate(messages, schema, on_token=lambda t: self._emit("token", text=t), **kw)
                if callable(_pre_llm):
                    _pre_llm("post_llm_call", messages=messages, schema=schema, result=res)
                return res
            except TypeError:
                pass
        try:
            res = self.generate(messages, schema, **kw)
        except TypeError:                              # stub/generate sem max_tokens → chamada simples
            res = self.generate(messages, schema)
        if callable(_pre_llm):
            _pre_llm("post_llm_call", messages=messages, schema=schema, result=res)
        return res

    def _pending_todos(self) -> str:
        """Bloco de reinjeção da CHECKLIST operacional (item 9) — só os itens em aberto. "" se não há
        TODOs ou se a render falha (fail-open: a compactação nunca quebra por causa do checklist)."""
        try:
            from okami.core.tools.todo import render_pending
            return render_pending(self.ctx.todos)
        except Exception:  # noqa: BLE001
            return ""

    def _compact(self, *, keep_tail: int = 6) -> int:
        """Compacta self.messages reinjetando a CHECKLIST operacional em aberto (item 9). Devolve o nº
        de fatos destilados. FAIL-OPEN com o kwarg pending_todos: uma implementação de compact que ainda
        não conhece o parâmetro (stub de teste antigo / fork) é chamada sem ele — nunca quebra o turno.
        Fase NÃO-interruptível: cortar o turno no meio de uma compactação corrompe o histórico (pares
        tool_call/tool órfãos) → marca a sessão p/ o gateway demotar /busy interrupt → queue enquanto roda."""
        self._set_no_interrupt(True)
        try:
            try:
                self.messages, promoted = _compaction.compact(
                    self.messages, self.memory, keep_tail=keep_tail,
                    pending_todos=self._pending_todos())
            except TypeError:                          # compact sem suporte a pending_todos → modo legado
                self.messages, promoted = _compaction.compact(
                    self.messages, self.memory, keep_tail=keep_tail)
        finally:
            self._set_no_interrupt(False)
        return promoted

    # --- audit + budget de resultado de tool (Sprint 2) ---------------------
    def _audit(self, **fields) -> None:
        """Trilha append-only de TODA tool + decisão de aprovação (.okami/audit.jsonl), com HMAC ENCADEADO
        (item 5): cada linha leva um `mac` = HMAC(key, tail_anterior + payload-menos-mac), espelhando os
        checkpoints. Adulterar/inserir/reordenar uma linha quebra a cadeia dali em diante → a trilha vira
        tamper-evident. Campos FLAT preservados (leitores existentes seguem lendo). Best-effort: qualquer
        falha (chave, redact, I/O) cai no append simples sem mac em vez de derrubar o turno."""
        try:
            import time as _t
            from okami.core import machain
            from okami.core.redact import redact
            d = self.ctx.workspace / ".okami"
            d.mkdir(parents=True, exist_ok=True)
            audit = d / "audit.jsonl"
            # payload = campos FLAT redigidos (segredo mascarado ANTES do mac → o mac cobre o que é gravado)
            payload = json.loads(redact(json.dumps({"ts": _t.time(), **fields},
                                                   ensure_ascii=False, default=str)))
            key = machain.key_for(self.ctx.workspace)
            # cache do último mac (item 30): tail_mac relê o arquivo INTEIRO a cada append → O(n²) numa
            # sessão com muitas tools. Lê do disco só na 1ª vez deste harness; depois encadeia em memória.
            prev = getattr(self, "_audit_last_mac", None)
            if prev is None:
                prev = machain.tail_mac(audit)
            mac = machain.mac(key, prev, payload)
            entry = {**payload, "mac": mac}
            with audit.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._audit_last_mac = mac
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
        # default=str: tipo não-JSON (set/etc) NUNCA derruba o turno no fingerprint (defesa; o parser já
        # normaliza, mas tool/MCP pode injetar args exóticos).
        return f"{action.tool}:{json.dumps(action.args, sort_keys=True, ensure_ascii=False, default=str)}"

    def _bump_action_failure(self) -> int:
        """Incrementa o contador UNIFICADO de falha pré-dispatch (nome inválido + arg faltando, WIN1).
        Zera só quando alguma tool DISPACHA de verdade (_handle_tool_result)."""
        self._consecutive_action_failures += 1
        return self._consecutive_action_failures

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
                                                              workspace=self.ctx.workspace,
                                                              surface=self.surface, model=self.model,
                                                              allow_paths=self.ctx.allow_paths,
                                                              open_fs=self.ctx.open_fs, native=self._native_proto)},
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
                    self._compact(keep_tail=4)
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
                if not self._grace_used:             # GRACE (Hermes): 1 última iteração real no limite —
                    self._grace_used = True          # muitas tarefas fecham no passo seguinte (task_complete)
                    self._emit("grace_step", step=step_n)
                else:
                    return self._fail(t, f"orçamento de {self.budget.max_steps} passos esgotado")
            if (self.budget.max_turn_output_tokens                          # backstop de TOKENS (runaway de
                    and self._turn_output_tokens >= self.budget.max_turn_output_tokens):   # geração) — protege
                if not self._token_grace_used:                             # provider por-token de queimar $$$
                    self._token_grace_used = True                          # GRACE: 1 última chamada (fecha no
                    self._emit("token_budget_grace", tokens=self._turn_output_tokens)    # passo seguinte)
                else:
                    return self._fail(t, f"orçamento de tokens do turno esgotado (~{self._turn_output_tokens} "
                                      "tokens de saída) — runaway protegido")
            if self._stall_exceeded:                 # watchdog de SEM-PROGRESSO estourou N vezes (nudge não
                self._stall_exceeded = False         # resolveu): escala p/ modelo mais forte, senão FALHA
                if self._try_escalate("sem progresso persistente"):   # (com salvage) — em vez de nudgar ∞
                    self._stall_breaks = 0
                else:
                    return self._fail(t, "sem progresso: vários passos sem resultado e a abordagem não mudou")
            if self.cancel():                        # /stop do usuário (§13)
                t.state = TaskState.BLOCKED
                t.reason = "cancelado pelo usuário (/stop)"
                self._emit("cancelled")
                return t
            # Auto-compaction (§6.4) em DUAS fases (Hermes): primeiro a poda BARATA de tool-results
            # antigos (1-linha + dedup, sem perda — transcript segue na sessão); só se ainda estourar,
            # o compact pesado (drop de mensagens + destilação à memória).
            if _compaction.estimate_chars(self.messages) > self.budget.max_context_chars:
                self.messages, _saved = _compaction.prune_observations(self.messages)
                if _saved:
                    self._emit("compact", promoted=0, pruned_chars=_saved)
                _before = _compaction.estimate_chars(self.messages)
                if _before > self.budget.max_context_chars:
                    promoted = self._compact()
                    self._emit("compact", promoted=promoted)
                    # Anti-thrashing (pesquisa #5 item 2): 2 compactações seguidas rendendo <10% =
                    # contexto saturado — compactar a cada turno é thrash. Encerra honesto (com
                    # salvage de entrega parcial via _fail) sugerindo /new.
                    if self._note_compact_gain(_before, _compaction.estimate_chars(self.messages)):
                        self._emit("compact_thrash", before=_before)
                        return self._fail(t, "a compactação não reduz mais o contexto (<10% de ganho "
                                             "2x seguidas) — contexto saturado. Conclua aqui e abra "
                                             "uma sessão nova com /new.")
            # LOTE (batch — Hermes roda VÁRIAS por turno): se sobraram LEITURAS da mesma geração, roda a
            # próxima SEM nova chamada ao modelo — corta os round-trips (o gargalo de velocidade vs Hermes).
            # Só leitura entra no lote; ação que muta/encerra/pede aprovação segue 1-por-turno.
            if self._batch:
                action = self._batch.pop(0)
                text = ""
            else:
                _g0 = _wt.monotonic()                  # cronômetro da geração → torna o gargalo VISÍVEL
                try:
                    out = self._do_generate(self.messages, self._action_schema)
                except Exception as e:  # noqa: BLE001 — transporte esgotou retry/failover do provider
                    from okami.core.errors import Action as _Act
                    from okami.core.errors import classify_provider
                    fail = classify_provider(e)
                    self.events.emit("failure", scope="generate", kind=fail.kind.value,
                                     action=fail.action.value, reason=fail.reason, status=fail.status)
                    # RECALIBRAÇÃO multi-vendor: o provider REPORTOU o limite REAL de contexto (tokens) no erro
                    # — crucial p/ Ollama/LMStudio, onde o contexto carregado quase nunca bate o catálogo. Baixa
                    # o teto de compactação p/ ~80% do limite real (tokens→chars ≈ ×4) → compacta no ponto certo
                    # daqui pra frente em vez de estourar de novo. Só ENCOLHE (nunca aumenta).
                    if fail.context_limit:
                        _real = int(fail.context_limit * 3.2)
                        if 0 < _real < self.budget.max_context_chars:
                            self.budget.max_context_chars = _real
                            self._emit("context_limit_calibrated", tokens=fail.context_limit, chars=_real)
                    # RECUPERAÇÃO 1ª: timeout/lento ≈ CONTEXTO GRANDE. ENCOLHE forte (keep_tail=3) e re-gera 1x —
                    # chamada menor = mais rápida, cabe até no fallback local. Antes só escalava p/ modelo mais
                    # forte com o MESMO contexto gigante → pendurava de novo e morria.
                    if fail.action in (_Act.RETRY, _Act.ESCALATE) and not self._shrunk_retry:
                        self._shrunk_retry = True
                        before = _compaction.estimate_chars(self.messages)
                        promoted = self._compact(keep_tail=3)
                        if _compaction.estimate_chars(self.messages) < before:
                            self._emit("compact", promoted=promoted)
                            # Continuação distinta p/ QUEDA NO MEIO (pesquisa #5 item 3): sem isto o
                            # modelo re-gerado tende a recomeçar do zero e repetir trabalho já feito.
                            self._append_user_note(
                                "[A geração anterior FALHOU no meio (rede/provider) e foi descartada. "
                                "Retome do estado atual — NÃO recomece do zero nem repita trabalho já "
                                "concluído nos passos anteriores.]")
                            continue              # re-gera com contexto MENOR (mais rápido, sem trocar modelo)
                    # RECUPERAÇÃO 2ª: escala p/ modelo mais forte (resiliência, não crash)
                    if fail.action in (_Act.RETRY, _Act.ESCALATE) and self._try_escalate(f"provider: {fail.reason}"):
                        continue
                    from okami.core.errors import friendly_failure   # mensagem HUMANA (não "falhou: overloaded")
                    return self._fail(t, friendly_failure(fail.reason))
                comp = as_completion(out)          # tolera str (JSON-em-texto) E Completion (nativo)
                self._shrunk_retry = False         # gerou com sucesso → libera novo encolhimento p/ falha futura
                # RESPOSTA VAZIA (modelo de reasoning: tudo no reasoning_content, content=''): NÃO persiste
                # {role:assistant, content:''} sem tool_calls — o histórico zumbi faz o PRÓXIMO request 400
                # ('assistant precisa de content OU tool_calls'). Conta, recupera com nudge, e é BOUNDED.
                if not (comp.text or "").strip() and not comp.tool_calls:
                    self._empty_responses += 1
                    self._emit("empty_response", n=self._empty_responses)
                    if self._empty_responses >= 3:
                        if self._try_escalate("respostas vazias repetidas"):
                            self._empty_responses = 0
                            continue
                        return self._fail(t, "o modelo devolveu resposta vazia várias vezes seguidas")
                    self.messages.append({"role": "assistant", "content": "(resposta vazia)"})  # não-zumbi
                    self._append_user_note("[Sua resposta veio VAZIA. Emita UMA ação (tool) agora — ou, se a "
                                           "tarefa já terminou, chame task_complete com um resumo.]")
                    continue
                self._empty_responses = 0          # veio conteúdo/ação → zera o contador de vazias
                _u = comp.usage                     # usage POR CHAMADA no trajeto (P2 observabilidade)
                self._turn_output_tokens += int(getattr(_u, "output_tokens", 0) or 0)   # backstop runaway
                self.events.emit("llm_call", provider=comp.provider, model=comp.model,
                                 surface=self.surface,        # /insights: breakdown por plataforma (item 21)
                                 finish_reason=getattr(comp, "finish_reason", ""),
                                 tokens_in=getattr(_u, "input_tokens", 0),
                                 tokens_out=getattr(_u, "output_tokens", 0),
                                 cache=getattr(_u, "cache_read_tokens", 0),
                                 tool_call=bool(comp.tool_calls),
                                 secs=round(_wt.monotonic() - _g0, 1))   # quanto a CHAMADA demorou
                _amsg = {"role": "assistant", "content": comp.text}
                if getattr(comp, "reasoning_items", None):   # Codex/o-series store=false: guarda p/ REPLAY no
                    _amsg["reasoning_items"] = comp.reasoning_items   # mesmo turno (só o transport codex lê)
                self.messages.append(_amsg)

                # LENGTH-CONTINUATION (Hermes): resposta CORTADA pelo limite (finish_reason='length') →
                # continua EXATAMENTE de onde parou e CONCATENA, em vez de aceitar a entrega pela metade.
                if getattr(comp, "finish_reason", "") == "length" and len(self._truncated_parts) < self._MAX_LENGTH_CONT:
                    # Continuação DISTINTA por tipo de corte (pesquisa #5 item 3): TOOL de args grandes
                    # (write_file etc.) truncada não pode ser "continuada do meio" (concatenar JSON
                    # cortado é loteria) — descarta o parcial e RE-EMITE menor. Já respond/task_complete
                    # truncado é um RELATÓRIO longo: continuar preserva o conteúdo (re-emitir perderia).
                    _tname = truncated_action_name(comp.text)
                    if _tname and _tname not in _REPORT_META:
                        # TETO próprio (review #2b): re-emitir não acumula em _truncated_parts, então o
                        # cap de length não protegeria aqui — sem isto o modelo teimoso spinava até o
                        # backstop de turnos. Esgotou as tentativas → deixa cair no fluxo normal (a ação
                        # truncada não parseia → detect_malformed ENSINA / vira violação).
                        self._truncated_action_reemits += 1
                        if self._truncated_action_reemits <= self._MAX_LENGTH_CONT:
                            self._next_max_tokens = self._length_max_tokens(self._truncated_action_reemits)
                            self._emit("length_continue", part=0, truncated_action=True)
                            self.messages.append({"role": "user", "content":
                                "[Sua AÇÃO (json) foi CORTADA pelo limite de tamanho — o JSON não fechou. "
                                "NÃO repita igual nem tente continuar do meio: re-emita a ação COMPLETA com "
                                "args menores — quebre conteúdo grande em pedaços de <8K chars (ex.: "
                                "write_file da primeira parte, depois edit_file p/ anexar o resto).]"})
                            continue
                    self._truncated_parts.append(comp.text)
                    self._next_max_tokens = self._length_max_tokens(len(self._truncated_parts))
                    self._emit("length_continue", part=len(self._truncated_parts))
                    self.messages.append({"role": "user", "content":
                        "[Sua resposta foi CORTADA pelo limite de tamanho. Continue EXATAMENTE de onde parou, "
                        "SEM repetir o que já escreveu, e TERMINE a entrega. Se estava no meio do bloco json "
                        "de ação, complete-o.]"})
                    continue
                if self._truncated_parts and parse_actions(comp.text):
                    # pediu "continue" mas veio uma ação COMPLETA standalone → o modelo re-emitiu do
                    # zero; concatenar duplicaria/quebraria o JSON — usa a fresca e descarta o parcial.
                    self._truncated_parts = []
                text = "".join(self._truncated_parts) + comp.text if self._truncated_parts else comp.text
                # ESGOTOU a continuação e a resposta AINDA veio cortada (finish_reason=length): não entrega
                # pela metade FINGINDO que fechou. Marca claro (paridade Hermes: não dá done silencioso num
                # turno truncado). Ação truncada não parseia → cai na violação normal; relatório leva o aviso.
                _unresolved_trunc = bool(self._truncated_parts) and getattr(comp, "finish_reason", "") == "length"
                self._truncated_parts = []             # episódio de truncamento fechado → texto completo
                if _unresolved_trunc and not _actions_from_tool_calls(comp.tool_calls) and not parse_actions(text):
                    self._emit("truncation_unresolved", parts=self._MAX_LENGTH_CONT)
                    text += ("\n\n[⚠ resposta truncada no limite de tamanho — não consegui FECHAR mesmo "
                             "continuando; peça pra eu continuar de onde parei se faltou conteúdo]")
                _acts = _actions_from_tool_calls(comp.tool_calls) or parse_actions(text)
                for _a in _acts:                       # COERÇÃO schema-aware: nativo manda "false"/"30" string
                    _t = self.registry.get(_a.tool)    # → coage pro tipo declarado (arg_types) p/ não bugar
                    if _t is not None and getattr(_t, "arg_types", None):
                        _a.args = coerce_args(_a.args, _t.arg_types)
                action = _acts[0] if _acts else None
                # VÁRIAS tool_calls por turno (paridade Hermes). NATIVO: cadeia SERIAL inclusive com mutações
                # (cada uma gated/aprovada/anti-loop; a 1ª é a tool_call declarada na assistant=role=tool, as
                # demais voltam como observação → sequência válida, sem órfã). JSON (modelo fraco): só leituras
                # líderes (mutação 1/turno — protocolo de texto não tem o mesmo contrato de mensagem).
                self._batch = (_lead_serial(_acts[1:], action) if comp.tool_calls
                               else _lead_readonly(_acts[1:], action))

            # --- Reparo de nome de tool ALUCINADO (Hermes): 'read'→'read_file' etc. antes de violar ---
            if action is not None and action.tool not in self.registry:
                _fix = _repair_tool_name(action.tool, self.registry)
                if _fix:
                    self._emit("tool_repaired", **{"from": action.tool, "to": _fix})
                    action = Action(_fix, action.args, call_id=action.call_id)   # preserva o id nativo

            # --- Action-or-Terminate (§3.2) ---
            if action is None or action.tool not in self.registry:
                # CONVERSA: o modelo só FALOU (prosa, sem envelope JSON) e não havia nada a executar
                # → isso É a resposta dele. Não rejeita nem mostra "emita JSON" (seria UX de robô num
                # papo). Só vale em conversa pura, sem ação pedida e sem tentativa de tool malformada.
                if (action is None and is_conversational(t) and not self._action_expected
                        and not FUTURE_INTENT.search(text)  # promessa "vou fazer" NÃO é resposta
                        and '"tool"' not in text and len(text.strip()) >= 2):
                    t.state = TaskState.COMPLETE
                    t.result = strip_think_blocks(text)        # tira <think> que vazaria pra resposta visível
                    self._emit("complete", summary=t.result)
                    return t
                self._consecutive_violations += 1
                self._stats["violations"] += 1
                hint = ""
                _diag = detect_malformed(text) if action is None else None
                if _diag:                                  # JSON inválido/truncado → erro sintético que ENSINA
                    hint = f" {_diag}"
                elif action is None and FUTURE_INTENT.search(text):
                    hint = " Você descreveu intenção em vez de agir."
                elif action is not None:                   # nome de tool ALUCINADO e sem reparo → sugere as
                    import difflib                          # MAIS PRÓXIMAS (não despeja o manual inteiro: o
                    _near = difflib.get_close_matches(action.tool.lower(), list(self.registry), n=5, cutoff=0.3)
                    hint = (f" '{action.tool}' não existe." +  # prompt já lista as tools; aqui só um empurrão
                            (f" Quis dizer: {', '.join(_near)}?" if _near else ""))
                self._emit("violation", n=self._consecutive_violations, text=text[:200])
                # AGREGAÇÃO unificada (WIN1, paridade Hermes tool_guardrails.py:298-319): nome ALUCINADO
                # conta pro MESMO contador que arg-faltando lá embaixo — fecha o buraco de um modelo que
                # ALTERNA entre os dois erros (nenhum contador ISOLADO bate sozinho na alternância).
                _agg = self._bump_action_failure()
                if (self._consecutive_violations >= self.budget.max_consecutive_violations
                        or _agg >= self.budget.max_tool_failures):
                    if self._try_escalate("violações de Action-or-Terminate"):
                        continue
                    # JSON-RECOVERY (Hermes): antes de DESISTIR, injeta uma recuperação CLARÍSSIMA e dá +N
                    # rodadas — modelo fraco (sem escalate) que erra o formato 3x merece um empurrão, não fail
                    # seco. BOUNDED por _MAX_JSON_RECOVERIES (anti-loop infinito); depois disso, falha.
                    if self._json_recoveries < self._MAX_JSON_RECOVERIES and self._truncated_action_reemits == 0:
                        # SÓ p/ erro de FORMATO genuíno (prosa/garbage). Se o modelo está preso TRUNCANDO ação
                        # (re-emits > 0), a recuperação multiplicaria com o ciclo de continuação → deixa o cap
                        # de truncamento falhar limpo.
                        self._json_recoveries += 1
                        self._consecutive_violations = 0
                        self._emit("json_recovery", attempt=self._json_recoveries)
                        self._append_user_note(
                            "[RECUPERAÇÃO: suas últimas saídas NÃO foram ações válidas. PARE e emita AGORA UM "
                            'ÚNICO bloco json EXATO, nada antes nem depois: {"tool":"<nome>","args":{...}}. '
                            'Terminou? {"tool":"task_complete","args":{"summary":"..."}}. Travou? '
                            '{"tool":"task_blocked","args":{"reason":"..."}}.]')
                        continue
                    return self._fail(t, "violações repetidas de Action-or-Terminate (mesmo após recuperação)")
                self._reject(action,                                       # NATIVO → erro role=tool; JSON → user
                             f"erro: ferramenta inválida.{hint} Chame uma ferramenta REAL.",
                             f"REJEITADO: nenhuma ação válida.{hint} Emita UM bloco ```json "
                             f'{{"tool": "...", "args": {{...}}}}``` agora — ou task_blocked.')
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
                self._reject(action,                                       # NATIVO → erro role=tool; JSON → user
                             "erro: ação repetida (loop). NÃO repita — faça algo DIFERENTE ou conclua.",
                             "LOOP DETECTADO: você já repetiu essa ação. NÃO repita — faça algo "
                             "diferente ou declare task_blocked com a razão.")
                self._fingerprints.append(fp)
                continue
            elif repeats + 1 == self.budget.warn_repeat and fp not in self._loop_warned:
                # WARN-BEFORE-BLOCK (WIN1, paridade Hermes agent/tool_guardrails.py warn_after): a 2ª
                # repetição idêntica ainda EXECUTA — só avisa (1x por fingerprint, não spamma a cada
                # repetição intermediária). O bloqueio de vez só chega em max_repeat (ramo acima). O aviso
                # vai DEPOIS do resultado da tool (_handle_tool_result), pra não quebrar a sequência
                # assistant→tool do protocolo nativo (call_id tem de ser seguido IMEDIATAMENTE pelo result).
                self._loop_warned.add(fp)
                self._emit("loop_warn", fingerprint=fp, repeats=repeats + 1)
                self._pending_loop_warn = (
                    "AVISO: você repetiu essa MESMA ação antes. Ainda não é bloqueio, mas mude a "
                    "abordagem — ou, se a repetição é de propósito (ex.: esperar um processo), explique "
                    "o porquê na próxima mensagem. Repetir sem mudar nada vai bloquear em breve.")

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
                # NUDGE (task_complete/respond rejeitado: rasa/sem-ferramenta/sem-verificação/...) = o
                # modelo RESPONDEU, não travou — mesma lógica do go/no-go negado/hook vetado acima: reseta
                # o anti-travamento (senão dois nudges seguidos em cima de trabalho longo podem SOMAR
                # tempo de relógio e disparar o watchdog de stall por engano, mesmo com o modelo ativo).
                _last_progress = _wt.monotonic()
                continue  # task_complete rejeitado → segue

            # --- Validação de args: ação malformada NÃO quebra o harness, vira re-prompt ---
            missing = [a for a in tool.required if a not in action.args]
            if missing:
                self._stats["violations"] += 1
                self._fingerprints.append(fp)
                # Contador PRÓPRIO: o re-prompt não conta passo, e o anti-loop por args idênticos não pega
                # quando o modelo varia os OUTROS args a cada tentativa (só erra o obrigatório). Sem isto, um
                # modelo fraco girava até o backstop de 1000 turns mandando a mesma tool incompleta. Reseta
                # a cada dispatch de verdade (_handle_tool_result) → só conta SEGUIDAS.
                self._consecutive_arg_fails += 1
                self._emit("malformed_args", tool=action.tool, missing=missing,
                           n=self._consecutive_arg_fails)
                # AGREGAÇÃO unificada (WIN1): mesmo contador do nome-alucinado acima — args faltando
                # também soma no total, fechando o buraco da alternância nome-errado ↔ args-faltando que
                # nenhum contador isolado pegava sozinho.
                _agg = self._bump_action_failure()
                if (self._consecutive_arg_fails >= self.budget.max_consecutive_violations
                        or _agg >= self.budget.max_tool_failures):
                    if self._try_escalate("ação repetidamente sem argumento obrigatório"):
                        self._consecutive_arg_fails = 0
                        continue
                    return self._fail(t, f"ação '{action.tool}' veio sem argumento(s) obrigatório(s) "
                                         f"{missing} repetidas vezes — modelo não consegue formar a chamada.")
                self._reject(action,                                       # NATIVO → erro role=tool; JSON → user
                             f"erro: faltou argumento obrigatório {missing}. Reenvie a chamada COMPLETA.",
                             f"Ação '{action.tool}' sem argumento(s) obrigatório(s): {missing}. Reenvie completa.")
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
                    t.steps.append(Step(step_n, action.tool, action.args, "negado (go/no-go)", False, False))
                    self._emit("step", n=step_n, tool=action.tool, args=action.args, ok=False, effect=False)
                    self._reject(action,                                   # NATIVO → erro role=tool; JSON → user
                                 f"erro: ação NEGADA (go/no-go) — {sens.reason}. Proponha uma alternativa.",
                                 f"AÇÃO NEGADA (go/no-go): o usuário recusou — {sens.reason}. Proponha "
                                 "alternativa, peça confirmação com outra abordagem, ou declare task_blocked.")
                    continue

            # --- Hook before_tool (§11): política externa pode VETAR a tool ---
            # + pre_tool_call (bus unificada, §unify): ADITIVO — plugin novo via ctx.on("pre_tool_call", fn)
            # também pode vetar, sem duplicar o before_tool acima (fontes independentes, mesmo call site).
            _pre_tc = getattr(self.plugin_hooks, "fire_blockable", None)
            _blocked = (self.hooks is not None and not self.hooks.fire(
                    "before_tool", {"tool": action.tool, "args": action.args}))
            if not _blocked and callable(_pre_tc):
                _blocked = not _pre_tc("pre_tool_call", tool=action.tool, args=action.args)
            if _blocked:
                step_n += 1
                _last_progress = _wt.monotonic()          # passo concluído (vetado) = atividade → reseta o anti-travamento
                t.steps.append(Step(step_n, action.tool, action.args, "vetado por hook", False, False))
                self._emit("step", n=step_n, tool=action.tool, args=action.args, ok=False, effect=False)
                self._reject(action,                                       # NATIVO → erro role=tool; JSON → user
                             f"erro: ação BLOQUEADA por hook de política ('{action.tool}'). Tente outra abordagem.",
                             f"AÇÃO BLOQUEADA por um hook de política: '{action.tool}'. Tente outra "
                             "abordagem ou declare task_blocked.")
                continue

            # --- Tool normal ---
            # PARALELO (item 20): se ESTA ação é leitura segura e ainda há um LOTE líder de leituras da
            # MESMA geração, roda o GRUPO em paralelo (ThreadPool) — N reads em ~1 read de wall-clock.
            # Os resultados voltam na ORDEM DE ENTRADA e cada step/_audit/observação é emitido SERIAL na
            # thread principal (determinístico). Mutação/aprovação NUNCA entram aqui (segue 1-por-turno).
            if (self._batch and all(_is_batchable(a) for a in (action, *self._batch))   # mutação NUNCA em
                    and not paths_collide([action, *self._batch])):                     # paralelo (race) → serial
                group = [action, *self._batch]
                self._batch = []                          # consumido inteiro no paralelo
                self._emit("parallel", n=len(group), tools=[a.tool for a in group])
                results = run_parallel(group, self.registry, self.ctx)
                for ga, gres in zip(group, results):      # emite em ordem de ENTRADA (determinístico)
                    self._fingerprints.append(self._fingerprint(ga))
                    step_n = self._handle_tool_result(t, step_n, ga, gres)
                _last_progress = _wt.monotonic()          # grupo executado = ATIVIDADE → reseta o anti-travamento
                continue
            self._fingerprints.append(fp)
            self._emit("tool_start", n=step_n + 1, tool=action.tool, args=action.args)   # terminal VIVO:
            try:                                           # anuncia ANTES de rodar (spinner+relógio na TUI)
                res = tool.run(action.args, self.ctx)
            except Exception as e:  # noqa: BLE001 — uma tool NUNCA derruba o harness
                res = ToolResult(False, f"erro na tool {action.tool}: {e}")
            step_n = self._handle_tool_result(t, step_n, action, res)
            _last_progress = _wt.monotonic()              # passo executado = ATIVIDADE → reseta o anti-travamento (trabalho longo nunca expira)

        return self._fail(t, f"orçamento de {self.budget.max_steps} passos esgotado")

    def _reject(self, action, native_err: str, user_msg: str) -> None:
        """Recusa uma ação NÃO-dispatchada. NATIVO (action tem call_id e a assistant acima ainda não echoou):
        injeta o erro como role=tool — o modelo vê a própria tool_call + o erro e se auto-corrige (paridade
        Hermes), e a sequência fica válida (echo atômico → sem tool_call órfã). Senão: mensagem de user."""
        _prev = self.messages[-1] if self.messages else None
        if (action is not None and getattr(action, "call_id", "") and isinstance(_prev, dict)
                and _prev.get("role") == "assistant" and "tool_calls" not in _prev):
            from okami.core.harness.parsing import _oai_tool_call
            _prev["tool_calls"] = [_oai_tool_call(
                {"id": action.call_id, "name": action.tool, "arguments": action.args})]
            if not _prev.get("content"):
                _prev["content"] = None
            self.messages.append({"role": "tool", "tool_call_id": action.call_id, "content": native_err})
        else:
            self.messages.append({"role": "user", "content": user_msg})

    def _handle_tool_result(self, t: Task, step_n: int, action: Action, res: ToolResult) -> int:
        """Pós-dispatch de UMA tool: conta o passo, emite eventos, audita, roda o circuit-breaker e o
        watchdog, e anexa a observação. Devolve o novo step_n. Compartilhado pelo caminho SERIAL e pelo
        PARALELO (item 20) — assim o lote read-only emite step/_audit/observação idêntico ao serial."""
        _transform = getattr(self.hooks, "transform_tool_result", None)   # duck-typed: hooks doubles em
        if callable(_transform):                          # teste que só implementam .fire() seguem OK
            res.output = self.hooks.transform_tool_result(action.tool, action.args, res.output)  # §11
        step_n += 1
        self._consecutive_arg_fails = 0               # dispatch de verdade → zera o contador de args malformados
        self._consecutive_action_failures = 0          # dispatch de verdade → zera o agregado também (WIN1)
        t.steps.append(Step(step_n, action.tool, action.args, res.output, res.effect, res.ok))
        self._emit("step", n=step_n, tool=action.tool, args=action.args, ok=res.ok, effect=res.effect,
                   out=(res.output or "")[:500])      # preview p/ o /replay (inspecionar o que retornou)
        # REFUND de passo (item 5, espelha o budget de poll): execute_code read-only é META-trabalho (rodou
        # N tools num ÚNICO passo de modelo) — não deve queimar o orçamento de passos. BOUNDED (cap =
        # max_poll_waits) p/ nunca virar loop infinito; o anti-loop/no-progress/stall continuam valendo.
        if (action.tool == "execute_code" and not res.effect
                and self._exec_refunds < self.budget.max_poll_waits):
            self._exec_refunds += 1
            step_n -= 1
        if action.tool not in _POLL_TOOLS:            # fez algo ≠ esperar processo → zera o budget de espera
            self._poll_waits = 0
        # OBSERVAÇÃO vai PRIMEIRO (antes de qualquer nudge): no rail NATIVO o resultado (role=tool) tem de
        # seguir IMEDIATAMENTE a mensagem assistant que echoou a tool_call — nudge de user no meio invalida a
        # sequência de function-calling. Pro rail JSON é indiferente (result antes do nudge é até mais natural).
        self._append_observation(step_n, action, res)
        self._inject_steer()
        if self._pending_loop_warn is not None:        # warn-before-block (WIN1): DEPOIS do result, nunca antes
            self.messages.append({"role": "user", "content": self._pending_loop_warn})
            self._pending_loop_warn = None
        # NÃO-PROGRESSO por OUTPUT (OpenClaw): tool read-only/poll que devolve a MESMA saída de novo
        # e de novo é I/O à toa — o anti-loop por args não pega (args podem até variar). Avisa 1x/tool.
        if res.ok and not res.effect:
            _same = self._progress.stalled_count(action.tool, res.output)
            if _same >= self._MAX_SAME_OUTPUT and action.tool not in self._stall_nudged:
                self._stall_nudged.add(action.tool)
                self._emit("no_progress", tool=action.tool, repeats=_same + 1)
                self.messages.append({"role": "user", "content":
                    f"'{action.tool}' devolveu a MESMA saída {_same + 1} vezes seguidas — repetir não vai "
                    "mudar o resultado. Faça algo DIFERENTE (outra abordagem/tool), ou ENTREGUE o que já "
                    "tem, ou declare task_blocked. Se era espera de processo, mate (process_kill) e siga."})
        self._audit(event="tool", step=step_n, tool=action.tool, args=self._args_brief(action.args),
                    ok=res.ok, effect=res.effect, out_chars=len(res.output))
        if self.hooks is not None:
            self.hooks.fire("after_tool", {"tool": action.tool, "args": action.args, "ok": res.ok,
                                           "effect": res.effect, "output": res.output,
                                           "out_chars": len(res.output or "")})
        _post_tc = getattr(self.plugin_hooks, "invoke", None)   # post_tool_call (bus unificada, §unify) —
        if callable(_post_tc):                                  # ADITIVO ao after_tool acima (fonte independente)
            _post_tc("post_tool_call", tool=action.tool, args=action.args, ok=res.ok,
                     effect=res.effect, output=res.output, out_chars=len(res.output or ""))

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
            transient = fail.kind == FailureKind.RATE_LIMIT      # 429/sobrecarga do modelo aux: NÃO é a tool
            if transient and self._failures[key] == 1:           # quebrada — avisa LOGO p/ não martelar igual
                self.messages.append({"role": "user", "content":
                    f"'{action.tool}' bateu no LIMITE/sobrecarga do provedor auxiliar (não é a ferramenta "
                    "quebrada). ESPERE alguns segundos antes de repetir IGUAL, ou siga com outra abordagem "
                    "se for urgente."})
            elif deterministic or self._failures[key] >= 3:
                why = ("BLOQUEADO (determinístico/sandbox): repetir não resolve."
                       if deterministic else
                       "CIRCUIT BREAKER: essa abordagem falhou 3x com o mesmo erro.")
                self.messages.append({"role": "user", "content":
                    f"{why} Mude de estratégia ou declare task_blocked."})

        # watchdog / stall (§3.3). PROGRESSO ≠ só efeito colateral: uma leitura/busca que DEU CERTO é
        # progresso (o agente aprendeu algo) — senão TODA análise/exploração (read/list/find/grep, que
        # têm effect=False) era nagueada com "escreva algo", e o modelo thrashava chutando caminho.
        # ...mas uma busca/listagem que NÃO ACHOU NADA ("(nada casou…", "(vazio") NÃO é progresso —
        # senão o modelo find-spammava com queries diferentes (loop só pega args idênticos) sem o nag.
        _empty = res.output.lstrip().startswith(("(nada", "(vazio"))
        _explored = res.ok and not _empty and (action.tool in _BATCHABLE_READONLY
                                                or (action.tool == "run_shell" and not res.effect))
        if res.effect or _explored:                # PROGRESSO real → zera o contador de anti-thrash de
            self._low_gain_compactions = 0         # compactação (senão 2 compactações de baixo ganho
            self._stall_breaks = 0                 # e o budget de sem-progresso (progresso solta o watchdog)
            #                                        DISTANTES, num trabalho longo legítimo, matavam o
            #                                        turno — review #1: o thrash só vale SEM progresso).
        if res.effect:                             # MUTAÇÃO bem-sucedida = progresso REAL → solta o budget
            self._loop_breaks = 0                  # de loop (paridade Hermes: não acumula loops de FASES
            #                                        DISTINTAS de uma tarefa longa e produtiva num _fail
            #                                        prematuro). Loop patológico não tem effect → segue pego.
        self._steps_without_effect = 0 if (res.effect or _explored) else self._steps_without_effect + 1
        if self._steps_without_effect >= self.budget.stall_limit:
            self._steps_without_effect = 0
            self._stall_breaks += 1
            self._emit("stall", steps=self.budget.stall_limit, breaks=self._stall_breaks)
            if self._stall_breaks >= self.budget.max_loop_breaks:   # nudge não resolveu N vezes → não nudga
                self._stall_exceeded = True                         # mais p/ sempre: main loop escala/falha
            else:
                self.messages.append({"role": "user", "content":
                    "SEM PROGRESSO: vários passos SEM RESULTADO (reads falhando / chutando caminho). Se está "
                    "explorando, MAPEIE antes: list_dir na raiz, ou run_shell `find . -type f -name '*.py' | "
                    "head -80` — depois leia os arquivos CERTOS. Se a tarefa pede mudança, escreva/rode algo. "
                    "Ou task_blocked."})

        return step_n

    def _inject_steer(self) -> None:
        """/steer (INJETA no turno em curso, NÃO cancela — distinto do /busy interrupt): drena o texto
        pendente do dono (via `_steer_source`, dono do lock é o gateway) e ANEXA à observação que acabou
        de ser appendada, envolto no marcador (paridade Hermes). Sem uma mensagem tool/user pra anexar
        (ex.: observação multimodal, content=lista) o texto NÃO SE PERDE — fica em `_deferred_steer` pro
        próximo passo tentar de novo."""
        txt = self._deferred_steer or self._steer_source()
        self._deferred_steer = None
        if not txt:
            return
        last = self.messages[-1] if self.messages else None
        if isinstance(last, dict) and last.get("role") in ("user", "tool") and isinstance(last.get("content"), str):
            last["content"] = (last["content"] or "") + f"\n\n{STEER_MARKER_OPEN}\n{txt}\n{STEER_MARKER_CLOSE}"
            self._emit("steer", chars=len(txt))
        else:                                          # nada pra anexar agora → guarda p/ o PRÓXIMO passo
            self._deferred_steer = txt

    def _append_observation(self, step_n: int, action: Action, res: ToolResult) -> None:
        """Anexa a OBSERVAÇÃO da tool ao histórico. Multimodal (item 6): se a tool devolveu blocos
        nativos em res.content (ex.: vision com imagem), anexa-os DIRETO como mensagem 'user' — sem
        passar pelo corte por orçamento de chars (que é p/ texto; truncar bloco de imagem o corromperia).
        Caso normal (texto): aplica o budget (teto por-resultado + teto AGREGADO do turno)."""
        if res.content is not None:                  # tool-result MULTIMODAL → blocos nativos, sem truncar
            # Bloco de imagem NÃO é truncável, mas CONTA no orçamento agregado do turno (item 6/14):
            # se o turno já estourou o teto, não enfia mais uma imagem nativa (blowup de contexto) —
            # vira placeholder textual. Estima bytes pelo data-URL (onde mora o peso da imagem).
            def _approx(blocks):
                try:
                    return sum(len(b.get("image_url", {}).get("url", "")) + len(b.get("text", ""))
                               if isinstance(b, dict) else len(str(b)) for b in blocks)
                except Exception:  # noqa: BLE001
                    return 0
            if self._obs_chars > self.budget.max_turn_tool_chars:
                self.messages.append({"role": "user", "content":
                    "[imagem omitida — teto de contexto do turno atingido; abra novo turno p/ analisá-la]"})
                return
            self._obs_chars += _approx(res.content)
            self.messages.append({"role": "user", "content": res.content})
            return
        obs_res = res                                # budget de contexto: trunca output gigante (persiste o completo)
        # Teto AGREGADO do turno (pesquisa #5 item 15): estourou → até output médio (>2K) é
        # persistido, com preview curto (1K). O teto por-resultado sozinho deixava N resultados
        # médios inundarem o contexto.
        _over_turn = self._obs_chars > self.budget.max_turn_tool_chars
        _limit = 2000 if _over_turn else self._tool_result_budget
        if len(res.output) > _limit:
            saved = self._persist_large_output(step_n, res.output)
            from okami.core.harness.persisted import persisted_output_wrapper
            wrapped = persisted_output_wrapper(saved, len(res.output),
                                               res.output[:1000 if _over_turn else self._preview_cap])
            obs_res = ToolResult(res.ok, wrapped, res.effect)   # tag estruturada + read_file(offset/limit)
        _obs = format_observation(step_n, action.tool, obs_res, workspace=self.ctx.workspace,
                                  result_budget=self._tool_result_budget)
        self._obs_chars += len(_obs)
        # FUNCTION-CALLING NATIVO (paridade Hermes): se a ação veio de uma tool_call nativa E a mensagem
        # logo acima é a assistant deste turno, ECHOA a tool_call nela (ATÔMICO: só agora que há resposta →
        # rejeição nunca vira tool_call órfã) e devolve o resultado como role=tool. Senão, observação user
        # (rail JSON, ou guard de segurança se a sequência não bater).
        _prev = self.messages[-1] if self.messages else None
        if (getattr(action, "call_id", "") and isinstance(_prev, dict)
                and _prev.get("role") == "assistant" and "tool_calls" not in _prev):
            from okami.core.harness.parsing import _oai_tool_call
            _prev["tool_calls"] = [_oai_tool_call(
                {"id": action.call_id, "name": action.tool, "arguments": action.args})]
            if not _prev.get("content"):
                _prev["content"] = None                # content vazio + tool_calls → null (alguns providers exigem)
            self.messages.append({"role": "tool", "tool_call_id": action.call_id, "content": _obs})
        else:
            self.messages.append({"role": "user", "content": _obs})

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
            msg = strip_think_blocks(action.args.get("message") or action.args.get("summary") or "")
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
            # Anti-bail (rumo ao Hermes, que NEM tem tool de 'blocked'): se está desistindo CEDO — tarefa
            # PEDE ação, quase nenhum passo executado, e NENHUMA tool falhou de verdade — empurra a tentar
            # UMA vez (a "sensação de incompetência" é o modelo fraco bailando sem tentar). Bloqueio
            # GENUÍNO (já tentou OU uma tool falhou de verdade) é honrado na hora, sem forçar spin.
            if (self._action_expected and not self._blocked_nudged
                    and len(t.steps) < 2 and not self._failures):
                self._blocked_nudged = True
                self._emit("blocked_rejected", reason=action.args.get("reason", ""))
                self.messages.append({"role": "user", "content":
                    "Antes de declarar bloqueio: você quase não TENTOU. Faça primeiro o lookup/abordagem "
                    "óbvia (find_files/read_file/run_shell/browse/use_skill) — só declare task_blocked se "
                    "uma ferramenta REAL falhar e não houver alternativa. Tente AGORA, sem pedir permissão."})
                return None
            t.state = TaskState.BLOCKED
            t.reason = action.args.get("reason", "(sem razão)")
            self._emit("blocked", reason=t.reason)
            return t
        if action.tool == "need_input":
            t.state = TaskState.NEEDS_INPUT
            t.reason = action.args.get("question", "(sem pergunta)")
            opts = action.args.get("options")          # clarify (Hermes): escolha numerada — a pessoa
            if isinstance(opts, list) and opts:        # responde "2" em vez de digitar parágrafo
                rendered = "\n".join(f"{i}. {o}" for i, o in enumerate(opts, 1))
                t.reason = f"{t.reason}\n{rendered}\n(responda com o número ou escreva outra opção)"
            self._emit("need_input", question=t.reason)
            return t
        if action.tool == "task_complete":
            ok, missing = check_exit(t.exit_criteria, self.ctx)
            if ok:
                _summary = str(action.args.get("summary", "")).strip()
                _real = len([s for s in t.steps if s.tool not in _REPORT_META])
                # backstop: pediu AÇÃO mas declarou CONCLUÍDO sem rodar NENHUMA ferramenta (pulou direto pro
                # task_complete, não pelo 'respond') → re-pede 1x. Espelha o guard do ramo respond (l.829);
                # modelo fraco às vezes "declara vitória" de memória com exit_criteria vazio + 0 trabalho.
                if self._action_expected and not self._nudged_action and not t.steps:
                    self._nudged_action = True
                    self._emit("complete_rejected", missing=["concluído sem rodar nenhuma ferramenta"])
                    self.messages.append({"role": "user", "content":
                        "Você declarou CONCLUÍDO sem usar nenhuma ferramenta. O pedido exige AGIR: leia/rode/"
                        "analise o que for preciso e ENTREGUE o resultado real — não conclua de memória."})
                    return None
                if (self._action_expected and not self._thin_nudged
                        and _deliverable_too_thin(t.goal, _summary, _real)):   # entrega rasa → re-pede 1x
                    self._thin_nudged = True
                    self._emit("complete_rejected", missing=["entrega rasa vs trabalho feito"])
                    self.messages.append({"role": "user", "content": _THIN_NUDGE.format(n=_real)})
                    return None
                # VERIFY-ON-STOP mínimo (WIN2, espírito Hermes verification_stop.py): exit_criteria VAZIO
                # (nada VERIFICÁVEL declarado) + já houve EFEITO real nesta corrida (escreveu/editou/rodou
                # algo que muda estado) + nenhum run_shell BEM-SUCEDIDO depois do último efeito → o modelo
                # está encerrando sem checar o próprio trabalho. Empurra UMA vez; na 2ª tentativa aceita
                # DE QUALQUER JEITO (sem risco de loop — é um nudge, não um gate como check_exit).
                _pre_verify = getattr(self.plugin_hooks, "invoke", None)   # pre_verify (bus unificada, §unify):
                if callable(_pre_verify):                                  # plugin pode empurrar p/ continuar
                    for _ret in _pre_verify("pre_verify", task=t, summary=_summary):
                        _cont = (_ret.get("action") == "continue" or _ret.get("decision") == "block") \
                            if isinstance(_ret, dict) else False
                        if _cont:
                            _msg = _ret.get("message") or _ret.get("reason") or "continue verificando antes de concluir."
                            self.messages.append({"role": "user", "content": _msg})
                            return None
                if (not t.exit_criteria and not self._verify_nudged
                        and any(s.effect for s in t.steps) and not _verified_since_last_effect(t.steps)):
                    self._verify_nudged = True
                    self._emit("complete_rejected", missing=["sem verificação após o último efeito"])
                    self.messages.append({"role": "user", "content":
                        "Antes de concluir: você fez mudança(s) mas não vi um comando de VERIFICAÇÃO rodar "
                        "depois delas. Verifique o resultado antes de concluir — rode um comando que comprove "
                        "(teste, lint, o próprio comando/arquivo alterado) e SÓ AÍ chame task_complete de novo."})
                    return None
                t.state = TaskState.COMPLETE
                t.result = _summary or "(sem resumo)"
                self._extract_on_complete(t)
                self._emit("complete", summary=t.result)
                return t
            # rejeitado: 'concluído' falso (§3.4)
            self._stats["gate_rejections"] += 1
            self._emit("complete_rejected", missing=missing)
            _miss = "\n".join(f"  - {m}" for m in missing)
            self._reject(action,                                           # NATIVO → erro role=tool; JSON → user
                         f"erro: task_complete REJEITADO — critérios não satisfeitos:\n{_miss}\nContinue.",
                         f"task_complete REJEITADO — critérios de saída não satisfeitos:\n{_miss}"
                         "\nContinue trabalhando para satisfazê-los.")
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
        self._consecutive_arg_fails = 0
        self._consecutive_action_failures = 0            # WIN1: modelo NOVO começa sem bagagem de falha agregada
        self._loop_warned.clear()
        self._fingerprints.clear()
        self._batch = []                                # descarta ações do lote antigo: o modelo NOVO reavalia
        #                                                 do zero (ação órfã do modelo anterior = incoerência)
        self._emit("escalate", why=why)
        self.messages.append({"role": "user", "content":
            "Trocando para um modelo mais forte. Reavalie o estado e tome a PRÓXIMA "
            "ação concreta (um bloco json), ou declare task_blocked."})
        return True

    def _extract_on_complete(self, t: Task) -> None:
        """Extract (§6.2 passo 4): promove o resumo da tarefa para a memória RANKED (não MEMORY.md).

        Era gravação MECÂNICA de 'goal → result' pra TODA tarefa com ≥1 passo com efeito — o mesmo
        anti-padrão já diagnosticado e corrigido em `learning.reflect` (docstring de
        okami/learning/__init__.py:22-34): memória de longo prazo só guarda o que é DURÁVEL e
        GENERALIZÁVEL, não post-mortem re-descobrível de toda tarefa (isso enchia o recall de lixo que
        sequestrava o pedido seguinte). Alinhado ao mesmo padrão: só passa quem teve trabalho REAL
        (≥2 passos com efeito — 1 mutação isolada é trivial demais pra virar 'fato'), e SÓ vai pra
        memória semântica via policy.prepare (que já filtra temp/do-not-capture/etc). MEMORY.md deixou
        de receber escrita automática daqui — arquivo é só p/ remember/remember_user/reflect; histórico
        de tarefa (o que rodou, quando) já é buscável via sessão (session search), não via memória
        semântica."""
        if self.memory is None or not t.result:
            return
        if len([s for s in t.steps if s.effect]) < 2:   # trabalho trivial (0-1 efeito) → não persiste
            return
        from okami.memory.policy import prepare
        item = prepare(f"{t.goal} → {t.result}", source="task", kind="summary")   # passa pela política
        if item is not None:
            self.memory.write(item)
            self.events.emit("memory_write", kind=item.kind, text=item.text[:200])

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
            comp = as_completion(self._do_generate(self.messages, self._action_schema))
            txt = comp.text or ""
            cands = [prose_outside_action(txt), txt]
            act = _action_from_tool_calls(comp.tool_calls) or parse_action(txt)
            if act and act.tool in ("respond", "task_complete"):   # modelo embrulhou o relatório num respond
                cands.insert(0, str(act.args.get("message") or act.args.get("summary") or ""))
            best = max((c.strip() for c in cands), key=len, default="")
            return best if len(best) >= 40 else ""
        except Exception:  # noqa: BLE001 — salvage é best-effort; se falhar, cai no FAILED mudo normal
            return ""
