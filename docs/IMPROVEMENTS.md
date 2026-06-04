# Okami — Auditoria Hermes + OpenClaw → plano de melhorias

> Varredura profunda do código real do **Hermes** (`NousResearch/hermes-agent`, harness de produção) e do
> **OpenClaw** (`czl9707/build-your-own-openclaw`, referência rodável de 18 passos + o OpenClaw original),
> mapeada arquivo-a-arquivo pro nosso código. Gerado em 2026-06-04 por 6 agentes paralelos (harness,
> estabilidade, effort/params/providers, setup/config, terminal/TUI, joias diversas).

## O que NÃO regredir (Okami já está à frente)
- **Action-or-Terminate** + **exit criteria verificados** (`check_exit`): "concluído" é asserção do harness,
  não do modelo. Nenhuma das duas referências verifica conclusão. É a nossa melhor ideia.
- **Protocolo JSON agnóstico de modelo** (paridade com fraco/local) — manter como *fallback documentado*
  quando ligarmos tool-calling nativo. As duas referências assumem modelo forte com tool-calling nativo.
- **Scan de segurança de skills** (`skills/skill_security.py`) — mais completo que qualquer um dos dois.
- **Crash recovery** (transcript append-only + `resume_interrupted` + guarda anti-loop) — paridade ou melhor.
- **Gateway channel-agnóstico**, **go/no-go**, **banner/status bar**, **descoberta de modelos ao vivo**,
  **roteamento de segredo por formato da chave**, **herança de config por-agente**.

---

## ONDA 1 — Estabilidade da chamada ao modelo + effort completo  ⭐ (começar por aqui)
*Pequeno, alto impacto, conserta os erros reais (o turno que morre no codex). Quase tudo S/M.*

| # | O que | Fonte | Nosso arquivo / gap | I/E |
|---|---|---|---|---|
| 1.1 | **Codex SSE: terminal-event-or-raise.** Se o stream acaba sem `response.completed/incomplete/failed` E sem texto → **levantar erro** (não `return ""`). Sintetizar dos deltas; tratar `response.incomplete` (truncado). | Hermes `agent/codex_runtime.py` `_consume_codex_event_stream` | `transports.py` `_codex_sse_text` retorna `""` silencioso → harness vê "sem ação" → viola Action-or-Terminate → **turno morre** (o bug que te pegou) | S |
| 1.2 | **Resposta vazia = falha de provider.** `complete_messages`: `if not result.strip(): raise` → entra na rotação/failover (hoje só retry em exceção). | Hermes `conversation_loop.py` (eager fallback) | `providers.py` trata vazio como sucesso | M |
| 1.3 | **Classificador de erro** (`okami/llm/errors.py`): 401→rotaciona · 429→rotaciona+failover · **529/503→back off+troca provider (NÃO rotaciona)** · 400/content-policy→falha rápido (não queima o pool). | Hermes `error_classifier.py` (`ClassifiedError`, 16 categorias) | `providers.py` rotaciona chave em **qualquer** erro | M |
| 1.4 | **Backoff com jitter** entre retries/rotações (só p/ erro retriável), em incrementos pequenos checando `cancel`. | Hermes `retry_utils.py` `jittered_backoff(base=5,max=120)` | `providers.py` faz retry em loop apertado **sem espera** (martela o rate-limit) | S |
| 1.5 | **Cooldown por chave** (429 → chave parada 1h ou até `Retry-After`); `_rotate_key` pula chaves em cooldown. | Hermes `credential_pool.py` (`EXHAUSTED_TTL_429=1h`) + `nous_rate_guard` | `_rotate_key` é round-robin puro, sem saúde | M |
| 1.6 | **Effort unificado por transport** (`reasoning_param(pc, effort)`): codex→`reasoning.effort` (temos) · **Anthropic→`thinking.budget_tokens`** (tabela `xhigh=32k…low=4k`) · `claude_cli`→diretiva no prompt. | Hermes `anthropic_adapter.py` `THINKING_BUDGET` | **hoje "high" no `claude_cli` é silenciosamente ignorado** | M |
| 1.7 | Timeout na rota LiteLLM (`providers.py`); watchdog de TTFB no stream do codex (aborta se N s sem frame); scrub de surrogates UTF-16 antes do `json.dumps`. | Hermes `stream_diag.py`, `message_sanitization.py` | sem timeout no litellm; stream pode pendurar 300s; 1 char ruim no histórico trava todo turno | S–M |

---

## ONDA 2 — Terminal vivo (ligar eventos que já emitimos)  ⭐
*Plumbing puro, risco baixo, impacto percebido enorme. O harness JÁ emite os eventos; o chat só não se inscreve.*

