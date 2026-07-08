"""Camada de providers do Okami, sobre LiteLLM.

Fase 0: uma interface única (`complete` / `stream_complete`) que normaliza a chamada
para qualquer backend (Codex/GPT, Claude, MiniMax, MiMo, LMStudio local).
Nas próximas fases isso ganha router por custo/capacidade, fallback/rotação (§5) e
o capability profile adaptativo (§3.5).
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator

import litellm

from okami.llm import errors as _err
from okami.llm import transports
from okami.llm.retry import retry_delay
from okami.llm.usage import Completion, as_completion, normalize_usage
from okami.config import OkamiConfig, ProviderConfig


class EmptyResponse(RuntimeError):
    """Provider devolveu resposta vazia — tratado como falha (retry/failover), não como sucesso."""


_SURROGATE = re.compile(r"[\ud800-\udfff]")


def _sanitize_messages(messages: list[dict], *, strip_fields: bool = True) -> list[dict]:
    """Remove surrogates UTF-16 soltos + control chars que estouram `.encode('utf-8')`/`json.dumps` do SDK
    ANTES da requisição (ex.: histórico de modelo local byte-level). Cobre content STR e LISTA-DE-BLOCOS
    (multimodal). Um char ruim no transcript não pode travar TODO turno até o /new. Fail-open.
    `strip_fields=False` mantém campos não-padrão (reasoning_items) p/ o replay do Codex."""
    from okami.llm.sanitize import sanitize_messages
    return sanitize_messages(messages, strip_fields=strip_fields)


# Famílias de reasoner que EXIGEM reasoning_content de volta em msg assistant com tool_calls (thinking-mode):
# DeepSeek-reasoner/R1, Kimi (Moonshot k2/kimi-thinking), Xiaomi MiMo. Sem o campo → HTTP 400 multi-turn.
_REASONING_ECHO_RE = re.compile(r"deepseek.*(reasoner|r1|v3\.\d)|\bkimi\b|moonshot|\bmimo\b", re.I)


def _ensure_reasoning_echo(messages: list[dict], pc) -> list[dict]:
    """Garante reasoning_content em CADA msg assistant COM tool_calls quando o provider exige (port do
    chat_completion_helpers do Hermes). Sem isso, DeepSeek-reasoner/Kimi/MiMo dão HTTP 400 no multi-turno
    ('The reasoning_content in the thinking mode must be passed back'). Placeholder ' ' (fallback do Hermes)
    quando não há reasoning real — NÃO sobrescreve um existente. 'strip' desliga; 'require' força p/ qualquer
    modelo; 'auto' (default) detecta a família. Copia (não muta o histórico)."""
    mode = (getattr(pc, "reasoning_echo", "auto") or "auto").lower()
    if mode == "strip":
        return messages
    if mode != "require" and not _REASONING_ECHO_RE.search(getattr(pc, "model", "") or ""):
        return messages                              # 'auto' + família que não exige → nada muda
    out = []
    for m in messages or []:
        if (isinstance(m, dict) and m.get("role") == "assistant" and m.get("tool_calls")
                and not m.get("reasoning_content")):
            m = {**m, "reasoning_content": " "}      # campo presente satisfaz o contrato (sem custo de CoT real)
        out.append(m)
    return out

# Tolera params não suportados por um provider específico e reduz ruído de log.
litellm.drop_params = True
litellm.suppress_debug_info = True


def _effective_model(pc: ProviderConfig, model: str | None) -> str:
    """Resolve o model efetivo.

    Se o override vier sem prefixo de provider (ex.: '-m qwen3.5-2b-mtp'), herda o
    prefixo de roteamento do model configurado (ex.: 'openai/...') para o LiteLLM
    saber rotear. Override com '/' explícito é respeitado como veio.
    """
    if not model:
        return pc.model
    if "/" in model:
        return model
    if "/" in pc.model:
        prefix = pc.model.split("/", 1)[0]
        return f"{prefix}/{model}"
    return model


# Janela de contexto default por tier (tokens), quando o provider não declara context_window.
_TIER_WINDOW = {"strong": 128000, "weak": 32000, "local": 8192, "unknown": 16000}
# Fração da janela em que disparamos a auto-compaction (§6.4). Ex.: 250K→~180K ≈ 0.72.
COMPACT_RATIO = 0.72
# Teto REALISTA da janela p/ tier local/weak. A janela do catálogo (ex.: minimax=1M) é ARQUITETURAL —
# um modelo local no LMStudio NÃO serve 1M de contexto rápido. Sem teto, a auto-compaction (proporcional
# à janela) só dispararia a ~2.88M chars → o histórico inteiro era REENVIADO a cada passo (lentidão
# mortal, 1.5M tok de entrada). Capamos p/ a compaction disparar cedo. Dono sobe via `context_window:`.
_LOCAL_WINDOW_CAP = 32_768
# TETO DE TRABALHO (2026-07-08, uso real): mesmo num modelo de janela GIGANTE (minimax M3 = 1M tokens,
# setado explícito no config → bypassa o _LOCAL_WINDOW_CAP), NÃO carregamos ~720K tokens de contexto a
# cada passo. Um log real de gerar 1 PDF acumulou 1.8M tok porque a compaction só dispararia a 0.72×1M.
# A janela do modelo segue sendo o limite DURO; este é só o working-set em que COMEÇAMOS a compactar —
# manter enxuto deixa cada passo rápido/barato. 180K tok ≈ pilha de trabalho grande e ainda sã.
_WORKING_CTX_CAP_TOKENS = 180_000


def context_window_tokens(pc: ProviderConfig) -> int:
    if pc.context_window:                              # explícito na config SEMPRE vence
        return pc.context_window
    from okami.llm.model_catalog import model_info     # janela REAL do modelo (models.dev-lite)
    info = model_info(pc.model)
    win = info.context_window if info else _TIER_WINDOW.get(pc.tier, 16000)
    if pc.tier in ("local", "weak"):                  # nominal do catálogo não vale p/ deploy local
        win = min(win, _LOCAL_WINDOW_CAP)
    return win


def compaction_threshold_chars(pc: ProviderConfig, ratio: float = COMPACT_RATIO) -> int:
    """Quando comprimir (em chars): proporcional à janela REAL do modelo (anti-overflow), MAS capado num
    working-set são (_WORKING_CTX_CAP_TOKENS) — num modelo de janela gigante não arrastamos 720K tokens
    de contexto por passo (lento/caro). O menor entre os dois vence."""
    window_based = int(context_window_tokens(pc) * pc.chars_per_token * ratio)
    working_cap = int(_WORKING_CTX_CAP_TOKENS * pc.chars_per_token)
    return min(window_based, working_cap)


def _build_messages(prompt: str, system: str | None) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return messages


# Conversão effort → orçamento de tokens p/ providers no estilo "thinking" (Anthropic). Escada
# conservadora: o budget cresce com o esforço pedido (item 12). minimal fica de fora — esse estilo
# começa em low; se vier minimal tratamos como low (menor budget útil).
_EFFORT_BUDGET = {"minimal": 1024, "low": 4096, "medium": 8192, "high": 16384}


def _effort_to_budget(effort: str) -> int:
    return _EFFORT_BUDGET.get((effort or "").strip().lower(), 8192)


def _apply_reasoning(kw: dict, pc: ProviderConfig) -> None:
    """Molda o esforço de raciocínio conforme o `reasoning_style` declarado do provider (item 12).

    Lê o effort JÁ resolvido em kw["reasoning_effort"] (default de pc + override + clamp já aplicados) e:
      - "thinking": vira kw["thinking"]={"type":"enabled","budget_tokens":N}; remove reasoning_effort.
                    Sem effort declarado → não inventa budget (remove os dois).
      - "none":     remove reasoning_effort E thinking (modelo que recusa ambos).
      - "" / "reasoning_effort": mantém reasoning_effort (estilo OpenAI/litellm); remove thinking se
                    algum override o injetou (reasoning XOR thinking — nunca os dois juntos)."""
    style = (pc.reasoning_style or "").strip().lower()
    effort = kw.get("reasoning_effort", "")
    if style == "none":
        kw.pop("reasoning_effort", None)
        kw.pop("thinking", None)
        return
    if style == "thinking":
        kw.pop("reasoning_effort", None)
        if effort:                                   # sem effort → não inventa budget (sem thinking)
            kw["thinking"] = {"type": "enabled", "budget_tokens": _effort_to_budget(effort)}
        else:
            kw.pop("thinking", None)
        return
    # "" / "reasoning_effort": estilo padrão — reasoning_effort manda, thinking nunca acompanha.
    kw.pop("thinking", None)


def _strip_tool_images(messages: list[dict]) -> list[dict]:
    """Remove blocos image_url de mensagens role=="tool" (item 12, vision_tool_messages=False) — alguns
    providers dão 400 com imagem dentro de resultado de tool. Só toca role=="tool"; user/assistant
    (vision normal) ficam intactos. Lista NOVA (não muta o histórico do chamador)."""
    out = []
    for m in messages:
        c = m.get("content")
        if m.get("role") == "tool" and isinstance(c, list):
            kept = [b for b in c if not (isinstance(b, dict) and b.get("type") == "image_url")]
            m = {**m, "content": kept}
        out.append(m)
    return out


def _kwargs(
    pc: ProviderConfig,
    messages: list[dict[str, str]],
    *,
    stream: bool,
    model: str | None,
    **overrides,
) -> dict:
    if not pc.vision_tool_messages:                  # provider recusa imagem em msg de tool (item 12)
        messages = _strip_tool_images(messages)
    kw: dict = {
        "model": _effective_model(pc, model),
        "messages": messages,
        "stream": stream,
    }
    if pc.api_base:
        kw["api_base"] = pc.api_base
    key = overrides.pop("_api_key", None) or pc.resolved_key()   # credential pool injeta a chave da vez
    if key:
        kw["api_key"] = key
    kw.update(pc.params)
    if pc.omit_temperature:                          # modelo que SÓ aceita o default → tira de params
        kw.pop("temperature", None)
    if pc.reasoning_effort:                          # default do provider (override /think ainda vem abaixo)
        kw["reasoning_effort"] = pc.reasoning_effort
    kw.update(overrides)                             # override por chamada (/think) vence o default
    if pc.omit_temperature:                          # de novo: um override não pode REINTRODUZIR temp
        kw.pop("temperature", None)
    if kw.get("reasoning_effort"):                   # CLAMP do effort RESOLVIDO (default ou override) ao
        from okami.llm.model_catalog import clamp_effort   # teto do modelo — cost-safe (item 15a): high→medium
        kw["reasoning_effort"] = clamp_effort(_effective_model(pc, model), kw["reasoning_effort"])
    _apply_reasoning(kw, pc)                          # reasoning_style: thinking XOR reasoning_effort (item 12)
    if "num_ctx" not in kw:                           # Ollama default 2048 TRUNCA silencioso → descobre o teto
        from okami.llm.local_ctx import resolve_num_ctx   # REAL e seta num_ctx (só local; cloud devolve None)
        nc = resolve_num_ctx(pc, kw["model"])
        if nc:
            kw["num_ctx"] = nc
    routing = getattr(pc, "provider_routing", None)   # hints de roteamento OpenRouter → extra_body.provider
    if routing and "openrouter.ai" in (pc.api_base or "").lower():   # SÓ p/ base OpenRouter (não quebra outros)
        kw.setdefault("extra_body", {})["provider"] = dict(routing)
    kw.setdefault("timeout", resolve_timeout(pc))     # FALHA RÁPIDO por TIER (harness encolhe+failover)
    return kw


# Timeout (s) por tier quando `timeout_seconds` não vem explícito na config. LOCAL (LMStudio/Ollama/
# llama.cpp) é sabidamente mais lento (CPU/GPU do usuário, sem escala de datacenter) → folga bem maior;
# nuvem mantém o corte curto (era 150s FIXO p/ todo mundo — penalizava reasoning/contexto grande de
# provider rápido só p/ compensar o local devagar, ou o contrário: local devagar cortava cedo demais).
_TIER_TIMEOUT = {"local": 1800.0}
_DEFAULT_TIMEOUT = 600.0


def resolve_timeout(pc: ProviderConfig) -> float:
    """Timeout (s) da chamada: explícito na config SEMPRE vence; senão default por tier (local ganha
    folga; nuvem/weak/strong/unknown ficam no corte padrão de nuvem). Fail-fast continua o padrão —
    só o número muda por capacidade REAL do backend."""
    if pc.timeout_seconds is not None:
        return pc.timeout_seconds
    return _TIER_TIMEOUT.get((pc.tier or "").lower(), _DEFAULT_TIMEOUT)


_key_cursor: dict[str, int] = {}      # rotação round-robin do pool de chaves por provider
_key_cooldown: dict[str, float] = {}  # chave -> epoch até quando está parada (tomou 429)


def _available_pool(pc: ProviderConfig, now: float) -> list[str]:
    """Chaves não-parqueadas (cooldown in-memory + pool PERSISTENTE cross-restart/processo); se TODAS
    em cooldown, devolve o pool cheio (não trava). O pool persistente (item 20) sobrevive ao restart."""
    live = [k for k in pc.key_pool() if _key_cooldown.get(k, 0.0) <= now]
    try:
        from okami.llm import cred_pool
        live = [k for k in live if k in set(cred_pool.available(pc.name, live, now=now))]
    except Exception:  # noqa: BLE001 — pool persistente é otimização, nunca trava
        pass
    return live or pc.key_pool()


def _rotate_key(pc: ProviderConfig, now: float | None = None) -> str | None:
    now = time.time() if now is None else now
    pool = _available_pool(pc, now)
    if len(pool) <= 1:
        return pool[0] if pool else None
    i = _key_cursor.get(pc.name, 0) % len(pool)
    _key_cursor[pc.name] = (i + 1) % len(pool)    # avança normalizado: não cresce sem teto nem desbalanceia
    return pool[i]                                #   a distribuição quando o pool encolhe (chave parqueada)


_PARK_TTL = {"rate_limit": 3600.0, "billing": 6 * 3600.0}   # billing dura mais: crédito não volta sozinho


def _park_key(key: str | None, ce, now: float | None = None, ttl: float | None = None,
              provider: str | None = None) -> None:
    """Chave com 429/billing/auth → parqueia in-memory + no pool PERSISTENTE (item 20: cross-restart/
    processo; status ok/exhausted/dead por classe de erro)."""
    if not key:
        return
    if ce.reason in _PARK_TTL:
        _key_cooldown[key] = (time.time() if now is None else now) + (ttl or _PARK_TTL[ce.reason])
    if provider:                                      # persistente: sobrevive ao restart, guarda só fingerprint
        try:
            from okami.llm import cred_pool
            cred_pool.mark(provider, key, ce.reason, now=now)
        except Exception:  # noqa: BLE001 — pool persistente nunca trava o turno
            pass


def complete(
    cfg: OkamiConfig,
    prompt: str,
    *,
    provider: str | None = None,
    system: str | None = None,
    model: str | None = None,
    **overrides,
) -> str:
    pc = cfg.provider(provider)
    messages = _build_messages(prompt, system)
    via = transports.dispatch(pc, messages, model, overrides)
    if via is not None:
        return as_completion(via).text
    resp = litellm.completion(**_kwargs(pc, messages, stream=False, model=model, **overrides))
    return _message_text(resp.choices[0].message)


def _stringify_content(content) -> str:
    """`content` → string. Server OpenAI-compat/local (LMStudio, shims) às vezes devolve LISTA de blocos
    ([{type:text,text:..}]) ou dict em vez de string — sem normalizar, o `.strip()` abaixo estoura."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict):
                parts.append(str(b.get("text") or b.get("content") or ""))
            elif isinstance(b, str):
                parts.append(b)
        return "".join(parts)
    if isinstance(content, dict):
        return str(content.get("text") or content.get("content") or "")
    return "" if content is None else str(content)


