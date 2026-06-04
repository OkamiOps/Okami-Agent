# Pesquisa profunda: Hermes-agent + OpenClaw vs Okami

> Estudo de fonte (não "por cima") dos repos **NousResearch/hermes-agent** e **openclaw/openclaw**,
> clonados e lidos arquivo:linha por 6 agentes (terminal/TUI · slash commands · Telegram × 2 repos).
> Objetivo: tornar o terminal **profissional** (não "garagem") e fechar o gap de **comandos `/`** e Telegram.
> Datado 2026-06-05. Refs ficam em `/tmp/okami-refs/{hermes-agent,openclaw}` (clones rasos).

## TL;DR — as 3 jogadas estruturais (onde os DOIS repos concordam)

1. **O terminal deles é TUI de tela cheia (árvore de componentes), não um REPL de linha.**
   Hermes = fork do **Ink/React** (`ui-tui/packages/hermes-ink`). OpenClaw = framework próprio **pi-tui**.
   Regiões persistentes (header · log · status · footer · editor): a **entrada é estruturalmente separada
   da saída** → a linha que você digita **nunca** é corrompida por output ao vivo. É a alavanca #1 do
   "feeling profissional". Nós somos REPL de linha (prompt_toolkit) — bom, mas é o teto da "garagem".

2. **Slash commands deles saem de UM registro declarativo** (Hermes `CommandDef`, OpenClaw `defineChatCommand`).
   Desse registro derivam: help, autocomplete, menus nativos (Telegram/Discord), dispatch, "did you mean".
   Têm `scope: text|native|both`, `tier: essential|standard|power` (disclosure progressivo p/ ~50 comandos),
   `category`, aliases, prefix-match, arg-menus. Hermes ~**70** comandos, OpenClaw ~**50**. Nós temos **~15**
   tratados num `if/elif` na mão. **Adotar o registro é o que destrava "muitos comandos" sem virar espaguete.**

3. **Telegram deles é um produto, o nosso é um eco-bot.** Botões inline (aprovação tap-to-approve),
   streaming por edição de mensagem, typing indicator, reactions como progresso, split de mensagem >4096,
   threads/tópicos como sessão, retry/backoff/rate-limit, dedup/idempotência, coalescing de entrada,
   webhooks + resiliência de rede. Nós: `/yes`/`/no` em texto, sem botão, sem streaming, **mensagem >4096
   quebra**, sem retry/dedup.

---

## 1) TERMINAL / TUI

### Comparação
| Capacidade | Hermes (Ink) | OpenClaw (pi-tui) | Okami (Rich+prompt_toolkit) |
|---|---|---|---|
| Tela cheia (alt-screen, regiões fixas) | ✅ `appLayout.tsx:401` | ✅ `tui.ts:735-754` | ❌ REPL de linha |
| Entrada não-corrompível por output | ✅ render tree | ✅ render tree | ⚠️ via `patch_stdout` (bom, mas frágil) |
| Streaming de tokens (in-place) | ✅ `streamingMarkdown.tsx` | ✅ `tui-stream-assembler.ts` | ❌ só no fim do turno |
| Syntax highlight em código | ✅ 8 langs `syntax.ts` | ✅ `theme.ts`/markdown | ❌ (só no `okami config`) |
| Diff colorido (intra-linha) | ✅ `markdown.tsx:774` | ✅ `diff.ts:89-163` | ❌ |
| Tool-calls como cards (cor/estado/tempo/tokens) | ✅ `thinking.tsx` (+árvore de subagente) | ✅ `tool-execution.ts` | ⚠️ 1 linha `tui.event_line` |
| Spinner animado + verbo + relógio | ✅ `FaceTicker` | ✅ `tui-waiting.ts` (shimmer) | ❌ status estático |
| Status bar com disclosure por largura + gauge de ctx | ✅ `appChrome.tsx:235` | ✅ `tui.ts:1177` | ⚠️ toolbar simples |
| Temas + detecção claro/escuro (WCAG) | ✅ `theme.ts:415` | ✅ `theme.ts:15-126` | ❌ |
| OSC 8 links clicáveis / OSC 9;4 progresso na taskbar | ✅ | ✅ `osc-progress.ts` | ❌ |
| Notificação nativa do OS / bell | ✅ `useTerminalNotification.ts` | ⚠️ progresso | ❌ |
| Mouse (scroll/seleção/scrollbar) | ✅ SGR completo | ⚠️ parcial | ❌ |
| Editor multi-linha + undo/redo + emacs | ✅ `textInput.tsx` (1340l) | ✅ `Editor`/Alt-Enter | ❌ single-line |
| Command palette (model/agent/session picker, fuzzy) | ✅ overlays | ✅ Ctrl-L/G/P | ❌ só WordCompleter |
| Ctrl-C contextual (limpa→avisa→2x sai) · Ctrl-D só vazio | ✅ | ✅ `tui.ts:462` | ⚠️ Ctrl-C cancela; idle = dica |
| Fila digitar-enquanto-ocupado | ✅ | ✅ | ✅ (já temos, FIFO) |