| # | O que | Fonte | Nosso arquivo / gap | I/E |
|---|---|---|---|---|
| 2.1 | **Display de tool-call ao vivo**: passar `on_event` no chat (o `okami task` já renderiza) → spinner + "⚙ run_shell pytest… (3s)" por passo. Mata o "espera 30s e cospe tudo". | Hermes `ui-tui` tool trail; OpenClaw tool cards | `gateway._run` passa `on_event=None`; chat só imprime `task.result` no fim | S–M |
| 2.2 | **Streaming token-a-token** da resposta: `complete_messages_streamed(on_delta)` acumula a string (parse intacto) e emite deltas; só na "fala" (`respond`). | Hermes `message.delta`→`message.complete` | `stream_complete` já existe (usado no `okami run`), **não ligado ao harness** | M |
| 2.3 | **Ctrl-C aborta a geração** (1º Ctrl-C = cancela run via `s.cancel`; 2º = sai). Mid-token no loop de streaming. | OpenClaw Esc=abort / Ctrl-C=clear | `/stop` só entre passos; Ctrl-C sai do REPL | S–M |
| 2.4 | **Renderizar Markdown/código** nas respostas (somos um agente de código!). Stream cru ao vivo → re-render Markdown no fim. | Hermes `markdown.tsx` | `terminal.py` imprime texto cru | S |
| 2.5 | **`prompt_toolkit`** no input: histórico (↑), multiline, autocomplete de slash. | Hermes `textInput.tsx`, `useCompletion.ts` | `console.input` single-line, sem histórico/menu | M |
| 2.6 | Status bar **ao vivo** + tokens/custo + nível `/think`/yolo; `/model` e `/agent` trocam em runtime. | Hermes `StatusRule`; OpenClaw footer | bar impressa 1x por prompt; trocar modelo exige reabrir | M |

---

## ONDA 3 — Tool-calling nativo + tirar o menu do prompt  ⭐
*Maior (M), mas sobe confiabilidade E ajuda o "não parecer chatbot".*

| # | O que | Fonte | Nosso arquivo / gap | I/E |
|---|---|---|---|---|
| 3.1 | **Tool-calling nativo como caminho primário**, JSON-em-texto como fallback (modelo fraco/local). `tools=` na API; em modo nativo monta `Action` direto do `tool_calls`. | OpenClaw `01-tools` (branch em `stop_reason`); Hermes `conversation_loop.py` | `parse_action` faz regex em prosa; sem caminho nativo | M |
| 3.2 | **Apagar o menu de ferramentas + bloco `=== USO INTERNO ===` do prompt** em modo nativo (tools vão nativas). É a vitória mais limpa pro "humano, não chatbot". | Hermes `prompt_builder.py` (não renderiza tools no texto) | `build_system_prompt` despeja tools + 3 frases pedindo pra não recitar | S (depois de 3.1) |
| 3.3 | **Múltiplas tool calls por turno** (hoje 1 → ler 5 arquivos = 5 round-trips, lento e robótico). Paralelo só se todas read-only. | Hermes `execute_tool_calls_concurrent` (8 workers); OpenClaw `asyncio.gather` | 1 ação por turno | M |
| 3.4 | **Detecção de "sem progresso" por hash de resultado** (read-only repetido com mesmo output ≥2× → nudge). | Hermes `tool_guardrails.py` (idempotent no-progress) | anti-loop só pega args idênticos / 2-ciclo; circuit breaker só conta falhas | S |
| 3.5 | Não contar turnos de re-prompt (violação/loop/stall) no `max_steps` (refund). | Hermes `iteration_budget.py` `refund()` | toda correção nossa queima passo | S |

---

## ONDA 4 — Prompt caching + custo + modelos auxiliares
*ROI de custo gigante (~75% nos tokens de entrada). Trio coeso: cachear + medir o cache.*

| # | O que | Fonte | Nosso arquivo / gap | I/E |
|---|---|---|---|---|
| 4.1 | **Reordenar o system prompt estático→dinâmico** (timestamp/canal/recall por último) → prefixo cacheável estável. | OpenClaw `13-multi-layer-prompts` `prompt_builder.py` | montamos com persona/memória interleaved | S |
| 4.2 | **`cache_control` (Anthropic)**: breakpoint após o bloco estático + 3 no fim do histórico. ~75% de economia em multi-turno. | Hermes `prompt_caching.py` (`system_and_3`) | **zero** `cache_control` no código | S |
| 4.3 | **`LLMResult(text, usage, finish_reason)`** em vez de `str` nos transports → destrava custo/tokens (hoje jogamos fora o `usage` que o SSE do codex já entrega). | Hermes adapters normalizam usage | transports devolvem `str` cru | M |
| 4.4 | **Contabilidade de custo/tokens** + view tipo `/insights` (buckets input/output/cache-read/write; modo "incluído" p/ assinatura = $0). | Hermes `usage_pricing.py`, `insights.py` | sem observabilidade de custo | M |
| 4.5 | **Modelos auxiliares baratos por tarefa** (compaction/summary/title/vision → tier weak/local). Hoje queima codex/claude resumindo. | Hermes `auxiliary:` + `auxiliary_client.py` | substrato existe (`tier`), nada roteia | L (S por tarefa) |
| 4.6 | **Model aliases** (nome amigável → provider/model). | Hermes `model_aliases:` | só por nome de provider | S |