def _message_text(message) -> str:
    """Texto da resposta = `content`. Se vier VAZIO, cai no `reasoning_content`/`reasoning` — modelos de
    REASONING (MiniMax-M3, DeepSeek-R1…) jogam a saída no campo de pensamento e deixam `content` vazio;
    sem este fallback a fala se perde (output só-reasoning → resposta vazia / '(COMPLETE)' mudo)."""
    txt = _stringify_content(getattr(message, "content", None))
    if txt.strip():
        return txt
    for attr in ("reasoning_content", "reasoning"):
        r = getattr(message, attr, None)
        if isinstance(r, str) and r.strip():
            return r
    # alguns SDKs expõem em provider_specific_fields / model_extra
    for bag in (getattr(message, "provider_specific_fields", None), getattr(message, "model_extra", None)):
        if isinstance(bag, dict):
            for attr in ("reasoning_content", "reasoning"):
                r = bag.get(attr)
                if isinstance(r, str) and r.strip():
                    return r
    return txt


_ANTHROPIC_MODEL = re.compile(r"(^|/)(anthropic/|claude\b|claude-)", re.I)


def _cache_marker() -> dict:
    """Marcador cache_control. Default 5min; OKAMI_CACHE_TTL=1h habilita o TTL estendido de 1h (#9) —
    daemon/gateway ocioso entre mensagens sobrevive ao cache em vez de re-pagar o prefixo. Opt-in
    (default = comportamento atual) p/ não arriscar a rota Claude principal."""
    import os
    m = {"type": "ephemeral"}
    if os.getenv("OKAMI_CACHE_TTL", "").strip().lower() in ("1h", "60m", "3600"):
        m["ttl"] = "1h"
    return m


