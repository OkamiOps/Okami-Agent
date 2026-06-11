# Pesquisa profunda nº3: Hermes + OpenClaw (2026-06-11)

> Terceira varredura de fonte, agora cobrindo as áreas AINDA NÃO mineradas: memória/contexto,
> orquestração/kanban, automação/cron/hooks/ops do **Hermes** (`/tmp/hermes-agent`, atualizado hoje),
> e a arquitetura + diferenciais do **OpenClaw** (`/tmp/okami-refs/openclaw`, ~20k arquivos, hoje).
> 5 agentes leram arquivo:linha. Deduplicado contra o que o Okami JÁ tem (rodadas 1–3 anteriores).

## Onde o Okami já está em paridade (não repetir)
Já entregue nas rodadas anteriores: split>4096, retry/backoff, dedup, typing, botão inline + nonce,
mídia (envio/recebimento), bloco de estilo por superfície, guidance por família de modelo, markdown→
HTML do Telegram, tool_mode por capacidade, model catalog offline, pareamento dinâmico, home-channel
de cron, tool-cards com diff, criação de skills (humano + agente). **Streaming-by-edit, native
tool-calling E2E e registry formal de plataformas seguem pendentes** (precisam de live ou são grandes).

---

## A) MEMÓRIA / CONTEXTO (Hermes)

| Ideia | O que é | Okami hoje | Valor / esforço |
|---|---|---|---|
| **Snapshot congelado de memória** | Carrega MEMORY/USER 1x no início da sessão, congela no system prompt; escritas mid-sessão vão pro disco mas NÃO mutam o prompt → prefix-cache estável o dia todo. | injeta memória a cada turno (`ContextEngine`) → quebra prefix-cache | **Alto / M** |
| **Timestamp só-data** | hora no prompt é DATA, não minuto → byte-estável o dia inteiro (minuto quebra cache a cada turno). | conferir se injetamos hora com minuto | **Alto / S** |
| **Fronteira limpa de compressão** | nunca parte um par tool-call/tool-result ao resumir; `_snap_boundary` move a fronteira. | conferir invariante na nossa compaction | **Médio / S** |
| **Wrapper `<persisted-output>`** | resultado grande de tool vira tag estruturada (preview + caminho); modelo lê o resto com read_file(offset/limit). | já truncamos p/ `.okami/tool_outputs/` mas sem o wrapper estruturado nem offset/limit | **Médio / S** |
| **Scrubber de contexto no streaming** | máquina de estado tira blocos de memória vazados do texto streamado (cross-chunk). | sem streaming ainda → adiar | Baixo / — |
| **Prompt de sumarização versionado** | `"[CONTEXT SUMMARY]:"` + fallback estático quando o LLM falha. | temos compaction; conferir o fallback sem-LLM | Baixo / S |

## B) ORQUESTRAÇÃO / KANBAN (Hermes)

| Ideia | O que é | Okami hoje | Valor / esforço |
|---|---|---|---|
| **BackgroundRegistry com histórico de tentativas** | board SQLite com run history, comentários, parent/child, outcome estruturado (completed/timed_out/rate_limited). | BackgroundRegistry persiste, mas sem histórico de tentativas nem metadata estruturada | **Médio / M** |
| **Contrato de orquestração no prompt** | KANBAN_GUIDANCE injeta o ciclo de vida (orient→trabalha→heartbeat→complete/block→cria filhos não executa). | spawn/background sem contrato explícito | **Médio / S** |
| **Validação de cards criados** | worker que diz "criei tarefa X" tem o ID verificado no DB → `HallucinatedCardsError`. | sem verificação | Baixo / S |
| **Spawn tree observável** | subagent_id + parent_id + depth relayados → TUI desenha a árvore viva; registry de subagentes ativos; detecção de filho travado. | spawn é lista plana, sem árvore nem stale-detection | **Médio / M** |
| **Claim-lock + heartbeat** | tarefa longa tem claim com timestamp; sem heartbeat em 1h → re-enfileira. | sem supervisão de tarefa longa | Médio / M |
| **Background review fork** | após o turno, fork não-bloqueante revisa memória/skills (e poderia decidir criar follow-up). | temos review por LLM; sem fork com prefix-cache herdado | Baixo / M |

## C) AUTOMAÇÃO / CRON / OPS (Hermes)

| Ideia | O que é | Okami hoje | Valor / esforço |
|---|---|---|---|
| **Modo silencioso `[SILENT]`** | job cujo resultado começa com `[SILENT]` salva no arquivo mas NÃO entrega → sem spam, com trilha. | toda saída de cron entrega no chat | **Alto / S** |
| **Wake gate (pré-check)** | script pré-run devolve `wakeAgent:false` → pula o LLM inteiro ("se nada mudou, não acorda o agente"). | cron sempre roda o prompt cheio | **Alto / M** |
| **Entrega multi-alvo** | `deliver="telegram,slack"` ou `all` → mesma saída em vários canais. | alvo único | Médio / S |
| **Execução paralela de jobs** | pool de threads + dedup de in-flight; jobs com workdir são sequenciais, resto paralelo. | scheduler serial | Médio / M |
| **Per-job workdir** | job fixa o cwd e roda sequencial (isola projeto). | sem isolamento de cwd por job | Médio / S |
| **Memory-leak watchdog** | thread daemon loga RSS+GC a cada 5min, formato grepável `[MEMORY]`. | sem monitoramento | **Médio / S** |
| **Shutdown forensics** | no SIGTERM/SIGINT captura sinal/pai/load/takeover (<10ms) + diagnóstico assíncrono. | sem post-mortem | Baixo / M |
| **Graceful drain + exit 75** | sai com EX_TEMPFAIL pro service manager reiniciar; checa TimeoutStopSec do systemd. | sem drain configurável | Baixo / M |