---

## ONDA 5 — Camada de tools + setup/config robusto
| # | O que | Fonte | Nosso arquivo / gap | I/E |
|---|---|---|---|---|
| 5.1 | **Tool `edit` (string-replace)** — mais barato e cache-friendly que reescrever arquivo inteiro. | OpenClaw `builtin_tools.py` `edit` | só `write_file` (overwrite total) | S |
| 5.2 | **Budget de resultado de tool + persistência no sandbox** (output grande → arquivo + preview + path; budget agregado por turno 200k). | Hermes `tool_result_storage.py` | output sem guarda → estoura contexto | M |
| 5.3 | **Guarda de stale-read por mtime** (upgrade do `read_files`): detecta arquivo mudado em disco / por subagente antes de overwrite. | Hermes `file_state.py` | `read_files` nunca expira → overwrite com conteúdo velho | S–M |
| 5.4 | **`okami doctor --fix`** (cria `.env` 0600, recria config, stubs faltando) + lista numerada + exit≠0. | Hermes `doctor.py` | doctor é só leitura | M |
| 5.5 | **YAML hot-reload** (`watchdog` + valida-antes-de-trocar + **debounce** + callback pro gateway reler). | OpenClaw `08-config-hot-reload` | sem watcher (era meta na arquitetura) | M |
| 5.6 | **`config migrate`** + `config_version` + backup de config corrompido (`.corrupt.<ts>.bak`). | Hermes `config.py` / `doctor.py` | sem versão/migrate/backup | M |
| 5.7 | **Denylist de segredo** (`LD_PRELOAD`/`PATH`/…) + **chmod 0600** no `.env`. | Hermes `config.py` | `config set LD_PRELOAD …` escreveria vetor de injeção | S |
| 5.8 | Doctor mais fundo (Python/venv, shadowing env↔yaml, dirs, SOUL/VOICE presentes, SQLite) + probes em paralelo. | Hermes `doctor.py` | probes seriais, sem checks de FS/identidade | M |
| 5.9 | `okami init` zero-config (detecta provider pronto → escreve mínimo e roda) + guia non-TTY. | Hermes `setup.py` | sem caminho zero-config | S–M |

---

## ONDA 6 — Polimento multi-agente / ergonomia
| # | O que | Fonte | Nosso arquivo / gap | I/E |
|---|---|---|---|---|
| 6.1 | **`@`-referências** (`@file:x.py:40-80`, `@diff`, `@git:3`, `@url:`) com budget 25/50% + blocklist de path sensível. | Hermes `context_references.py` | sem injeção inline de contexto | M |
| 6.2 | **Trajectory JSONL** (sucesso/falha) p/ replay/eval → alimenta o `learning/`. | Hermes `trajectory.py` | sem log de trajetória estruturado | S |
| 6.3 | **Semáforo de concorrência por agente** no `spawn` (cap de fan-out). | OpenClaw `16-concurrency-control` | `spawn` sem cap | S |
| 6.4 | **Subagente: retorna `session_id`** + lista de agentes como `enum` no schema (anti-alucinação). | OpenClaw `15-agent-dispatch` | `spawn` devolve só string | M |
| 6.5 | **SKILL.md com template/inline-shell** (`${VAR}`, `` !`cmd` ``) expandido no load (via scanner). | Hermes `skill_preprocessing.py` | `use_skill` devolve corpo cru | S–M |
| 6.6 | Compaction: **truncar tool-results antes de sumarizar** (mais barato que ir direto pro LLM). | OpenClaw `context_guard.py` | vamos direto ao resumo | S |

---

## Sequência recomendada
**Onda 1** (conserta os erros reais + completa effort) → **Onda 2** (terminal vivo, plumbing barato) →
**Onda 3** (nativo + tira o menu = confiabilidade + "humano") → **Onda 4** (caching+custo) →
**Onda 5** (tools/config) → **Onda 6** (polimento). Ondas 1 e 2 são pequenas e atacam dor imediata.