def _can_carry_cache_marker(msg: dict) -> bool:
    """A mensagem tem onde COLAR o cache_control (paridade Hermes `_can_carry_marker`,
    agent/prompt_caching.py:52-73)? Em turno tool-heavy, uma mensagem assistant que é SÓ tool_calls
    (sem texto) ou um tool-result vazio tem `content` None/"" — o litellm/Anthropic não tem um bloco de
    TEXTO pra receber o marcador ali, e gastar um dos 4 breakpoints numa mensagem que o provider vai
    IGNORAR é desperdício (sobra menos breakpoint p/ conteúdo real). Só carrega marcador: string
    não-vazia, ou lista não-vazia com PELO MENOS um bloco de TEXTO não-vazio em QUALQUER posição — espelha
    a busca-de-trás-pra-frente que `apply_prompt_caching` faz abaixo (a marca vai no último bloco de TEXTO,
    não necessariamente o último item da lista — ex.: [texto, imagem] marca o texto, não a imagem)."""
    c = msg.get("content")
    if isinstance(c, str):
        return bool(c.strip())
    if isinstance(c, list) and c:
        return any(isinstance(p, dict) and p.get("type") == "text" and bool((p.get("text") or "").strip())
                   for p in c)
    return False


def apply_prompt_caching(messages: list[dict], model: str) -> list[dict]:
    """Prompt caching EXPLÍCITO da Anthropic (pesquisa #5 item 58): marca system + as 3 últimas
    mensagens COM CONTEÚDO REAL (`_can_carry_cache_marker`) com `cache_control: ephemeral` (máx. 4
    breakpoints da API) — ~75% de economia de input em conversa longa. Só p/ modelos Claude via
    litellm; outros providers não conhecem o formato (devolve a lista ORIGINAL, sem custo). Transports
    CLI/OAuth não passam por aqui."""
    if not _ANTHROPIC_MODEL.search(model or ""):
        return messages
    out = [dict(m) for m in messages]
    targets = {0} if out and out[0].get("role") == "system" else set()
    # candidatos: mensagens NÃO-system que realmente carregam o marcador (pula tool_call/tool_result
    # vazio — mirror do Hermes: gastar breakpoint numa mensagem ignorada pelo provider é desperdício).
    carriers = [i for i in range(len(out)) if i not in targets and _can_carry_cache_marker(out[i])]
    remaining = 4 - len(targets)
    targets |= set(carriers[-remaining:]) if remaining > 0 else set()
    for i in targets:
        c = out[i].get("content")
        if isinstance(c, str):
            out[i]["content"] = [{"type": "text", "text": c, "cache_control": _cache_marker()}]
        elif isinstance(c, list) and c:
            parts = [dict(p) for p in c]
            # marca o último bloco de TEXTO (não uma imagem — colar cache_control num image_url é
            # frágil e pode dar 400 / cache ignorado em turnos com vision; review #5).
            ti = next((j for j in range(len(parts) - 1, -1, -1)
                       if isinstance(parts[j], dict) and parts[j].get("type") == "text"), None)
            if ti is not None:
                parts[ti] = {**parts[ti], "cache_control": _cache_marker()}
                out[i]["content"] = parts
    return out


