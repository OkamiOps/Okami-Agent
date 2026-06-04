# Okami — Plano de robustez (auditoria profunda Hermes + OpenClaw)

> 2ª varredura **funda e pronta-pra-codar** do código real do **Hermes** (`NousResearch/hermes-agent`,
> harness de produção) e do **OpenClaw** (`czl9707/build-your-own-openclaw` + instalação real do OpenClaw
> em disco + issues do openclaw/openclaw). 6 agentes paralelos, cada um com spec arquivo:linha. Substitui
> a 1ª versão (mais rasa). Objetivo: **robusto, não de garagem.** Atualizado 2026-06-04.

## ⛓️ O KEYSTONE (faz primeiro — destrava 3 ondas de uma vez)
Hoje `complete_messages`/transports devolvem **`str` cru** e jogam fora o `usage`. Introduzir **um objeto
de resultado** `Completion(text, tool_calls, usage, finish_reason)` destrava:
- **Onda 3 (nativo)** precisa de `tool_calls` + `finish_reason`.
- **Onda 4 (custo)** precisa de `usage` (que o SSE do codex **já entrega** e a gente descarta).
- **Onda 4 (caching)** medir cache precisa de `usage.cache_read`.
- **Onda 4 (compaction por token)** precisa de `usage.prompt_tokens` (hoje é char-based, model-blind).
- **Fallback** mostrar "quem respondeu" precisa do provider/model efetivo.

`okami/llm/usage.py` (novo): `CanonicalUsage` (input/output/cache_read/cache_write/reasoning) + `Completion`
+ `normalize_usage(raw, transport)` + tabela de preço + `estimate_cost` com **modo "incluído"** p/ assinatura.

## 🚫 O que NÃO regredir (Okami já à frente das duas referências)
Action-or-Terminate · exit criteria verificados · protocolo JSON p/ paridade (fallback) · skill security ·
transcript append-only com torn-line recovery + `_FileLock` (O_EXCL) · checkpoints/rollback · go/no-go
fail-closed · jittered backoff · key pool · surrogate scrub · empty-response→failover · `escalate_to` manual.

## 🚫 O que NÃO construir (gold-plating — ausente nas duas referências)
Router por custo/capacidade · idempotency keys · dedup de request in-flight · resume de stream parcial.
(Confirmado: nem Hermes nem OpenClaw têm. Não inventar.)

---

# ORDEM DE IMPLEMENTAÇÃO (por dependência)

**Fase A — Keystone:** `Completion` + `usage` + custo (Onda 4 parcial). *Destrava o resto.*
**Fase B — Onda 3 nativo (codex):** usa `tool_calls` do `Completion`.
**Fase C — Onda 4 resto:** caching (reorder estático→dinâmico + `cache_control`), compaction por token.
**Fase D — Onda 5 tools:** `edit_file`, budget de resultado, mtime guard, `doctor --fix`, hot-reload.
**Fase E — Fallback robusto:** chain `{provider,model}`, eager, `reset_at`, served-by, stream failover.
**Fase F — Gaps de produção:** durabilidade de config, audit log, env do MCP, scheduler lock, etc.

---

## FASE A — Custo / tokens (o que você cobrou)  ⭐
| # | O que | Fonte | Arquivo | I/E |
|---|---|---|---|---|
| A1 | `okami/llm/usage.py`: `CanonicalUsage`, `normalize_usage` (codex/litellm/anthropic), `Completion` | Hermes `usage_pricing.py` | novo | M |
| A2 | Capturar `usage` no `_codex_sse_text` (já está no `response.completed`!) → `(text, usage)` | Hermes `codex_runtime.py` | `transports.py` | S |
| A3 | Thread `Completion` por `complete_messages_ex`/`_complete_one`/`dispatch` (mantém `->str` p/ os testes) | Hermes `conversation_loop.py` | `providers.py` | M |
| A4 | Tabela de preço + `estimate_cost` com **`subscription_included`→$0/"incluído"** (codex/claude) | Hermes `usage_pricing.py` `resolve_billing_route` | `usage.py` | S |
| A5 | Acumular usage por sessão (`add_usage` sob `_FileLock`) + mostrar em `okami status` + status bar | Hermes `SessionDB.update_token_counts`, `insights.py` | `gateway/sessions.py`, `cli.py`, `tui.py` | M |
| A6 | `okami insights` (tokens/custo/cache-hit ratio/tool ranking) | Hermes `insights.py` | `cli.py` | M |
> Pega-ratão: codex/OpenAI reportam `prompt_tokens` **incluindo cache** → `input = max(0, total - cache_read - cache_write)`. Anthropic já vem separado. Persistir TOKENS, custo é derivado (preço muda retroativo).