## D) ARQUITETURA (OpenClaw)

| Ideia | O que é | Okami hoje | Valor / esforço |
|---|---|---|---|
| **Loop detection multi-detector** | 4 detectores: repeat por hash de args, poll-sem-progresso, ping-pong (par alternado A→B→A→B), circuit breaker global. | anti-loop por fingerprint (repeat + ciclo de 2) — não pega poll-sem-progresso por mudança de OUTPUT | **Alto / M** |
| **System prompt em seções ordenadas + cache** | prompt montado de seções com ordem declarada; partes estáveis cacheadas; plugins/engine injetam seções. | ContextEngine já é por seção; falta cache de prefixo estável | Médio / M |
| **Provider adapter plugável** | cada provider é um plugin: normaliza schema de tool, parseia stream, política de replay/thinking, recuperação de erro. | provider via litellm/cli, lógica no core | Médio / L |
| **Repair layers por provider** | wrappers empilhados: sanitiza tool-call-id, decodifica args (xAI html-entities), normaliza nome de tool. | reparo de nome de tool só (alucinação) | Médio / M |
| **Rewrite de transcript in-place** | sessão é DAG; engine pede reescrita de entrada (redação/conserto). | transcript append-only linear | Baixo / L |

## E) UX / DIFERENCIAIS (OpenClaw)

| Ideia | O que é | Okami hoje | Valor / esforço |
|---|---|---|---|
| **Streaming-by-edit** | 1ª msg `send`, próximos chunks `edit` na MESMA msg → "digitando ao vivo"; coalescing 800–1200 chars/1s idle. | resposta só no fim do turno | **Alto / M** (depende de deltas do harness) |
| **Debounce por chave (entrada)** | agrupa msgs do mesmo (remetente, canal) numa janela → 10 DMs em rajada = 1 turno; garante ordem por remetente. | cada msg = 1 turno | **Alto / M** |
| **Comandos em tiers + fuzzy** | essential/standard/power (disclosure progressivo) + match por Levenshtein ("/model mistrl"→sugere). | ~40 comandos com tier no CommandDef + "did you mean" simples | **Médio / S** (já temos base) |
| **Aprovação multi-superfície** | aprovação vai pro thread de origem OU DM do aprovador (se ele não está no canal) + aviso "veja seu DM". | aprovação só no thread de origem | Médio / M |
| **Análise de risco no approval** | mostra o comando com trechos de risco destacados (rm -rf, curl\|sh, eval). | classify destrutivo só decide pedir/não | **Médio / S** |
| **Comando de skill registra nativo** | skill define `nativeName`/args → aparece no menu nativo do canal. | skills não viram comando | Baixo / M |
| **Thinking levels por modelo** | UI só mostra níveis que o modelo suporta (Claude tem 5, OpenAI binário). | /think livre | Baixo / S |
| **Pairing adapter por canal** | id_label ("Slack username"), normalize_allow_entry, notify_approval ("você foi pareado!"). | pairing genérico (acabamos de adicionar) | Baixo / S |

---

## Plano priorizado (alto valor / baixo-médio risco, testável offline)

**Onda A — robustez do agente (sem depender de streaming/live):**
1. **Loop detection multi-detector** (D) — poll-sem-progresso + ping-pong + circuit breaker. *Conserta travamento real que o fingerprint atual não pega.*
2. **Wrapper `<persisted-output>` + read_file(offset/limit)** (A) — modelo recupera saída grande de verdade.
3. **Snapshot congelado de memória + timestamp só-data** (A) — prefix-cache estável (economia real de token/custo).

**Onda B — automação que o usuário sente:**
4. **Modo silencioso `[SILENT]` no cron** (C) — sem spam de cron, com trilha.
5. **Wake gate (pré-check)** (C) — cron condicional barato (não acorda o LLM à toa).
6. **Memory-leak watchdog** (C) — observabilidade de produção.

**Onda C — entrada/saída (parte depende do harness emitir deltas):**
7. **Debounce por chave na entrada** (E) — rajada de DMs vira 1 turno. *Não depende de streaming.*
8. **Análise de risco no approval** (E) — destaca trecho perigoso. *Testável, isolado.*
9. **Streaming-by-edit** (E) — depende de deltas do harness → fazer junto com native tool-calling.

**Adiar (grande/arquitetural ou precisa live):** provider adapter plugável, rewrite de transcript DAG,
shutdown forensics/systemd drain, board SQLite com histórico, background review fork.

> Fonte da verdade do estado atual: README + auto-memória. Refs: `/tmp/hermes-agent`, `/tmp/okami-refs/openclaw`.