def _response_format(pc: ProviderConfig, response_schema: dict | None) -> dict | None:
    """Constrained decoding (§3.5): força JSON válido em modelos json_constrained. NÃO no rail nativo —
    response_format (json_object) + tools= confunde o provider; nativo já tem a garantia estrutural."""
    from okami.llm.native_capability import native_supported
    if response_schema and pc.effective_tool_mode() == "json_constrained" and not native_supported(pc):
        return {
            "type": "json_schema",
            "json_schema": {"name": "okami_action", "schema": response_schema, "strict": False},
        }
    return None


def _extract_tool_calls(msg) -> list[dict]:
    """tool_calls nativos do litellm → [{"id","name","arguments"}] (vazio = sem function-calling)."""
    out = []
    for tc in (getattr(msg, "tool_calls", None) or []):
        fn = getattr(tc, "function", None)
        out.append({"id": getattr(tc, "id", "") or "",
                    "name": (getattr(fn, "name", "") if fn else "") or "",
                    "arguments": (getattr(fn, "arguments", "") if fn else "") or ""})
    return out


_SCHEMA_ERR_MARKERS = ("grammar", "json schema", "invalid schema for function", "schema must have type",
                       "not allowed at the same level", "tool schema", "failed to parse schema",
                       "tools[", "function parameters")


