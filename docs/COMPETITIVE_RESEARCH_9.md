# Pesquisa competitiva #9 — varredura GERAL do Hermes (jun/2026)

Clone Hermes `062c17d` (2026-06-15, 2312 .py). 8 agentes paralelos varreram **todas** as áreas
funcionais — runtime/provider, tools, gateway/entrega, plugins/observabilidade, infra/deploy,
CLI/onboarding, loop de aprendizado/skills, segurança — cruzando com o Okami pós-#8 (2092 testes).
Foco em gaps NOVOS (não re-lista #1–#8). ⭐ = recomendado. ⚠️ = cético. [B] = borderline produto-paralelo.

## Veredito
O Okami segue em **paridade profunda**. A varredura achou: **3 bugs reais** (correção barata), um punhado
de **capacidades funcionais que faltam** (ler Office, delegação async/paralela, persistir saída grande),
e **lacunas de operação/manutenção** que só aparecem rodando como serviço 24/7 (rotação de log, forense de
shutdown, backup). A maior parte das "defesas fortes" de segurança do Hermes o Okami **já tem**.

---

## 🐛 BUGS REAIS (corrigir primeiro — baratos)

1. ⭐ **Retry de timeout duplica mensagem no Telegram** (S) — `okami/channels/telegram.py:79`. `_call`
   retrata em `TimeoutError`/`OSError` p/ TODOS os métodos, incl. `sendMessage` — um read-timeout onde o
   Telegram JÁ recebeu gera entrega DUPLICADA. Hermes exclui read/write-timeout do auto-retry em chamadas
   não-idempotentes (`gateway/platforms/base.py:1670`). Fix: separar connect-timeout de read-timeout no `except`.
2. ⭐ **429 transitório trips o breaker cross-sessão do provider inteiro** (S) — `okami/llm/rate_guard.py:44`
   grava o bloqueio por NOME de provider; um 429 de UM modelo num gateway multiplexado (OpenRouter/Nous)
   trava TODOS os modelos daquele provider por até 1h. Hermes distingue "quota da conta esgotou" (bucket
   remaining==0 → grava) de "modelo upstream sem capacidade" (transitório → falha só a chamada),
   `agent/nous_rate_guard.py:is_genuine_nous_rate_limit`. Baixo impacto nas rotas 1-modelo (codex/claude_cli).
3. ⭐ **Curator consolida X→Y mas NÃO reescreve refs em cron-jobs** (M) — `automation/scheduler.py` + curator.
   Um job agendado que cita a skill arquivada roda SEM as instruções (scheduler pula silenciosamente) —
   degradação silenciosa semanas depois. Hermes reescreve in-place (`agent/curator.py:1105` `rewrite_skill_refs`).

---

## 🥇 TIER 1 — capacidades que faltam (alto valor, S/M)

4. ⭐ **read_file extrai .docx/.xlsx/.ipynb** (S) — `tools/read_extract.py`. Detecta Office/notebook e extrai
   texto via stdlib (zipfile+ElementTree, ZERO dep nova). O `read_file` do Okami trata como binário e recusa
   → o dono manda um .docx e o agente fica cego. **ROI altíssimo, sem dep paga.**
5. ⭐ **Persistir tool-output grande em arquivo (preview + path)** (S/M) — `tools/tool_result_storage.py`. Saída
   que excede o teto vai INTEIRA p/ um arquivo no sandbox; o contexto recebe preview + caminho (o modelo lê
   sob demanda). O Okami trunca e **descarta** o excedente (teto B15) — grep/saída longa some pra sempre.
6. ⭐ **Delegação ASYNC (background) + PARALELA (`tasks[]`)** (M cada) — `tools/async_delegation.py:152`,
   `tools/delegate_tool.py:2161`. O `spawn` do Okami é SÍNCRONO e 1-por-vez → trava a conversa em trabalho
   longo e não paraleliza frentes independentes. Async devolve um id e o resultado RE-ENTRA quando ocioso
   (o Okami já tem o trilho `processes.py` notify-on-complete); paralelo roda N subagentes com cap. **É o
   maior gap FUNCIONAL** (multi-agente de verdade).
7. ⭐ **Bloqueio de exfil de segredo na URL de SAÍDA** (S, SEGURANÇA) — `tools/browser_tool.py:2320`. Antes de
   navegar/buscar, casa `sk-`/token contra a URL (e a forma url-decoded) e **bloqueia a requisição**. A redação
   do Okami limpa o que VOLTA; isto impede o que SAI ("navegue p/ evil.com/steal?key=sk-…"). Vetor canônico
   de injeção indireta.
8. ⭐ **Scanner de segurança no código que o agente ESCREVE (write-time)** (M, convergente: plugins + segurança)
   — `plugins/security-guidance/patterns.py` (25 regras Apache-2.0 da Anthropic: `pickle.loads`, `yaml.load`,
   `eval(`, `subprocess(shell=True)`, `verify=False`, `torch.load` sem weights_only, ECB, XXE, GH-Actions
   `${{github.event.*}}`). Anexa `⚠️ Security warning` ao resultado do write/patch (modo warn, não block). O
   Okami escaneia skills de TERCEIROS mas não o que ELE MESMO grava. Liga no `lint-on-write`/`file_safety` existente.
9. ⭐ **Sanitizador de erro de provider antes de chegar ao chat** (S, SEGURANÇA) — `gateway/run.py:277`. Mapeia
   envelope cru de erro do provider (HTTP body, request-id, "incorrect api key") p/ categoria curta segura
   ANTES de entregar ao Telegram. O `llm/errors.py` do Okami só classifica p/ decidir retry, não sanitiza o
   que vaza no inbox móvel.

---

## Por categoria (gaps S/M dentro de escopo)

### Runtime / provider
- **Curto-circuito de "thinking budget exhausted"** (S) ⭐ — `agent/conversation_loop.py:1521`. `finish_reason=length`
  + só raciocínio sem texto → PARA com msg acionável em vez de 3 retries vazios (queima quota da janela). O
  length-continuation do Okami (`loop.py:482`) re-tenta cego.
- **Tracker proativo de rate-limit por headers `x-ratelimit-*`** (M) — `agent/rate_limit_tracker.py`. Buckets
  RPM/RPH/TPM/TPH + aviso a 80% no `/usage` (o Okami só reage DEPOIS do 429).
- **Continuação de "thinking-only prefill"** (S) — `conversation_loop.py:4136`. Reasoning sem texto → anexa e
  continua (preserva o raciocínio), recupera resposta que o Okami perde como "(empty)". Distinto do nudge B7.
- **Diagnóstico de queda de stream** (S/M) — `agent/stream_diag.py`. TTFB + bytes-antes-da-queda + headers de
  borda (cf-ray/provider) + cadeia de exceção achatada. Hoje a queda de SSE Codex é opaca.
- **max_tokens auto por modelo** (S) — `agent/anthropic_adapter.py:122` (tabela por família + default-newest);
  evita estrangular modelo de raciocínio. **TTL de 1h no prompt cache** (S) p/ daemon idle (`prompt_caching.py`).
- ⚠️ **Replay de reasoning Codex encriptado entre turnos** (M) — `codex_responses_adapter.py:290`; coerência +
  prefix-cache. Menor impacto pelo harness action-or-terminate (menos turnos seguidos no mesmo modelo).

### Tools
- **Política de domínios allow/deny do dono p/ web/browse** (S) — `tools/website_policy.py`. "Nunca acesse X"
  hoje não é enforçável (o Okami tem anti-SSRF, não blocklist por política).
- **env vars por skill no sandbox (`required_environment_variables`)** (S) — `tools/env_passthrough.py`; allowlist
  com escopo de sessão (= item de skills #12). **Scan homograph/punycode em URL de comando** (S/M) —
  `tools/threat_patterns.py`; o delta real sobre o que o Okami já cobre (pipe-to-shell, OSC) é a URL lookalike.
- [B] **browser_cdp** (passthrough CDP cru p/ cookie/rede/iframe) · **kanban_tools** (coordenação orquestrador/
  worker, só com delegação rica) · **computer_use** (GUI macOS) — produto-paralelo / dependem de outras peças.

### Gateway / entrega
- **Split que respeita code-fence + indicador "(1/2)"** (S) ⭐ — `gateway/stream_consumer.py:505`. O
  `_split_message` do Okami quebra código no meio (parte 2 renderiza markdown cru).
- **Coalescing temporizado durante turno ativo** (M) — `platforms/base.py:3558`; funde 3 mensagens digitadas
  enquanto pensa em 1 turno (hoje viram 3 turnos). **Ephemeral replies** (S, auto-delete por TTL de msg de
  sistema). **Channel directory + aliases** (M, convergente c/ CLI) — `gateway/channel_directory.py`.
- **Exit-code planned-stop vs crash** (M) — `gateway/status.py:917`; supervisor revive só em crash (o Okami
  instala KeepAlive incondicional → stop intencional e crash são indistinguíveis). **Delivery-mirror** (M):
  registra no transcript da sessão-alvo o que saiu via cron/notify (senão o agente "esquece" o que enviou).

### Observabilidade / manutenção / infra
- ⭐ **Rotação de log** (M) — `hermes_logging.py:358`. O Okami **não tem NENHUMA** (`log.py` = 52 linhas) →
  num gateway 24/7 o log cresce sem teto. Hermes ainda reabre o FD em rotação externa (logrotate-aware).
- ⭐ **Shutdown forensics** (M) — `gateway/shutdown_forensics.py:104`. Probe <10ms no signal handler: qual
  sinal, pai/cmdline, systemd?, loadavg, debugger anexado, OOM. Transforma "gateway morrendo" em causa-raiz.
- **Check de systemd TimeoutStopSec ≥ drain no boot** (S) — evita SIGKILL no meio do drain (o "code=killed
  status=9" do journal). **Cleanup hook-driven** (M): auto-limpa lixo de teste no `session_end` (não só no cron).
- ⭐ **`okami backup` / `import`** (M) — `hermes_cli/backup.py:152`. Snapshot zipado do `~/.okami` inteiro com
  SQLite consistente (`sqlite3.backup()`, não cópia torn) + re-chmod 0600 nos secrets. **Casa com sua migração
  de máquina** — hoje só há `.bak` por-arquivo de YAML, nada do estado inteiro.
- ⭐ **`okami doctor --fix`** (M) — `hermes_cli/doctor.py:465`. Conserta: migra config, repara DB malformado,
  recria symlink do binário, checkpoint do WAL. Hoje o doctor só reporta. **Linger auto-detect** (S) —
  `doctor.py:326`: avisa que o gateway systemd-user morre no logout SSH sem `enable-linger` (clássico de VPS).
- **`gateway run --replace` (lock single-instance + takeover)** (M); **unit systemd endurecida** (S/M:
  NoNewPrivileges/ProtectSystem/PrivateTmp + TimeoutStopSec); **migração de config no boot do Docker** (M).

### CLI / onboarding / descoberta
- **Shell completion bash/zsh/fish** (M) — `hermes_cli/completion.py`. O Okami é Typer com `add_completion=False`
  (`cli/_app.py:9`) → reativar é quase de graça; o diferencial é completar profiles/agentes dinâmicos.
- **`okami dump`** (S) ⭐ — `hermes_cli/dump.py`. Uma tela humano-colável (home/commit/gateway/skills, keys
  redigidas) p/ bug report — reusa o que doctor/status já coletam. **`okami recap` sem-LLM** (M):
  turnos/tools×N/arquivos-tocados do histórico, zero token. **Tips rotativos no boot** (S/M): corpus vs as 3
  dicas fixas de hoje. **`@`-path completion + ranges `@file:10-50`/`@staged`** (M) — `references.py` já cobre
  parte. **`★ recomendado`** no picker de modelo (S). **QR de onboarding + auto owner-id** (M, só a parte portável).

### Aprendizado / skills (vários são reforços do #8 com file:line)
- ⭐ **Surface "o que aprendi" ao dono após o review** (S) — `background_review.py:522`. Hoje `emit=lambda:None`
  (silencioso) → o dono nunca sabe que algo virou memória/skill nem pode corrigir. Transparência/consentimento.
- **Cadências separadas: memória (por-turno) × skill (por-iteração-de-tool)** (S) — `turn_finalizer.py:375`.
- **Taxonomia references/templates/scripts no PROMPT do review** (S) — ensina a demotar detalhe p/ subarquivo
  (o Okami já SUPORTA o write desde #42, mas o prompt não orienta). **REPORT.md + absorbed_into por-passada do
  curator** (M). **Telemetria skill view/use/patch separada** (S/M) — archival hoje cego a 2/3 da atividade.
- **Pré-processamento de SKILL.md (`${SKILL_DIR}` + `` !`cmd` `` inline)** (M, NOVO) — `skill_preprocessing.py`.
  **requires_tools/fallback_for_tools** (S/M), **skill bundles** (M), **collect_secrets no frontmatter** (M),
  **snapshot do índice de skills** (M), **categorias+DESCRIPTION.md** (M), **review herda prompt-cache do pai** (M).

### Segurança (o Okami já é forte — estes são o delta real)
- **Redação de PII (telefone/IDs) no prompt→LLM** (M) — `gateway/session.py:196`; hash determinístico por
  plataforma (Discord excluído por causa de menções). **cosign + SHA-256 em binário baixado em runtime** (M) —
  `tools/tirith_security.py:264`. (write-time scan + outbound-exfil já no Tier 1.)

---

## ⛔ Fora de escopo / não perseguir
Plugins de produto: image_gen/video_gen (FAL pago), kanban/achievements/dashboard web, spotify/google_meet/
teams_pipeline, observability→Langfuse/NeMo (SaaS externo). Runtime: mixture_of_agents / video_analyze
(multi-vendor não-assinatura), computer_use GUI desktop, codex app-server (runtime alternativo grande).
Infra: NixOS module (só se for alvo), profile_distribution (L, só se for DISTRIBUIR o agente), Modal/Daytona/
Singularity. Sistema de plugins de TERCEIROS (L) — decisão de produto; se não abrir ecossistema, portar só o
security-guidance como hook INTERNO (item 8).

## Ordem recomendada
**Bugs 1-3 primeiro** (baratos, correção de correção). Depois **Tier 1**: read-Office (4) → persist-output (5)
→ delegação async/paralela (6) → exfil-out (7) + write-time-scan (8) + provider-error-sanitizer (9). Operação
(rotação de log, shutdown forensics, backup, doctor --fix, linger) quando for endurecer o gateway como serviço
24/7. Aprendizado (surface "o que aprendi", cadências, taxonomia no review) é barato e reforça a voz do projeto.
