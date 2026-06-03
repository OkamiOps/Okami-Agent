# Okami Agent — Roadmap (plano em fases)

> Acompanha `ARCHITECTURE.md` v0.4. Stack: **Python 3.12+ / uv / LiteLLM**. Referência rodável:
> [build-your-own-openclaw](https://github.com/czl9707/build-your-own-openclaw) (18 passos) + Hermes.
> Ordem pedida pelo usuário: provar as 2 dores → **Telegram cedo** → **auto-melhoria + memória**
> → persona evolutiva + gosto de design. As fases 1, 1.5, 2, 5, 6 e 7 são o coração.
>
> Mapa repo→fases: 00/01→F0/F1 · 02 skills,06 web→F2/F12 · 03/05/17→F4/F4.5 ·
> 04/09/14→F3/F11 · 07/08/12→F10 · 11/15/16→F9 · **13 multi-layer-prompts→F6 (persona)**.

---

## Fase 0 — Fundação ✅ (feita 2026-06-03)
- [x] Projeto Python + pydantic + pyproject (venv em `C:\okv` por causa de long-path no OneDrive).
- [x] `okami/config.py`: loader de `okami.yaml` + `.env`; ProviderConfig com `tier` (§3.5).
- [x] `okami/providers.py`: wrapper **LiteLLM** (5 providers: lmstudio, codex, claude, minimax, mimo).
- [x] `okami/cli.py`: `okami run` (streaming) + `providers` + `doctor` + `version`.
- [x] **Verificado**: `okami run` gera via LMStudio local; override `-m` herda prefixo de roteamento.
- [ ] (pendente do usuário) confirmar ids/bases de codex/minimax/mimo + chaves no `.env`.
- [ ] (depois) YAML hot-reload, lint/format, migrar para uv.
**Saída:** ✅ `okami run "..."` responde via LMStudio (ref.: passo 00-chat-loop).

## Fase 1 — Harness confiável (DOR #1) ⭐ ✅ (feita 2026-06-03)
- [x] `okami/core`: máquina de estados (`harness.py`) + tools (`tools.py`: read/write/list/shell + terminais).
- [x] **Action-or-Terminate** + reconciler de intenção (futuro PT/EN) — texto sem ação é rejeitado.
- [x] Protocolo de **ação JSON** model-agnóstico (base da paridade; modos nativos na Fase 1.5).
- [x] Watchdog/stall + orçamentos + `exitCriteria` verificados (file_exists/shell_ok/file_contains).
- [x] **Anti-loop (§3.6)**: fingerprint+dedup, detecção de ciclo, circuit breaker, backstops (harness sempre termina).
- [x] **Anti-alucinação (§3.7)**: grounding no write (não sobrescreve arquivo não-lido).
- [x] **8 testes** passando (trava-nunca, loop-nunca, conclusão-falsa-barrada, grounding).
- [x] **Verificado ao vivo**: `okami task` com modelo LOCAL (qwen3.6-35b) concluiu tarefa real com critério verificado.
- [ ] (Fase 1.5) checagem de existência de símbolo/pacote (anti-slopsquatting), self-consistency, escada de escalonamento p/ modelo forte.
**Saída:** ✅ harness não trava, não gira, não aceita conclusão falsa — provado por testes + run real.

## Fase 1.5 — Paridade de capacidade entre LLMs ⭐⭐ (parcial — 2026-06-03)
- [x] **Constrained decoding** p/ locais via **response_format json_schema** (LMStudio). VERIFICADO:
      modelo de **2B** concluiu tarefa real emitindo ação JSON válida.
- [x] **Capability profile** por provider (`capability.tool_mode`: json_text | json_constrained | native).
- [x] **Cascata/escalonamento**: `--escalate <provider>` — modelo fraco travou → troca p/ o forte
      (testado: weak nunca age → strong conclui).
- [ ] Tool-call **nativo** + auto-reparo de tool-call malformado (json_constrained já cobre a confiabilidade).
- [ ] **Decomposição externalizada** + **tool subsetting** + **self-consistency**.
- [ ] Bench de paridade (Haiku / GPT-5.4-mini / local vs. forte) + auto-tune do profile (Fase 5).
**Saída:** ✅ base da paridade no ar — local/fraco roda o harness de forma confiável + cascata.

## Fase 8 (antecipada) — Providers de assinatura (OAuth) — parcial 2026-06-03
- [x] Camada de **transports** (`okami/transports.py`): litellm | claude_cli | codex_oauth.
- [x] **Claude via assinatura** (CLI `claude -p`, sancionado, ToS-ok). **VERIFICADO AO VIVO**.
- [x] **Codex via auth.json** (backend-api/codex/responses) — implementado, **não testado ao vivo** (schema a confirmar).
- [ ] MiniMax-M3 / MiMo via token plan (api_key) — aguardando chaves; refresh automático de tokens.

## Fase 2 — Contracts + Skills + Verification Gates (DOR #2) ⭐ (núcleo — 2026-06-03)
- [x] **Contracts** em `okami.yaml` (`contracts.ui`) carregados na config.
- [x] **Verification gate** (`okami/contracts.py`): anti-hex-inline, anti-`<style>`, anti-`style={{}}`,
      require import da lib (`@/components/ui`). Comando `okami gate [path]`.
- [x] **Integrado ao harness**: critério `-e ui_gate` rejeita `task_complete` com UI feia até passar.
- [x] Testes: gate flag UI feia / passa ShadCN limpo; e2e no harness (feio→rejeitado→ShadCN→COMPLETE).
- [x] **Skills runtime + router** (`okami/skills.py`): SKILL.md (agentskills.io) + skills FORÇADAS
      por contrato/keywords, injetadas no system prompt do harness (`system_extra`).
- [x] Skills `frontend-shadcn`/`frontend-heroui` que **ensinam a instalar/inicializar** a lib no
      projeto (npm/npx shadcn init) — NÃO pré-instalado, o agente faz via run_shell.
- [x] **skill.sh + ClawHub** com VALIDAÇÃO: `okami learn <fonte>` (quarentena → scan → promove);
      `okami scan <path>`; `okami skills`. Scanner `okami/skill_security.py` (prompt injection,
      malware, exfiltração de segredos, combo segredo+rede). Router se recusa a injetar skill
      bloqueada. Fontes: owner/repo, URL, git, `clawhub:<slug>`.
- [ ] `minComponentReuse` por AST + build/typecheck automático no gate (shell_ok já cobre build).
**Saída:** ✅ frontend que ignora o design system é impossível concluir (skill forçada + gate mecânico).

## Fase 3 — Telegram ✅ (feito 2026-06-03, depois do multi-agente p/ não refazer)
- [x] `okami/channels/telegram.py` (cliente urllib: getUpdates long-poll + sendMessage) +
      `okami/gateway.py` (`AgentBot` + `run_gateway`). **Um bot por agente** (channels.telegram.token).
- [x] Mensagem → `runner.run_task` no workspace do agente → resposta com status. `okami gateway`.
- [x] **Go/No-Go por chat** (`/yes`/`/no`, timeout fail-closed) + `allow_chats`. Reusa o roteamento §10.
- [x] `runner.py` extraído (CLI `task` e gateway compartilham). 6 testes (cliente fake).
- [x] **Estrutura robusta (estilo OpenClaw)**: abstração `Channel` (`channels/base.py`) +
      `TelegramChannel`; **Sessões** com continuidade (histórico injetado); **slash commands**
      (/new /reset /status /stop /yolo /normal /help); **concorrência** (1 tarefa/sessão);
      `/stop` cancela de verdade (callback no harness). 11 testes.
- [x] **VOZ** (`okami/voice/`): STT Whisper local (faster-whisper) — áudio Telegram → transcreve;
      TTS Edge (grátis) / MiniMax → resposta em áudio. CLI `transcribe`/`say`. **Verificado ao vivo**:
      transcreveu o sample m4a do user; Edge gerou mp3. Extra `[voice]`. (5 testes)
- [ ] Botões inline, persistência de sessão + auto-resume após crash. (Live Telegram: token do user.)
**Saída:** ✅ Telegram robusto (um bot/agente, sessões, slash, go/no-go por chat, /stop, VOZ).

## Fase 4 — Memória plugável + auto-compaction (núcleo — 2026-06-03)
- [x] `okami/memory/`: interface `Memory` (inject/recall/recent/write) + arquivos `MEMORY.md` (`files.py`).
- [x] Backend **`sqlite-fts5`** HÍBRIDO (`sqlite_fts5.py`): **BM25** (insensível a acento) + recência
      + importância + **embeddings OPCIONAIS** (OpenAI-compat: llama.cpp/Ollama/LMStudio) com probe +
      circuit breaker → **nunca depende de embeddings**. **Dedup** + **forget**. Verificado ao vivo
      (busca semântica + degradação p/ BM25).
- [x] Tools `remember`/`recall_memory` + injeção no prompt + extract ao concluir + `okami memory add/search/list`.
- [x] **Auto-compaction**: PROMOVE mensagens antigas à memória (recuperáveis) + ponteiro; "nada perdido". → promove + ponteiros → reidrata.
      Testes "compactou e esqueceu".
- [x] **6 testes** (FTS recall, inject, compaction promove+encurta+recuperável, dedup) + verificado ao vivo (extract → MEMORY.md).
- [x] Cliente **MCP** (`okami/mcp.py`): stdio JSON-RPC síncrono (sem dep extra). Conecta servidores
      (`mcp.servers` no yaml), lista tools e as **embrulha como tools nativas** do harness (mesmas
      invariantes: args, anti-loop, go/no-go). `okami mcp` lista. Testado contra servidor-mock +
      verificado ao vivo (harness chamou tool MCP e concluiu). HTTP/SSE = futuro.
**Saída:** ✅ lembra cross-sessão; comprime sem perder decisões; consome servidores MCP. **FASE 4 COMPLETA.**

## Fase 4.5 — Backends avançados (PRIORIDADE: daily-driver do user = holographic + honcho)
- [x] **`holographic`** (`okami/memory/holographic.py`): HRR/numpy LOCAL (codebook tokens+trigramas,
      superposição), pluga no backend rápido. **Sem servidor de embedding.** + bind/unbind/cleanup.
      4 testes; verificado ao vivo (recall semântico-lexical sem embedder).
- [x] **`honcho`** (`honcho_backend.py`): SDK `honcho-ai` (peer/session/add_messages, `peer.chat`
      dialético), **base_url remoto** (VPS via Tailscale), dep opcional `[honcho]`. Testes mockados.
      (validação ao vivo na instância do user — não acessível daqui).
- [x] **Memória em CAMADAS** (`layered.py`): holographic (local) + honcho (user-model remoto); write
      fan-out, inject concatena, recall merge+dedup. **Tolerante**: honcho offline → segue só holographic.
- [x] **Config distribuída**: `backend` aceita lista; embedder/honcho por host (Tailscale); `okami doctor`
      mostra memória/embedder/honcho. Verificado: doctor + degradação da camada.
**Saída:** ✅ holographic+honcho como daily-driver; sqlite-fts5 fallback público; tudo distribuível.

## Fase 4.6 — Camada de arquivos .md + setup (2026-06-03)
- [x] **`AGENTS.md` + `USER.md` + `MEMORY.md`** sempre injetados (`files.core_block`), **limites
      configuráveis** (default 4000 chars, maiores que Hermes). Writeback: `remember`/`remember_user`/extract.
- [x] **`okami setup`** (interativo + flags): escolher backend (fts5 / holographic / holographic+honcho),
      honcho base_url, embedder → grava `okami.local.yaml` (merge sobre okami.yaml, preserva comentários).
- [x] `okami doctor` mostra .md/limites; 5 testes (core_block caps, append_user dedup, merge, setup).
- [x] **Identidade injetada** (parte estática da §8): `SOUL.md`→`VOICE.md`→`PERSONA.md`(/PROFILE.md)
      no topo do core_block, capados. `remember_user` (tool) + regra 6 do prompt = agente atualiza
      USER/MEMORY e evolui. `okami persona-init` cria stubs. Identidade evolui só pelo learning loop (§7/§8).
**Saída:** ✅ pessoa escolhe a memória no setup; identidade + .md persistentes sempre no contexto; agente evolui USER/MEMORY.

## Fase 5 — Auto-melhoria (closed learning loop) ⭐ (fatia 1 — 2026-06-03)
- [x] `okami/learning.py`: **reflexão pós-tarefa** → **anti-padrões** (falhas/bloqueios) e **lições**
      (sucessos) gravados na memória; **voltam INJETADOS** na próxima tarefa parecida (recall).
      Harness acumula `stats` (violations/loops/gate_rejections/denials). Verificado ao vivo.
- [x] **Auto-skill** ✅ (`learning.distill_skill`/`maybe_write_skill`): tarefa COMPLETE e NÃO-trivial
      (≥4 passos, ≥2 tools) → destila `skills/<slug>/SKILL.md`; **scan obrigatório** antes de ativar
      (gap Hermes #16461 — nunca grava skill insegura/injeção). Config `learning.auto_skill` (default off).
- [x] **Checkpoints/rollback** ✅ (`okami/checkpoints.py`, estilo Hermes): snapshot antes de cada
      `write_file` → `okami rollback [n]` desfaz escritas. Ligado por padrão no runner.
- [ ] **Auto-tune** do capability profile por modelo (usa os stats); reflexão por LLM opcional; skill via LLM.
**Saída:** ✅ anti-padrões (recall) + auto-skill (escaneada) + rollback de arquivos. Auto-tune a seguir.

## Fase 6 — Identidade & Persona evolutiva ⭐
- [x] Identidade injetada (parte estática): `SOUL.md`→`VOICE.md`→`PERSONA.md` no `core_block` (Fase 4.6).
- [x] **Gênese**: `okami persona-init` / `agent new` criam stubs únicos (nome/valores/voz).
- [x] **Evolução** versionada de VOICE/PERSONA ✅ (`okami/persona.py`): `propose`/`propose_llm`
      (heurística + LLM constrained) → `apply_evolution` com **go/no-go** → bullet incremental sob
      "## Evolução (aprendida)" + changelog `.okami/persona_history.jsonl` → `rollback`. **SOUL
      protegido** (só com `allow_soul` + aprovação). CLI `persona-evolve|persona-log|persona-rollback`;
      no Telegram `/feedback <...>` e `/undo`. A evolução entra no `core_block` (injetada no prompt).
- [x] **Auto-evolução gradual ✅** (`persona.observe`): o agente PERCEBE o estilo do usuário ao longo
      da conversa (palavrão/apelido/sarcasmo/registro técnico) e evolui VOICE/PERSONA **+ USER.md**
      SOZINHO, sem perguntar (gradual: `min_count`; reversível: `/undo`). Hook no gateway por mensagem.
**Saída:** ✅ identidade evolui sozinha e gradual com a conversa; reversível; SOUL ancora contra drift.

## Fase 7 — Aprendizado de gosto de design (taste model) ⭐ ✅
- [x] `okami/taste.py`: design = tags+descritor → vetor esparso (Counter, cosine, sem servidor de
      embedding); `TasteProfile` (atratores/repulsores + peso), persistido em `<ws>/.okami/taste.json`.
- [x] Feedback `approved`/`rejected`/`want_different` (`record_feedback`); approve→atrai + decai
      repulsor parecido; reject→repele; different→repulsão LEVE (0.5) = explora. Cap 24 (anti-overfit).
- [x] **Steering**: `score = sim(atratores) − sim(repulsores)`; `steer()` injeta "PREFIRA X / EVITE Y"
      no prompt de UI (runner, gated por contrato/skill de frontend). Cold-start pede VARIEDADE.
- [x] Crítico **soft** acoplado aos gates **hard** (§4.1) — o steer diz "os gates do contrato valem".
- [x] CLI `okami taste like|dislike|different|show|steer`; no Telegram `/like /dislike /different`.
- [ ] Promoção de estilo forte p/ VOICE/memória (liga taste→persona §8); tags via LLM; trust/decay temporal.
**Saída:** ✅ recusou→repele, aprovou→atrai, "diferente"→perto do gostado e longe do recusado; guia a geração.

## Fase 8 — Providers completos + roteamento
- [ ] Adapters **Claude Code** (sub), **Codex** (sub), **MiniMax**, **MiMo** (validar auth sub).
- [ ] Router custo/capacidade + fallback/rotação; `okami model <provider/model>`.
**Saída:** troca de provider em runtime; fallback automático (auto-tune da Fase 5 aplicado).

## Fase 9 — Multi-agente (profiles + workspaces) ✅ (núcleo — 2026-06-03)
- [x] `okami/agents.py`: `AgentSpec` + `load_agents()` (cada agente em `agents/<id>/` = workspace
      isolado com `agent.yaml` + identidade + `.okami/memória` próprios). `effective_config` =
      global + overrides do agente (deep-merge) → provider/memória/aprovação/persona por agente.
- [x] **Roteamento** (`Router`): bindings com tiers (exato > regex > wildcard) + default. Casa
      origem (`telegram:123`) → agente. Pronto pro Telegram-por-agente.
- [x] CLI: `okami agent new/list`, `okami task -a <id>`, `okami route <source>`. 5 testes + verificado ao vivo.
- [x] **Conversa em GRUPO / turn-taking** (`okami/group.py` `GroupRoom`): dispatch + eligibility gating
      (cooldown, @menção força), **moderador** LLM escolhe quem fala ou NINGUÉM (anti-stampede), silêncio
      intencional (PASS), cap bot-to-bot. CLI `okami room`. 8 testes (incl. cenário CTO+UI/UX do user).
- [ ] Delegação a subagentes; peer model do Honcho casado com profiles; sessões persistidas; grupo no Telegram (multi-bot).
**Saída:** ✅ agentes isolados + roteamento + **conversa em grupo como reunião de empresa** (sem spam).

## Fase 10 — Scheduling & Eventos ✅
- [x] **Scheduler** ✅ (`okami/scheduler.py`): cron (5 campos), intervalos ("1h","every 30m","2h30m"),
      one-shot (ISO). Persiste em `.okami/cron.json`; `is_due` (cron casa minuto+dia-da-semana, não roda
      2x/min; intervalo por elapsed; once desativa após rodar). CLI `okami cron add/list/remove/run/tick`.
      Gateway sobe um loop que entrega o resultado no chat (estilo OpenClaw cron→canal). Roda pelo harness (§3).
- [x] **Event hooks/plugins** ✅ (`okami/hooks.py` `HookManager`): `before_task`/`after_task`,
      `before_tool`/`after_tool`, etc. `before_*` pode VETAR (config exit≠0 / handler False). Fontes:
      config `hooks:{evento:[cmd]}`, pasta `hooks/<evento>/*`, in-process. Wired no runner (before/after_task)
      e harness (before_tool veta). CLI `okami hooks`. Heartbeat = Paperclip (§13).
**Saída:** ✅ tarefas agendadas (cron) + reações/políticas por hooks, tudo na máquina de estados (§3).

## Fase 11 — Slack + Paperclip
- [x] Adapter **Paperclip** ✅ (`okami/channels/paperclip.py` — `PaperclipClient` + `run_heartbeat`): heartbeat
  completo (me → list issues → checkout → harness → PATCH done/blocked/in_review), 409=para sem retry,
  go/no-go vira `interactions` (governança via `--mode defer|yolo|off`). CLI `okami heartbeat` / `okami paperclip`.
- [ ] Adapter **Slack** (Events+Web) — adiado (menos urgente agora).
**Saída:** Okami "contratado" no Paperclip com governança ✅. Slack depois.

## Fase 12 — Painel + hardening
- [ ] `apps/web` (React+ShadCN): status, sessões, custos, skills, persona, taste, aprovações.
- [ ] Sandbox Docker default; secret store; self-check visual ligado.

---

## Sequência
**0 → 1 → 1.5 → 2 → 3 (Telegram)** primeiro. Depois **4 (+4.5) → 5 (auto-melhoria) → 6 (persona)
→ 7 (taste)** — o "ficar melhor com o tempo". Então **8 → 9 → 10 → 11** e **12** como
endurecimento. Coração do Okami: **1, 1.5, 2, 5, 6, 7**.