def _is_tool_schema_error(e) -> bool:
    """O erro do provider é sobre o SCHEMA das tools tropeçar no grammar-converter (não auth/rate/etc)?
    → vale re-sanitizar agressivo e retentar 1x (paridade Hermes reactive strip+retry)."""
    s = (str(getattr(e, "message", "") or "") + " " + str(e)).lower()
    return any(m in s for m in _SCHEMA_ERR_MARKERS)


def _complete_one(pc, messages, model, response_schema, overrides, raw_messages=None) -> Completion:
    # só passa raw_messages quando há (codex c/ replay) → mantém compat com mocks de dispatch de 4 args
    via = (transports.dispatch(pc, messages, model, overrides, raw_messages=raw_messages)
           if raw_messages is not None else transports.dispatch(pc, messages, model, overrides))
    if via is not None:
        return as_completion(via)
    messages = apply_prompt_caching(messages, _effective_model(pc, model))   # Claude → cache explícito
    rf = _response_format(pc, response_schema)
    if rf is not None:
        overrides.setdefault("response_format", rf)
    from okami.llm.native_capability import native_supported
    _native_sent = False
    if native_supported(pc):                                # tool-calling nativo — SÓ se o probe confirmou
        if "tools" not in overrides:                        # o runner pode JÁ passar o registry FILTRADO (surface/
            from okami.core.tools import default_registry, openai_tools   # disponibilidade) — não sobrescreve;
            overrides["tools"] = openai_tools(default_registry())         # só cai no default se ninguém passou.
        overrides.setdefault("tool_choice", pc.tool_choice or "required")  # força chamada (sem bail): respond/
        _native_sent = True                                 # task_complete SÃO tools → sempre válido
    try:
        resp = litellm.completion(**_kwargs(pc, messages, stream=False, model=model, **overrides))
    except Exception as e:  # noqa: BLE001
        if _native_sent and _is_tool_schema_error(e):       # schema tropeçou no grammar-converter mesmo após
            from okami.llm.schema_sanitizer import sanitize_tool_schemas   # sanitização proativa → re-sanitiza
            # AGRESSIVO sobre as MESMAS tools que já estavam no payload (preserva o registry FILTRADO por
            # surface que o runner passou) — reverter p/ default_registry reintroduziria run_shell/spawn etc.
            overrides["tools"] = sanitize_tool_schemas(overrides["tools"], aggressive=True)   # e retenta 1x
            resp = litellm.completion(**_kwargs(pc, messages, stream=False, model=model, **overrides))
        else:
            raise
    choice = resp.choices[0]
    return Completion(text=_message_text(choice.message),                   # content; vazio → reasoning_content
                      tool_calls=_extract_tool_calls(choice.message),       # antes JOGADO FORA (P0.4)
                      finish_reason=getattr(choice, "finish_reason", "") or "stop",
                      usage=normalize_usage(getattr(resp, "usage", None), transport="litellm"),
                      provider=pc.name, model=_effective_model(pc, model))