## FASE B — Onda 3: tool-calling nativo (codex)  ⭐
| # | O que | Fonte | Arquivo | I/E |
|---|---|---|---|---|
| B1 | `Tool.to_openai_schema()` + `openai_tools(registry)` + flag `mutating` (read tools=False) | OpenClaw `tools/base.py` | `core/tools.py` | S |
| B2 | codex: mandar `tools` no payload (shape flat `{type:function,name,...}`) + coletar `function_call` items do SSE (`response.output_item.done`) + converter tool-result→`function_call_output` | Hermes `codex_responses_adapter.py` | `transports.py` | M |
| B3 | Harness: branch nativo — `if res.tool_calls:` monta `Action`(+`call_id`), `_invoke_one` compartilhado, `parse_action` fica de fallback. Multi-tool: sequencial; paralelo só se TODAS read-only (ThreadPool 8) | OpenClaw `core/agent.py`, Hermes `tool_executor.py` | `core/harness.py` | L |
| B4 | `_repair_tool_call_arguments` (escada de fixes, nunca crasha) | Hermes `message_sanitization.py` | `llm/repair.py` (novo) | S |
| B5 | Modo nativo **tira o menu do prompt** (mantém guidance de voz) — gate por `capability.tool_mode: native` (só no codex) | Hermes `prompt_builder.py` | `core/harness.py` | S |
> **Claude (`claude_cli`) NÃO faz nativo** — o `-p` roda o loop interno do Claude Code com as ferramentas DELE; fica no JSON-em-texto (é pra isso que mantivemos o fallback). Nada de tentar Anthropic nativo via CLI (quebra o constraint de auth sancionada).

## FASE C — Onda 4: caching + compaction por token
| # | O que | Fonte | Arquivo | I/E |
|---|---|---|---|---|
| C1 | **Reordenar prompt estático→dinâmico** (identidade+manual no topo fixo; recall/histórico/timestamp por ÚLTIMO). Vale p/ TODOS (codex/OpenAI auto-cacheiam prefixo estável) | OpenClaw `prompt_builder.py` | `core/harness.py`, `memory/files.py` | M |
| C2 | `okami/core/prompt_caching.py`: `apply_anthropic_cache_control` (system + últimas 3 não-system, 4 breakpoints) — **só litellm→anthropic** | Hermes `prompt_caching.py` | novo | S |
| C3 | Compaction por TOKEN (`usage.prompt_tokens >= ctx*0.75`) com `protect_head=3`/`tail=6`; trunca tool-results ANTES de sumarizar; prompt de resumo de 5 seções; anti-thrashing | Hermes `context_engine.py`, OpenClaw `context_guard.py` | `memory/compaction.py`, `gateway/__init__.py` | M |
> Caching só rende de fato no caminho litellm→Anthropic; `claude_cli` achata em string `-p` (sem markers). Codex/OpenAI auto-cacheiam → o reorder (C1) é a vitória universal. Mede com `cache_read/(cache_read+input)` (depende da Fase A).

## FASE D — Onda 5: tools + config
| # | O que | Fonte | Arquivo | I/E |
|---|---|---|---|---|
| D1 | **`edit_file`** (string-replace com **gate de unicidade** `len(matches)>1 and not replace_all`) + re-leitura pós-escrita | Hermes `fuzzy_match.py` | `core/tools.py` | S |
| D2 | **Budget de tool-result**: `maybe_persist_tool_result` (output grande → `.okami/tool-results/<id>.txt` + preview+path; `read_file`=∞) + `enforce_turn_budget` (200k) | Hermes `tool_result_storage.py` | `core/tool_result_budget.py` (novo), `harness.py` | M |
| D3 | **mtime stale-guard** (read_files guarda mtime; bloqueia overwrite de arquivo mudado em disco/por subagente) | Hermes `file_state.py` | `core/tools.py` | S |
| D4 | **`doctor --fix`** (cria .env 0600, dirs/SOUL [nunca sobrescreve SOUL existente], WAL checkpoint, migrate, probes paralelos) + lista numerada + exit≠0 | Hermes `doctor.py` | `cli.py` | M |
| D5 | **YAML hot-reload** (watchdog + valida-antes-de-trocar + **debounce** + `on_reload` callback + RLock + cache mtime) | OpenClaw `08-config-hot-reload` | `config.py` | M |
| D6 | **🔴 chmod 0600 no `.env`** + **denylist de env** (`LD_PRELOAD`/`PATH`/`PYTHONPATH`/`EDITOR`…) no `config set` — vuln viva hoje (RCE via .env) | Hermes `config.py` `_ENV_VAR_NAME_DENYLIST` | `cli.py` | S |
| D7 | `config migrate` + `config_version` + backup de config corrompido (`.corrupt.<ts>.bak`, opera no dict CRU, não no expandido) | Hermes `config.py` | `config.py`, `cli.py` | M |

