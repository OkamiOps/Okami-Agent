# Pesquisa competitiva #6 — Okami vs Hermes COMPLETO (jun/2026)

Clone fresco do `NousResearch/hermes-agent` (commit `d62979a`, ~2275 arquivos .py) confrontado
com o Okami pós-pesquisa #5 (1521 testes). 6 varreduras paralelas por domínio (backends ·
plataformas · tools de código/web · memória/skills · segurança/providers · interfaces/infra).
Tamanhos S/M/L. ⭐ = recomendado próximo. Foco em gaps NOVOS (não re-lista o que #1–#5 entregaram).

## Onde o Okami está em PARIDADE ou À FRENTE (confirmado no source dos dois)

- **À frente:** voice memo transcrito LOCAL (faster-whisper, sem API) — o Hermes depende de
  OPENAI_API_KEY (Whisper API). Eixo subscription-only é pró-Okami.
- **À frente:** yolo é flag de sessão, não env — o vetor "skill exporta HERMES_YOLO_MODE=1" nem existe.
- **Paridade real:** rate-guard cross-sessão, classificador de erros (17 razões), aux model routing,
  prompt caching Anthropic, hardline-antes-do-yolo, redaction, untrusted delimiter, aprovação em tiers
  persistida, ApprovalStore single-use, MCP trust store, SSRF guard, pareamento dinâmico, auth profiles,
  execute_code (RPC), /goal, apply_patch, curator completo, tool_search, PTY, registry declarativo de
  canais, Honcho (ligado no peer certo), compaction anti-sequestro.
- **Falso gap:** `gateway/builtin_hooks/` do Hermes está VAZIO (`_register_builtin_hooks` retorna []) —
  não embarca nenhum hook. Okami tem hooks genéricos = paridade.

## 🐛 BUG ATIVO achado na análise (corrigir já, fora de onda)

`okami/core/harness/loop.py:84` — o `_TOOL_ALIASES` mapeia **`"search_files" → "find_files"`**. Modelos
treinados em convenção Claude/Hermes pedem `search_files` esperando busca por CONTEÚDO (grep) e recebem,
em SILÊNCIO, busca por NOME (find). Quando o item 2 (search_files real) entrar, remover o alias; até lá,
no mínimo o alias está mascarando a intenção do modelo. **S, alta prioridade.**

## 1. TOOLS DE CÓDIGO E WEB (maior superfície de gap funcional)

### ⭐ S/M — alto retorno
1. ⭐ **web_search** — o Okami NÃO pesquisa na web (só abre URL conhecida via `browse`). Portar o
   backend DDGS zero-key (`pip install ddgs`, `web_tools.py:285`) → tool `web_search(query, limit)`
   devolvendo título+url+snippet. Maior buraco funcional da lista. (S/M)
2. ⭐ **search_files por CONTEÚDO (ripgrep)** — regex no conteúdo + glob, `output_mode`
   (content/files_only/count), `-A/-B`, paginação, sort por mtime; backend rg (o Okami já detecta rg)
   com fallback grep. Hoje o agente faz grep manual por run_shell. + remover o alias-trap (bug acima).
   Molde: `tools/file_operations.py:1924`+ (`_search_content`/`_search_files_rg`). (M)

### M
3. **web_extract com sumarização auxiliar** — extrai página e roteia por modelo auxiliar que
   resume/chunka (preserva fato/código, corta tokens). Hoje `browse` trunca burro em 6000 chars.
   Molde: `web_tools.py:481,610`. Aux model já existe (B57). (M)
4. **vision_analyze** — dá visão a modelo text-only roteando imagem por auxiliar multimodal; OCR/
   screenshot. Fundação semi-pronta (`transports.py:36-41` já trata multimodal). `vision_tools.py:801`. (M)
5. **todo_tool** — checklist estruturado p/ o modelo rastrear progresso multi-passo. `tools/todo_tool.py`. (S)

### L
6. **LSP diagnostics-delta na escrita** — flagship do Hermes: snapshot de diagnostics ANTES do
   write/patch → devolve só os erros NOVOS introduzidos ("quebrei algo?"). Pacote `agent/lsp/` inteiro
   é semanas. **Alternativa 80/20 (M):** rodar linter por-extensão pós-write (ruff/pyright/tsc se no
   PATH) e devolver só o delta de erros — molde `file_operations.py:1608` `_check_lint_delta`. (L → M enxuto)
7. **Browser por árvore de ACESSIBILIDADE** (refs @e1…, click/type por ref não por seletor CSS frágil)
   — `browser_camofox.py`. Exige outro engine de browser. (L)

## 2. MEMÓRIA / SKILLS / APRENDIZADO

### ⭐ S — alto retorno, segurança
8. ⭐ **Scan de injeção na memória nas DUAS pontas (write E load)** — o scanner (`skill_security.scan_text`)
   JÁ existe e roda em 5 caminhos, mas NÃO no de MEMORY.md/USER.md. Ligar no write (rejeita HIGH) +
   sanitizar no load → entrada envenenada vira `[BLOCKED: …]` no system prompt. Buraco de segurança real
   (skill/sessão hostil planta instrução congelada no prompt). Molde: `memory_tool.py:173`. Melhor ROI. (S)
9. **Guard de drift externo** — antes de gravar memória, checa round-trip do .md em disco; se algo editou
   por fora (patch/shell/manual), tira `.bak.<ts>` e RECUSA (evita perda silenciosa). Mesma função
   (`memory/files.py:_append_bullet`) do item 8. `memory_tool.py:540`. (S/M)

### M/L
10. ⭐ **session_search como TOOL** — FTS5 sobre TODOS os transcripts + modos discovery/scroll/read/browse;
    doutrina "memória = preferência; histórico de tarefa = busca de sessão". O Okami JÁ guarda transcripts
    append-only (`gateway/sessions.py`) e tem FTS5 — falta indexar as MENSAGENS e a tool. Hoje conversa
    compactada/`/new`-ada vira arquivo morto irrecuperável. `tools/session_search_tool.py`, `hermes_state.py:601`. (M/L)
11. ✅ FEITO (jun/2026) **Skills Hub multi-fonte** — `okami/skills/sources.py`: `classify_source` (local/
    github/clawhub/url/well-known) com TIER de confiança (builtin>trusted>community>unverified), taps
    configuráveis (`okami skill tap <org>`, embutidos: anthropics/openai/nousresearch/huggingface/okamiops),
    `fetch_wellknown` (índice `/.well-known/skills/index.json`, SSRF-guarded, fail-open), e a MATRIZ
    `install_decision(trust, verdict)` — auto (trusted+limpo) / confirm (community) / BLOCK (HIGH+ sempre,
    segurança vence confiança). Ligado no `okami learn` (mostra tier + aplica a política). Sobre a base que
    já existia (quarentena + scan + lockfile sha256).
12. **Skill bundles** — `/<bundle>` carrega N skills correlatas de uma vez. Ergonomia; retorno baixo com
    biblioteca pequena. `agent/skill_bundles.py`. (S/M)
- **NÃO fazer:** `trajectory_compressor.py` (69KB) é geração de DATASET de treino, não runtime — só
  interessa se o Okami for fine-tunar modelo próprio. Nudges de memória e snapshot congelado: núcleo já
  existe no Okami (`_should_review` + `core_block` congelado).

## 3. SEGURANÇA / PROVIDERS / SEGREDOS / CUSTO

### ⭐ S/M — alto retorno
13. ⭐ **Smart approvals (juiz LLM)** — ~70% scaffolded: o slot aux `"approval"` JÁ está reservado em
    `okami/llm/aux.py`. No `Approver.__call__` modo `smart`, chamar `aux_complete(cfg,"approval",…)` →
    APPROVE/DENY/ESCALATE (temp 0, 16 tokens, fail-closed→ESCALATE). Só a escalação chega no humano —
    corta ruído de aprovação no Telegram. `tools/approval.py:990`. (S/M)
14. ⭐ **Janelas de uso de ASSINATURA** — bate em `api.anthropic.com/api/oauth/usage` (five_hour/seven_day…
    com utilization + resets_at) e codex `/wham/usage`; "X% restante, reseta em Yh". É a pergunta-chave de
    um agente subscription-only e o Okami é subscription-only. Reusa o token OAuth já resolvido.
    `agent/account_usage.py:439,487`. (M)
15. **Catálogo de advisories de supply-chain** — pacotes comprometidos conhecidos checados no boot via
    `importlib.metadata.version()` (barato), banner acknowledgeable (`doctor --ack`), re-banner 24h.
    `hermes_cli/security_advisories.py`. (S)
16. **sudo -S stdin guard** — bloqueia incondicional `sudo -S` sem SUDO_PASSWORD setado (= LLM chutando
    senha), antes do yolo. Fecha vetor que o gate normal (que o yolo pula) não cobre. `approval.py:307`. (S)
17. **Guard de modelo caro** — preço >$20/M input → confirmação antes de selecionar + did-you-mean de typo.
    `model_catalog.py` do Okami não tem custo. Relevante p/ provider pay-per-token (minimax). `model_cost_guard.py`. (S/M)
18. **Headers x-ratelimit-*** exibidos no /usage — 12 headers, 4 janelas, ⚠ ≥80%. Útil p/ minimax/openai-
    compat (codex/claude não mandam). `rate_limit_tracker.py`. (M)

### L
19. ⭐ **Secret sources / Bitwarden** — abstração de fonte de segredo plugável que injeta env no boot DEPOIS
    do .env (não-destrutivo, fail-never-block); BSM via `bws`: só `BWS_ACCESS_TOKEN` no .env, resto no cofre.
    Casa com o hard-constraint "secrets nunca em texto". Padrões reusáveis: SHA pin, zip-slip guard, cache
    0600. `agent/secret_sources/bitwarden.py`. (L)
20. **Pool de credenciais persistente** — status ok/exhausted/dead + TTL por classe de erro, persiste em
    disco (cross-restart/processo), com sanitizador de segredo emprestado antes de escrever. Okami é
    in-memory (2 dicts). `credential_pool.py` + `credential_persistence.py:151` (a joia de segurança). (L)
- **NÃO fazer:** Portal/Tool Gateway é integração de provider específico (Nous), não postura.

## 4. PLATAFORMAS & GATEWAY

### ⭐ M — alto retorno
21. ⭐ **/insights [--days N]** — analytics histórico cross-sessão: tokens/custo/tools/skills por período,
    breakdown por PLATAFORMA e por MODELO. O Okami JÁ coleta os dados (`sessions.add_usage` + `served_by` +
    events.jsonl) — falta o agregador. Maior valor de gateway p/ dono-único. `agent/insights.py:513`. (M)

### S/M
22. **platform_hint no ChannelSpec** — string injetada no system prompt por superfície ("você está no
    Slack, use mrkdwn"). Barato, melhora a voz por-canal (casa com voice-design). `platform_registry.py`. (S)
23. **Circuit breaker por-plataforma + /platform list|pause|resume** — marca canal falho/pausado, para o
    poll, expõe list/pause/resume. Útil quando token expira. `gateway/run.py:3170`. (M)
24. **standalone_sender_fn + delivery mirror** — envio de cron fora do processo + espelha entrega no
    transcript do canal-alvo. Só se opera 2+ canais ativos. `gateway/mirror.py`. (S/M)
- **NÃO fazer (anti-valor dono-único):** WhatsApp (~3000 LOC, Node/Baileys, risco ban), Signal (~1500 LOC,
  Java signal-cli), Home Assistant. **Email** (780 LOC stdlib) é o único barato mas a UX de poll atrita com
  "confidente em tempo real" — experimento futuro, não prioridade.

## 5. BACKENDS DE EXECUÇÃO

### ⭐ S/M — endurecimento barato + persistência sem SaaS
25. ⭐ **tmpfs noexec no Docker** — `/tmp`,`/var/tmp`,`/run` como tmpfs `noexec,nosuid` com tamanho-limite.
    Corta o vetor "dropa binário em /tmp e executa". Poucas flags no `docker_argv`. `docker.py:334`. (S)
26. **Reuso de container entre sessões + sessão de shell stateful** — container labelado (task_id,profile)
    com `docker start` em vez de `--rm` por comando; env/cwd persistem cross-call. Entrega o benefício
    "ambiente sobrevive entre turnos" que o Modal vende como hibernação, mas só com Docker LOCAL (casa com
    confiabilidade/dono-único). `docker.py:815`, `base.py:351`. (M)
27. **cap tuning fino** — dropa ALL e re-adiciona só o necessário por modo. O `--cap-drop ALL` puro do Okami
    é mais seguro, só menos compatível; ajustar se aparecer fricção. `docker.py:328`. (S, opcional)
- **NÃO fazer:** backends SSH/Modal/Daytona/Singularity. SSH é o único defensável (vetor de segurança, sem
  billing) mas exige extrair a interface ABC + file-sync (L) — só pague com caso de uso remoto concreto.
  Modal/Daytona/Singularity dependem de SaaS pago — antítese do subscription-only/dono-único.

## 6. INTERFACES & INFRA

### M — valor real
28. **ACP profundo** — o `integrations/acp.py` (91 linhas) faz initialize/session.new/prompt mas devolve
    tudo num chunk. O que falta p/ usar em Zed/VS Code: streaming token-a-token, session/cancel real, fork/
    resume/list_sessions, edit-approval com diff inline. Evoluir incremental (streaming+cancel+edit primeiro).
    `acp_adapter/` (5167 linhas). (L → começar M)
29. **mcp_serve** — servir o PRÓPRIO agente como servidor MCP (9 tools: conversations/messages/attachments/
    events/permissions) p/ Claude Code/Cursor/Codex consumirem o histórico e as mensagens do Okami. Hoje só
    consome MCP. Contrato pequeno, FastMCP sobre o event log/sessões que já existem. `mcp_serve.py`. (M)
30. **cron — 3 lacunas pontuais** — persistir histórico de output (`~/.okami/cron/output/{id}/{ts}.md`),
    `next_run_at` pré-calculado, jobs sem-agente/script puro (stdout sem gastar LLM). O resto do cron já é
    paridade. `cron/jobs.py:5,373,559`. (S cada)
- **NÃO fazer (fora de escopo, dono-único):** app desktop Electron (~89k linhas TS — segundo produto),
  batch_runner/mini_swe_runner (research/treino), tui_gateway (só compensa com desktop/multi-cliente).

## Ordem de implementação recomendada

ONDA A (S, segurança + bug) — ✅ CONCLUÍDA (jun/2026): bug do alias search_files (corrigido junto do
item 2) → 8 (scan de injeção na memória write+load → [BLOCKED]) → 16 (sudo -S guard, no detect_hardline)
→ 15 (advisories supply-chain, catálogo + doctor --ack) → 25 (tmpfs noexec docker) → 9 (drift guard
.bak por hash sidecar)

ONDA B (S/M, capacidade + subscription) — ✅ CONCLUÍDA (jun/2026): 1 (web_search DDGS zero-key, extra
`[web]`) → 2 (search_files conteúdo: regex/glob/context/count/paginação, jailed, redige segredo; alias
'grep/search'→search_files) → 13 (smart approvals: smart_judge fail-closed, slot aux 'approval', wired
no gateway) → 14 (janelas de uso de assinatura: account_usage.py codex/anthropic, no /usage — testado
AO VIVO no codex) → 21 (/insights: agrega event log por dia/modelo/provider/plataforma; CLI + gateway)

ONDA C (M, profundidade) — ✅ CONCLUÍDA (jun/2026): 10 (session_search: índice FTS5 dedicado sobre
transcripts ativos+arquivados, reindex incremental, tool) → 3 (web_extract: chunk+resume via aux) →
4 (vision_analyze: imagem→aux multimodal, data-uri, fast-path) → 6 (lint-on-write delta: validação
stdlib py/json/toml/yaml, só erro NOVO, em write/edit) → 22 (platform_hint no ChannelSpec → prompt) →
30 (cron: next_run_at, output histórico .okami/cron/output, jobs SCRIPT sem-LLM)

ONDA D (M/L, estratégico) — ✅ CONCLUÍDA (jun/2026): 29 (mcp_serve: OkamiMcpServer JSON-RPC sobre
sessões/memória, `okami serve-mcp` stdio — testado ao vivo) → 28 (ACP profundo: AcpServer com
streaming de tool-calls via session/update + session/cancel) → 19 (secret_sources: Bitwarden BSM via
bws, injeta env pós-.env não-destrutivo fail-never-block, no boot da config) → 26 (reuso de container:
docker_run_persistent_argv + docker_exec_argv, container long-lived por ws+perfil, opt-in
reuse_container) → 20 (cred_pool persistente: ok/exhausted/dead + TTL por classe, fingerprint sha256
no disco, ligado no _park_key/_available_pool) → 23 (circuit breaker: PlatformBreaker backoff
exponencial no poll loop + /platform list|pause|resume)
NÃO incluído da onda D (faltava caso de uso / fora do core): ACP edit-approval com diff inline
(streaming+cancel entregues; o diff-approval na IDE fica p/ quando houver cliente testando ao vivo).

FORA DE ESCOPO (decisão explícita): desktop app, batch/SWE runner, tui_gateway, WhatsApp/Signal,
backends Modal/Daytona/Singularity/SSH, trajectory_compressor, Portal/Tool Gateway.