_EMPTY_NUDGE = ("[ATENÇÃO: sua última resposta veio VAZIA (sem conteúdo). Responda AGORA de verdade — "
                "o texto da resposta ou o bloco ```json de ação. Não devolva vazio de novo.]")


def _with_empty_nudge(messages: list[dict]) -> list[dict]:
    """Escada de resposta vazia (pesquisa #5 item 7), nível "nudge": cópia das mensagens com um
    empurrão FUNDIDO na última 'user' (alternância preservada p/ Anthropic). É scaffolding
    SINTÉTICO e local — o histórico durável do chamador nunca vê isto."""
    out = [dict(m) for m in messages]
    for i in range(len(out) - 1, -1, -1):
        if out[i].get("role") != "user":
            continue
        c = out[i].get("content")
        if isinstance(c, str):
            out[i]["content"] = (c or "") + "\n\n" + _EMPTY_NUDGE
            return out
        if isinstance(c, list):                          # multimodal (vision): anexa como bloco de texto
            out[i]["content"] = [*c, {"type": "text", "text": _EMPTY_NUDGE}]   # (não cria 2ª user → alternância)
            return out
    out.append({"role": "user", "content": _EMPTY_NUDGE})
    return out


def _interruptible_sleep(total: float, cancel=None, on_heartbeat=None, _sleep=time.sleep) -> bool:
    """Dorme `total`s em fatias de 0.25s, checando cancel() a cada fatia. True = foi CANCELADO no meio.
    Multi-vendor: um backoff de rate-limit/overloaded acontece em TODO provider; sem isto, /stop do dono
    esperava o sleep INTEIRO (até 60s) antes de responder. `on_heartbeat()` é chamado a cada ~30s (best-effort)
    p/ o status 'ainda trabalhando' NÃO congelar durante a espera (o heartbeat normal só roda entre passos)."""
    if not total or total <= 0:
        return bool(cancel and cancel())
    slept = 0.0
    since_beat = 0.0
    while slept < total:
        if cancel and cancel():
            return True
        if on_heartbeat and since_beat >= 30.0:
            try:
                on_heartbeat()
            except Exception:  # noqa: BLE001 — heartbeat é best-effort; nunca derruba o retry
                pass
            since_beat = 0.0
        _sleep(min(0.25, total - slept))
        slept += 0.25
        since_beat += 0.25
    return bool(cancel and cancel())