### Backlog priorizado (na nossa stack Python/Rich/prompt_toolkit)
**P0 — alto impacto, baixo risco, sem rewrite (fica no REPL atual):**
- **Spinner animado + relógio de tempo decorrido** no bottom-toolbar (hoje é estático "⏳ trabalhando").
  `prompt(refresh_interval=0.5)` já re-renderiza → só faltam frames + timestamp. *(S)*
- **Tool-calls estruturados/coloridos com estado + emoji + tempo** (upgrade do `tui.event_line`): título
  `emoji label (running)`, ✓ verde / ✗ vermelho no fim, preview de 12 linhas com `…`. *(S–M)*
- **OSC 8 links clicáveis** nas respostas (Rich faz nativo `[link=url]`). *(S)*
- **Ctrl-C contextual** (input cheio → limpa + "aperte de novo p/ sair"; 2x em 1s → sai). *(S)*
- **Gauge de contexto colorido** (verde→amarelo→laranja→vermelho por %) + disclosure por largura no toolbar. *(S)*
- **Syntax highlight de blocos ```` ``` ```` nas respostas** com `rich.syntax.Syntax`. *(S)*
- **Diff colorido** p/ resultado de edição de arquivo (`difflib` + realce intra-linha no caso 1-linha). *(M)*

**P1 — polimento, esforço médio:**
- **Editor multi-linha** (Alt-Enter = newline, Enter = envia) — prompt_toolkit suporta direto. *(M)*
- **Palette fuzzy** p/ comando/model/persona (`FuzzyCompleter` + `radiolist_dialog`). *(S–M)*
- **Temas + detecção claro/escuro** (`COLORFGBG`/`OKAMI_THEME` → Rich `Theme`). *(M)*
- **Notificação do OS / bell + OSC 9;4** quando o turno acaba/pede aprovação sem foco. *(S)*
- **Dedupe de avisos repetidos** no scrollback (`… x3`). *(S)*

**P2 — aposta estratégica (a que mata a "garagem" de vez):**
- **TUI de tela cheia em [Textual]** (análogo Python do Ink/pi-tui): regiões fixas header/log/status/footer/editor,
  scroll/mouse/resize, status fixo, OSC. É reescrita do **front-end do chat** (não do core do agente);
  manter `_run_repl_simple` como fallback sem-TTY. *(L)* — gate atrás de `okami chat --tui`.
- **Streaming de tokens** (depende do harness emitir deltas; render com `rich.live.Live`). *(M–L)*

> Recomendação: P0 entrega ~80% do salto de qualidade **sem** rewrite. Textual (P2) é a decisão grande.

---

## 2) SLASH COMMANDS

### O que falta (união Hermes ∪ OpenClaw, sem equivalente no Okami)
Okami hoje: `/help /new /status /stop /yolo /normal /feedback /persona /think /undo /retry /like /dislike /different /exit`.
(Nosso diferencial que eles NÃO têm: `/like /dislike /different /feedback /persona /yolo` — taste/persona.)

**P0 — primitivos que o usuário usa todo dia:**
- **`/model [id]` + `/models`** — ver/trocar modelo na sessão (autocomplete de aliases + LMStudio). *O comando de poder #1.*
- **`/compact [instruções]`** — compacta contexto em vez de perder (já temos `store.compact`/`_maybe_compact`).
- **`/usage [tokens|cost]`** — tokens + custo da sessão (JÁ temos `usage.py`/accounting — só expor).
- **`/tools`** — lista as ferramentas do agente ("o que você sabe fazer?").
- **`/commands`** — lista completa, agrupada por categoria, paginada (hoje só `/help`).
- **`/config [get|set]`** — ver/mudar config no chat (temos CLI; falta no chat). *set = owner-gated.*
- **`/reasoning [nível|show|hide]`** — controle de esforço + visibilidade (temos `/think`, falta show/hide).
- **`/sessions` + `/resume [nome]`** — listar e retomar sessões anteriores (temos transcript store/arquivo).

**P1 — diferenciadores:**
- **`/queue <prompt>`** e **`/steer <prompt>`** — enfileirar / injetar no meio do turno sem interromper.
- **`/background` (`/bg`) `<prompt>`** + **`/agents` (`/tasks`)** — rodar em sessão de fundo e listar tarefas.
- **`/goal` + `/subgoal`** — meta permanente que o agente persegue entre turnos (feature-bandeira de "agente").
- **`/skill <nome> [input]`** + **`/reload-skills`** — invocar/inspecionar skill do chat (temos skills, falta no chat).
- **`/branch` (`/fork`)** · **`/title`** · **`/rollback`** — branch de sessão, nomear, restaurar checkpoint.
- **`/btw` (`/side`) `<pergunta>`** — pergunta lateral que NÃO polui o contexto futuro (truque ótimo de UX).
- **`/export` (HTML) / `/trajectory` (JSONL)** — exportar a conversa (forte p/ um "confidente").
- **`/voice [on|off|tts]`** — toggle de voz/TTS (combina com a nossa pegada de voz humana).
- **`/cron`** (chat) · **`/reload-mcp`** · **`/update`** · **`/debug`** — ops do chat (temos `cron` CLI).

**P2 — poder/admin:** `/bash` (host-gated) · `/mcp` · `/plugins` · `/whoami` + allowlist/owner gates ·
`/snapshot` · `/handoff <plataforma>` · `/personality` (picker) · `/copy` `/paste` `/image` · `/fortune`.

### Arquitetura a copiar (independe dos comandos)
Trocar o `if/elif` por um **registro declarativo** `CommandDef`/`defineChatCommand`:
- 1 definição → help + autocomplete + menu nativo + dispatch + "did you mean" (prefix-match).
- `scope: text|native|both` (1 def serve chat-texto e menu nativo do Telegram/Discord).
- `tier: essential|standard|power` (disclosure progressivo) · `category` (gera `/commands` sozinho).
- `aliases` · `args` com `choices` (context-aware) · `argsMenu:auto` (pick-list interativa).
- **Gates** owner/allowlist/feature-flag + **confirmação por token** (`/x confirm <token>`) p/ destrutivos.
Refs: Hermes `hermes_cli/commands.py:45-224` + `cli.py:8719` (dispatch+prefix). OpenClaw
`src/auto-reply/commands-registry.shared.ts` + `reply/commands-core.ts` + `command-status-builders.ts`.

---

## 3) TELEGRAM / CHANNELS

### Comparação
| Capacidade | Hermes | OpenClaw | Okami |
|---|---|---|---|
| Aprovação por botão inline (once/session/always/deny) + auth por clicador | ✅ `telegram.py:2649` | ✅ `approval-native.ts` | ❌ só `/yes`/`/no` texto |
| Callback queries / menus / paginação | ✅ model picker | ✅ multi-select | ❌ |
| Streaming por edição de mensagem (draft) | ✅ `stream_consumer.py` | ✅ `draft-stream.ts` | ❌ |
| Typing indicator (keepalive) | ✅ | ✅ `typing.ts` | ❌ |
| Reactions como progresso (👀→✅) | ✅ | ✅ `status-reactions.ts` | ❌ |
| Split de mensagem >4096 (tag-aware) | ✅ `truncate_message` | ✅ `format.ts:644` | ❌ **>4096 quebra** |
| Threads/tópicos/forum como sessão | ✅ | ✅ `channel.ts:573` | ❌ |
| Retry/backoff/rate-limit (429 retry_after) | ✅ | ✅ `network-errors.ts` | ❌ |
| Dedup/idempotência (update_id/message_id) | ✅ | ✅ claim/commit | ❌ |
| Coalescing de entrada (álbum/burst/paste partido) | ✅ | ✅ 3 sistemas | ❌ |
| Webhooks + resiliência (conflito getUpdates, fallback IP/DoH) | ✅ `telegram_network.py` | ✅ `polling-session.ts` | ❌ polling cru |
| Registry de plataformas plugável (~25 plataformas) | ✅ | ✅ | ❌ 3 canais hardcoded |
| Mídia rica (voz/doc/vídeo/álbum/sticker-in c/ vision) | ✅ | ✅ | ⚠️ foto-in / TTS-out |
| Grupo: mention-gating + observe-unmentioned | ✅ | ✅ `mention-gating.ts` | ⚠️ básico |

### Backlog priorizado (no nosso `Channel`/`AgentEndpoint`)
**P0 — correção/robustez (coisa que hoje QUEBRA):**
- **Split de mensagem >4096** (UTF-16, em fronteira segura). Hoje resposta longa falha silenciosa. *(S/M)*
- **Retry/backoff + 429 `retry_after`** + classificação pré-conexão (não duplica send). *(M)*
- **Dedup/idempotência** por `(chat_id, message_id)` (claim no recebimento, commit no dispatch). *(M)*
- **Typing indicator** com keepalive + TTL (ganho enorme de latência percebida; combina com a voz). *(S)*

**P1 — salto de UX:**
- **Aprovação por botão inline** (substitui `/yes`/`/no`) + auth por clicador (gate de allowlist). *(M)*
- **Streaming por edição** (envia 1 msg, edita com throttle; rola nova msg no overflow). *(M/L)*
- **Reactions** in/out (👀 no recebimento, ✅ no fim) como sinal de baixo ruído. *(S/M)*
- **Coalescing de entrada** (álbum + burst + paste partido → 1 turno). *(M)*
- **Mídia rica out** (doc/vídeo/voz nativa, caption split). *(M)*

**P2 — escala:** webhooks (secret obrigatório, fail-closed) · resiliência de polling (watchdog, conflito 409,
fallback IP/DoH) · threads/DM-topics como sessão · registry de plataformas plugável.

> Atenção (hard constraint): ao ligar botões/callbacks, **todo `callback_query` tem que passar pelo
> allowlist do dono** (senão qualquer um no grupo aprova ação perigosa). Ref OpenClaw `bot-handlers.runtime.ts:2111`.

---

## Sequência recomendada
1. **Terminal P0** (spinner/elapsed · tool-cards · Ctrl-C contextual · gauge · OSC8 · syntax) — mata "garagem", sem rewrite, testável.
2. **Registro de comandos + os `/` P0** (`/model /usage /tools /commands /compact /config /reasoning /sessions`).
3. **Telegram P0** (split · retry · dedup · typing) — conserta o que quebra.
4. **Decisões grandes** (te peço o call): TUI de tela cheia em **Textual** (P2) · botões+streaming no Telegram (P1) · refactor do registro agora vs. depois.