## FASE E — Fallback robusto (o que você cobrou)  ⭐
| # | O que | Fonte | Arquivo | I/E |
|---|---|---|---|---|
| E1 | **Chain `fallback_chain: list[{provider, model}]`** — inclui "modelo alternativo no mesmo provider"; itera os alvos passando provider+model | Hermes `agent_init.py` | `config.py`, `providers.py` | M |
| E2 | **Eager** em `EmptyResponse`/`overloaded`: NÃO queima todas as chaves num provider morto — avança a chain na hora | Hermes `conversation_loop.py`, openclaw #49696 | `providers.py` | S |
| E3 | **🔴 `stream_complete` ganha classify→retry→fallback** (hoje 529 no stream só explode) | openclaw #49696 | `providers.py` | M |
| E4 | Honrar **`reset_at` do header** (`x-ratelimit-reset-*`/`retry-after`) em vez do 1h fixo | Hermes `nous_rate_guard.py` | `errors.py`, `providers.py` | S |
| E5 | **Mostrar quem respondeu** ("respondido por minimax — codex sobrecarregado") | Hermes `conversation_loop.py` | `providers.py`, `runner.py` | S |
| E6 | **Two-strikes 429** (retenta a mesma chave 1x, rotaciona na 2ª) + status DEAD vs EXHAUSTED (401-perm=DEAD) + TTL 401=5min/429=1h | Hermes `credential_pool.py` | `providers.py`, `errors.py` | M |
| E7 | **Cooldown por provider** (overloaded) checado ANTES de disparar; guarda de provider-mismatch antes de parquear chave | Hermes `credential_pool.py` | `providers.py` | S |
| E8 | Estado de rate-limit **cross-process** (`.okami/rate_limits/<provider>.json`, escrita atômica) — gateway compartilha chaves entre scheduler+sessões+grupos | Hermes `nous_rate_guard.py` | novo `llm/ratestate.py` | M |
| E9 | Aliases estáticos de provider/model (`claude`→anthropic, `opus`→…) | Hermes `agent_runtime_helpers.py` | `config.py` | S |

## FASE F — Gaps de produção ("não-de-garagem")
| # | O que | Fonte | Arquivo | I/E |
|---|---|---|---|---|
| F1 | **Durabilidade de config**: escrita atômica + `.bak.N` rotativo + `.last-good` + quarentena `.clobbered.<ts>` + version stamp | OpenClaw real em disco | `config.py`, `cli.py` | M |
| F2 | **Audit log** de aprovações (tool, args-digest, categoria, risco, decisão, ator, ts → `.okami/audit.jsonl`) + modo `dry_run`/`defer` | OpenClaw `exec-approvals.json` | `core/approval.py`, `gateway` | S-M |
| F3 | **🔴 MCP sanitiza env**: hoje passa `os.environ` INTEIRO (tokens/chaves) pros servidores MCP de terceiros — anula a proteção do `run_shell` | nosso `mcp.py:97` | `integrations/mcp.py` | S |
| F4 | **Scheduler write-lock** (`_FileLock` no `cron.json`; race com o chat) + iniciar scheduler mesmo sem job no boot | nosso `scheduler.py`/`gateway` | `gateway/__init__.py` | S |
| F5 | OAuth **multi-perfil** (`provider:email`) + refresh-ahead (background) + contadores de cota | OpenClaw `auth.profiles`, Hermes `credential_pool.py` | `llm/oauth.py` | M-L |
| F6 | **Skill lockfile** (SHA-256 por skill; verifica no load) — supply-chain | OpenClaw `skills-lock.json` | `skills/__init__.py` | S-M |
| F7 | Logging estruturado (`.okami/okami.log.jsonl` + `trace_id` por turno) | Hermes `insights.py`/`trajectory.py` | novo `logging` | M |
| F8 | Shutdown gracioso (SIGTERM → drena sessões busy → flush) | nosso `gateway` | `gateway/__init__.py` | S-M |
| F9 | Trajectory JSONL (sucesso/falha) → alimenta o learning | Hermes `trajectory.py` | `learning/` | S |
| F10 | Dedup de update (Telegram redelivery por `update_id`) | — | `gateway/__init__.py` | S |

---

## Sequência recomendada (commits)
A (keystone+custo) → B (nativo codex) → C (caching) → D1-D3+D6 (tools+segurança) → E (fallback robusto)
→ D4-D5-D7 (doctor/hot-reload/migrate) → F (gaps de produção). Cada fase = 1 commit testado e verificado ao vivo.
Os 🔴 (D6 denylist/.env perms, E3 stream failover, F3 MCP env) são segurança/robustez — prioridade dentro da fase.