def complete_messages_ex(
    cfg: OkamiConfig,
    messages: list[dict],
    *,
    provider: str | None = None,
    model: str | None = None,
    response_schema: dict | None = None,
    _tried: set | None = None,
    _sleep=time.sleep,
    cancel=None,
    on_heartbeat=None,
    **overrides,
) -> Completion:
    """Completa a partir de uma lista de mensagens (harness §3) e devolve um `Completion` (texto +
    usage + provider/model que REALMENTE respondeu). Robustez (dor nº1): classifica o erro p/ a
    alavanca (rotacionar chave vs back off vs failover), espera com jitter, parqueia chave em 429,
    e trata RESPOSTA VAZIA como falha (não sucesso) — senão o harness vê turno em branco."""
    _orig = messages                                 # pré-sanitize (carrega reasoning_items) p/ o replay Codex
    messages = _sanitize_messages(messages)          # surrogate solto no histórico não trava o turno
    pc = cfg.provider(provider)
    messages = _ensure_reasoning_echo(messages, pc)  # DeepSeek-reasoner/Kimi/MiMo exigem reasoning_content
    # REPLAY de reasoning (Codex store=false): SÓ o transport codex recebe a versão field-kept (com
    # reasoning_items); litellm/minimax/etc seguem com o `messages` totalmente sanitizado (sem vazar campo).
    _raw = _sanitize_messages(_orig, strip_fields=False) if getattr(pc, "transport", "") == "codex_oauth" else None
    # piso de tentativas = pc.max_retries (default 3) — provider de UMA chave (sem pool) não pode ficar
    # com ZERO retry em erro transiente (429/503/timeout); pool maior que o piso ainda vale (giro de chave).
    attempts = max(pc.max_retries, len(pc.key_pool()))
    # Guarda CROSS-SESSÃO (Hermes nous_rate_guard): outro processo (gateway/cron/CLI) tomou
    # 429/529 deste provider → UMA sonda no máximo, sem rodar todas as chaves (era a amplificação
    # de retry que aprofundava o buraco da quota). Fail-open: a sonda re-testa e atualiza a marca.
    from okami.llm import rate_guard as _rg
    _was_blocked = _rg.blocked_for(pc.name) > 0
    if _was_blocked:
        attempts = 1
    last_exc: Exception | None = None
    do_fallback = True
    send = messages                                   # cópia local recebe o nudge; `messages` fica intacta
    nudged = False
    from okami.llm.turn_retry_state import TurnRetryState
    recovered = TurnRetryState()                      # #10/#11: guards one-shot de recuperação reativa
    attempt = 0
    while attempt < attempts:
        attempt += 1
        ov = dict(overrides)
        if pc.key_pool():
            ov["_api_key"] = _rotate_key(pc)
        try:
            res = as_completion(_complete_one(pc, send, model, response_schema, ov, raw_messages=_raw)
                                if _raw is not None                       # codex c/ replay → passa o field-kept;
                                else _complete_one(pc, send, model, response_schema, ov))   # resto: assinatura antiga
            if not res.text.strip() and not res.tool_calls:   # vazio = falha, entra na escada…
                from okami.llm.stream_diag import classify_completion
                # …MAS vazio por finish_reason='length' (modelo gastou tudo em reasoning) é TRUNCAÇÃO, não
                # stall: deixa passar p/ o loop fazer length-continuation em vez de nudge de "veio vazio" (#11).
                if classify_completion(res) != "length_truncation":
                    raise EmptyResponse("resposta vazia do provider")
            if not res.provider:                      # garante served-by mesmo no caminho legado/teste
                res.provider = pc.name
            if _was_blocked:                          # voltou a responder → limpa a marca cross-sessão
                _rg.clear(pc.name)
            if ov.get("_api_key"):                    # chave respondeu → tira do pool persistente (item 20)
                try:
                    from okami.llm import cred_pool
                    cred_pool.clear(pc.name, ov["_api_key"])
                except Exception:  # noqa: BLE001
                    pass
            return res
        except Exception as e:  # noqa: BLE001
            last_exc = e
            ce = _err.classify(e)
            # Escada de resposta VAZIA, nível "nudge" (pesquisa #5 item 7): antes de queimar chave/
            # backoff, UMA re-tentativa imediata com o empurrão — não consome tentativa do pool.
            if ce.reason == "empty_response" and not nudged:
                nudged = True
                send = _with_empty_nudge(send)
                attempt -= 1
                continue
            # #10: recuperação REATIVA in-place (1× por tipo) — conserta o request e re-tenta O MESMO
            # provider ANTES de queimar chave/failover. Crucial p/ assinatura-only (sem key pool):
            # um 400 'imagem grande' ou um 401 (token revogado) não pode pular pro fallback e perder o turno.
            from okami.llm import recovery as _rec
            if _rec.is_image_too_large(e) and recovered.try_once("shrink"):
                send = _rec.shrink_images(send)        # encolhe a imagem nativa e tenta de novo
                attempt -= 1
                continue
            if ce.reason == "auth" and recovered.try_once("oauth_refresh") and _rec.refresh_oauth(pc):
                # one-shot REAL: marca ANTES de tentar (401 c/ token não-expirado → força refresh e re-tenta).
                # Antes só marcava se o refresh desse certo → refresh quebrado re-tentava a cada 401 (loop).
                attempt -= 1
                continue
            if ce.reason == "rate_limit":             # marca CROSS-SESSÃO: outros processos param de martelar
                _rg.note_rate_limited(pc.name, retry_after=ce.retry_after)   # provider pediu N s → honra
            elif ce.reason == "overloaded":
                _rg.note_overloaded(pc.name)
            if ce.rotate_key:
                _park_key(ov.get("_api_key"), ce, provider=pc.name)   # parqueia (in-memory + persistente)
            if ce.never_repeat:                       # content_policy: NÃO re-envia na MESMA chave (o break
                do_fallback = ce.fallback             # já garante isso), mas PODE failover p/ outro provider/
                break                                 # família que talvez não recuse (o set `tried` corta loop)
            if not ce.retryable:                      # 400/auth-perm/model-retired → não insiste
                do_fallback = ce.fallback
                break
            do_fallback = do_fallback or ce.fallback
            if attempt < attempts:                    # ainda há chave → espera e tenta de novo
                # backoff INTERRUPTÍVEL: /stop do dono durante a espera para o retry NA HORA (não failover —
                # cancelou = parar tudo), em vez de esperar o sleep inteiro (até 60s).
                if _interruptible_sleep(retry_delay(attempt, ce.retry_after), cancel, on_heartbeat, _sleep):
                    do_fallback = False
                    break
    # esgotou chaves (ou erro não-retriável c/ fallback) → FAILOVER p/ outro provider (estilo Hermes)
    tried = (_tried or set()) | {pc.name}
    if do_fallback:
        for fb in (pc.fallback or []):
            if fb in tried or fb not in cfg.providers:
                continue
            fbc = cfg.provider(fb)
            if fbc.experimental:                          # opt-in só explícito — nunca failover automático
                continue
            # pula só quem tem requisito de AUTH não atendido (login/CLI/env key) — tomaria 401 na cara.
            # Provider "bare" (litellm via defaults) segue tentável.
            needs_login = fbc.transport in ("codex_oauth", "minimax_oauth", "claude_cli") and not fbc.ready
            needs_key = bool(fbc.api_key_env) and not fbc.resolved_key()
            if needs_login or needs_key:
                continue
            try:
                return complete_messages_ex(cfg, messages, provider=fb, response_schema=response_schema,
                                            _tried=tried, _sleep=_sleep, cancel=cancel,
                                            on_heartbeat=on_heartbeat, **overrides)
            except Exception:  # noqa: BLE001
                continue
    raise last_exc if last_exc else RuntimeError("sem provider disponível")


def complete_messages(cfg: OkamiConfig, messages: list[dict], **kwargs) -> str:
    """Compat: só o texto. Quem quer usage/served-by usa `complete_messages_ex`."""
    return complete_messages_ex(cfg, messages, **kwargs).text


def stream_complete(
    cfg: OkamiConfig,
    prompt: str,
    *,
    provider: str | None = None,
    system: str | None = None,
    model: str | None = None,
    **overrides,
) -> Iterator[str]:
    pc = cfg.provider(provider)
    messages = _build_messages(prompt, system)
    via = transports.dispatch(pc, messages, model, overrides)
    if via is not None:  # transports CLI/OAuth não streamam: devolve de uma vez
        yield via
        return
    # Robustez (dor nº1) também no caminho INTERATIVO: se o stream falha ANTES de qualquer token
    # (429/5xx/timeout/instabilidade), NÃO deixa o turno em branco — cai no caminho robusto
    # (complete_messages_ex: retry + rotação de chave + failover p/ pc.fallback) e entrega de uma vez.
    # Se já streamou parte e quebrar no meio, propaga (não dá p/ refazer limpo sem duplicar).
    produced = False
    try:
        for chunk in litellm.completion(
            **_kwargs(pc, messages, stream=True, model=model, **overrides)
        ):
            try:
                d = chunk.choices[0].delta
                delta = d.content or getattr(d, "reasoning_content", None) or getattr(d, "reasoning", None)
            except (AttributeError, IndexError):
                delta = None
            if delta:
                produced = True
                yield delta
        if not produced:                              # stream terminou SEM nada → trata como falha
            raise EmptyResponse("stream vazio")
        return
    except Exception as e:  # noqa: BLE001
        if produced:
            raise                                     # parte já entregue ao chamador → propaga
        from okami import log
        log.warn(f"stream instável ({_err.classify(e).reason}); caindo no caminho robusto (sem streaming).",
                 exc_info=False)   # fallback TRATADO: não assusta o usuário com traceback (a razão já basta)
        res = complete_messages_ex(cfg, messages, provider=provider, model=model, **overrides)
        if res.text:
            yield res.text
