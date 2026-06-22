# Changelog

Todas as mudanças notáveis do **Okami Agent**. Formato baseado em
[Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versionamento
[SemVer](https://semver.org/lang/pt-BR/) (pré-1.0 = a superfície ainda pode mudar entre alphas).

## [Não lançado]

### 🎙️ voz EMBUTIDA + recursos NATIVOS (skills e plugins que viajam no pacote)
- **STT (Whisper) ligado por padrão + auto-install**: o dono mandou áudio e o agente não entendeu —
  o stack de voz existia, mas STT era opt-in (nota de voz descartada em silêncio) e `import faster_whisper`
  cru (falhava sem o extra). Agora STT é default ON (só `voice.stt.enabled: false` desliga) e
  faster-whisper/edge-tts AUTO-INSTALAM na 1ª vez via lazy_deps. UX: aviso "🎤 transcrevendo…" na 1ª
  (download do modelo) e aviso claro se a transcrição estiver desligada (sem engolir o áudio).
- **Plugins NATIVOS**: os 3 built-in (security-guidance, disk-cleanup, usage-observer) foram p/
  `okami/builtin/plugins/` → viajam no `pip install` e carregam em QUALQUER CWD (antes só em ./plugins).
- **Skills NATIVAS**: novo conjunto embarcado em `okami/builtin/skills/` (criar-pull-request,
  depuracao-sistematica, pesquisa-web), mergeado no catálogo (a skill do usuário vence por nome).
- O agente segue podendo CRIAR plugins/skills próprios — os nativos só dão um piso útil de fábrica.

### 🐛 caça adversarial de dead-code + bugs (workflow 42 subagentes, 3 céticos/achado) — 5 reais corrigidos
Varredura por 9 áreas + verificação por 3 céticos (grep repo-wide p/ não marcar dead-code despachado por
registry/getattr). 7 confirmados, 4 rejeitados, 0 gap real do Hermes (já ~98% paridade + harness à frente).
- **inbound de webhook estava MORTO em produção** (`gateway/builders.py`): o `parser` de plataforma
  (dingtalk/wecom/weixin/qqbot/whatsapp/sms) nunca era ligado no `WebhookRoute` → todo callback caía na
  síntese de prompt GENÉRICA em vez de entregar o TEXTO real da mensagem ao agente. Agora `parser=webhook_parser(provider)`.
- **critérios de saída ilegíveis no prompt** (`harness/prompt.py`): o dict cru ia pro modelo
  (`{'type': 'file_exists', 'path': 'hello.txt'}`) em vez de "o arquivo 'hello.txt' deve existir". Novo `_format_criterion`.
- **`record_feedback` crashava** se `promote_to_persona` falhasse (`learning/taste.py`) — link taste→VOICE
  é opcional, agora não derruba o registro do feedback.
- **curador aceitava auto-absorção** (`learning/curator.py`): umbrella no próprio `absorb` passava silencioso
  → `validate_plan` agora rejeita com erro claro.
- **no-op morto** `ok = ok or False` no `ProcessManager.kill` (`core/processes.py`) → `pass` + comentário.
- Considerados e descartados (não quebrados): falta de log no `distill_skill_llm`, variantes de "nada a salvar".
  +4 testes (1 por bug funcional; o no-op é refactor sem mudança de comportamento).

## [Unreleased]

### 🧱 subagente #8: sobrevive ao restart (reconcile) — paridade com o BackgroundRegistry
Os 2 subsistemas de background (BackgroundRegistry do `/background` p/ humano · spawn_jobs p/ o agente)
seguem SEPARADOS DE PROPÓSITO (consumidores diferentes), mas faltava ao spawn a durabilidade do outro:
o background spawn é thread daemon (morre com o processo), e um job 'running' ficava órfão pra sempre
após reinício do gateway. `reconcile_spawn_jobs` (chamado no boot, ANTES de qualquer spawn novo) marca os
'running' remanescentes como 'interrupted' — todos são de um processo morto. + prune no boot.
NÃO fiz o merge físico no BackgroundRegistry: ele trunca o result em 500 chars (quebraria o readback do
resultado longo pelo agente, que é o ponto do subagente) e usa id int (o contrato da tool spawn_jobs é
8-hex). Honesto: a paridade que importa (survives-restart) sem o merge lossy. +3 testes.

### 🧱 subagente: o agente PAI lê o resultado de volta + cap + GC (revisão vs Hermes)
Revisão do subagente contra a delegação do Hermes (workflow). Gap central confirmado: o background spawn
era fire-and-forget pro DONO — o agente pai não conseguia USAR o resultado (não dava pra encadear). O
Hermes resolve com fila global + turno forjado (que ele mesmo desliga em sessão stateless); aqui o
caminho soberano é mais simples: leitura sob demanda + await curto. Adições:
- **tool `spawn_jobs`** (`action=list|status|result|await`): o agente pai LÊ o resultado de um background
  spawn (turno seguinte) ou ESPERA no mesmo turno (`await`, cap 300s) — fecha o loop de volta ao modelo.
  Header autocontido (objetivo+estado) p/ o pai relembrar por que o subagente existia (ideia do Hermes).
- **estado `running`→`done`/`failed`** no registro (`.okami/spawn/<id>.json`): some a ambiguidade
  "arquivo ausente = nunca começou OU rodando".
- **cap de concorrência** (Semaphore, default 3 via `OKAMI_MAX_BACKGROUND`): bug real — antes cada
  background criava thread daemon SEM limite (satura GPU local). Fila cheia → **fallback SÍNCRONO inline**
  (não perde, igual ao Hermes).
- **GC** (`prune_spawn_jobs`, keep=50 + TTL 7d): `.okami/spawn` não vaza mais disco; prune oportunista a
  cada novo background. +18 testes. Sync inline segue o DEFAULT (zero regressão).

### 🧱 harness #9: subagente em SEGUNDO PLANO (não trava mais o chat)
O `spawn` era 100% BLOQUEANTE: uma tarefa longa (ou fan-out de 6 subagentes) congelava o turno do pai por
5-25 min, o canal só mostrava "⏳ ~N min". Agora `spawn` aceita `background=true`: roda o subagente numa
thread daemon e **retorna na hora** ("▶ rodando em segundo plano, te aviso"); ao terminar, persiste o
resultado em `.okami/spawn/<id>.json` e **avisa o dono no chat que pediu** (captura o `ctx.notify` daquele
turno → vai pro chat certo mesmo após o turno acabar, sem o problema do `_last_chat` global). O modo
síncrono segue sendo o DEFAULT (zero regressão). Núcleo em `okami/core/spawn_jobs.py` (testável sem
thread). +6 testes. (Próximo: progresso "passo N/M" durante o background — item 6.)

### 🧱 harness review (Okami vs Hermes) — adoções e correções
Revisão completa do harness contra o source REAL do Hermes (workflow 8 agentes). Veredito honesto: nosso
loop está À FRENTE do Hermes nos backstops de modelo fraco (anti-bail/anti-thin/anti-empty, anti-loop
ABAB, circuit-breaker por tool, paralelo com path-collision, salvage anti-alucinação) — nada disso existe
no loop do Hermes. Gaps reais são poucos; começando a fechá-los:
- **Sanitização de surrogates/control chars antes do modelo** (`okami/llm/sanitize.py`, port do
  message_sanitization do Hermes): modelo LOCAL (GLM/Qwen) emite surrogate solitário (U+D800–DFFF) que
  estoura o `.encode('utf-8')` do SDK ANTES da request → derrubava o turno com UnicodeEncodeError. Já
  tínhamos sanitização PARCIAL (só str, só surrogate, só no complete); agora cobre **lista-de-blocos
  (multimodal) + control chars** E o **caminho de streaming** (que NÃO sanitizava — crítico agora que o
  streaming é default p/ local). Fail-open. +9 testes.

### 🌐 WebFetch melhor: navegador real + auto-fallback p/ Playwright
- **User-Agent de navegador real** (`BROWSER_HEADERS` em `okami/core/net_guard.py`): `web._fetch_full` +
  `browser.fetch` mandavam `okami/1.0` (robô óbvio → 403 na cara). Resolve a classe "403 só por causa do UA".
- **`smart_fetch` (auto-fallback p/ browser real)**: o fetch estático não renderiza JS nem passa bloqueio
  brando. Agora tenta estático e, se vier 403/casca-de-JS/Cloudflare/corpo minúsculo, re-tenta no
  **Playwright** (browser de verdade, contexto persistente p/ login) que renderiza JS e passa muitos
  bloqueios. Bloqueio SSRF não re-tenta; sem Playwright → devolve o estático. `web_extract` usa isto.
  Ainda NÃO vence captcha (decisão do dono: handoff p/ browser real, na fila). +10 testes.

### 💬 fix: formatação do Telegram (tags HTML cruas viravam texto literal)
Bug real (caso FIPE): a dica de plataforma MANDAVA o modelo escrever HTML (`<b>negrito</b>`), mas o
conversor `to_html` tratava a entrada como MARKDOWN e dava `html.escape` em tudo → `<b>` virava
`&lt;b&gt;` e o Telegram mostrava a TAG literal pro usuário ("várias tags abertas"). 3 correções:
- **dica de plataforma agora pede MARKDOWN** (`**negrito**`, `` `código` ``) — consistente com o conversor.
- **`to_html` tolera HTML cru do modelo** (`_html_to_md`): normaliza `<b>/<i>/<code>/<a>/<pre>/<blockquote>/
  <s>/<tg-spoiler>` p/ markdown antes do pipeline; tag não-suportada (div/span/li/h1…) perde só a tag. `<`
  solto de prosa ("2 < 3") segue escapado.
- **fallback agora é TEXTO-PURO LIMPO** (`to_plain`): se a API recusa o parse, manda "negrito" — não
  "**negrito**" nem `<b>` cru. Vale p/ `send_message` E `edit_message` (streaming-by-edit). +9 testes.

### ⚡ harness mais rápido (diagnóstico de 7 analistas → plano por impacto)
O agente demorava demais p/ a 1ª resposta (>5min, às vezes >25min) em modelo local lento. Causas-raiz
mapeadas: streaming desligado, prompt gigante tier-blind (~57 schemas de tool ≈ 20K chars no prefill de
todo turno), cascata de timeout/retry/failover (≈30min no pior caso), chat serializado por tarefa
síncrona, e re-geração por falso-positivo do Action-or-Terminate. **Leva 1 (a maior por menor esforço):**
- **streaming token-a-token LIGADO por default p/ tier local/weak** (`okami/llm/streaming.py`): a máquina
  de streaming já existia atrás de flag OFF — o usuário via "💭 thinking…" congelado por todo o
  prefill+geração (dezenas de s a min). Agora o default é tier-aware: liga sozinho p/ modelo de
  protocolo-texto (json_constrained — local/weak), fica OFF p/ strong com tool_calls nativos; config
  explícito (`harness.streaming`) sempre vence. A 1ª resposta começa a aparecer em ~segundos.

### 🛠️ fix: robustez + `send_message` (caça field-fail, leva 2)
- **MCP stdio anti-zumbi**: `_request` agora MATA o subprocesso no timeout/EOF (antes a thread de leitura
  ficava bloqueada em stdout p/ sempre e o proc virava zumbi).
- **browse sem Playwright**: action≠read (screenshot/click/…) falha CLARO ("instale Playwright") em vez de
  degradar SILENCIOSO p/ fetch (o agente pedia screenshot e recebia texto achando que deu certo).
- **tool `send_message`**: entrega direta de texto por um canal SEM rodar o LLM (avisos/relatórios);
  usa o token do PRÓPRIO agente (channels.telegram), target=chat_id ou vazio→dono; `danger=sensitive`
  (go/no-go). Fecha a lacuna "o agente não tinha como mandar msg a um target sem improvisar shell".

### 🛠️ fix: check() nas tools de integração (não falham mais feio em runtime)
Caça adversarial da CLASSE "onde o agente falha em campo" (workflow de 116 subagentes, 5 dimensões, 3
céticos/achado). 1ª leva corrigida: `generate_video`, `homeassistant`, `feishu_doc_read` e `x_search`
**não tinham `check()`** → ficavam VISÍVEIS pro agente mesmo sem a integração configurada; ele chamava e
levava um `RuntimeError` feio em runtime. Agora cada uma tem `check()` (via `*_config(load_config())`) →
quando a integração falta, a tool **some do registro** com motivo claro (`🔌 indisponível: configure
integrations.X`), igual a computer_use/web_search. `vision_analyze`/`web_extract` foram DESCARTADAS da
correção: caem no modelo principal via `aux_complete`, então funcionam sem config — podá-las removeria
tool que funciona. +6 testes. 2645 passed.

### 🛠️ fix: tool `install_skill` (o agente instalava skill SEM improvisar Docker)
Bug de campo: pedido para instalar a skill `html-to-pdf` (`aviz85/claude-skills-library`), o agente
**não tinha tool de instalação** (`use_skill` só carrega, `manage_skill` só AUTORA; instalar era `okami
learn`, CLI-only) → improvisou `npx skills add` (CLI de terceiro que pede Docker), travou pedindo p/
abrir o Docker e rodou ~160 min até um timeout transitório de modelo+fallback. Correção: nova tool
**`install_skill`** (`okami/skills/install.py` headless + `agentic.py`) que reusa a pipeline segura do
`okami learn` — **git clone (NUNCA Docker nem `npx skills add`)** p/ github/local → quarentena → scan de
segurança → matriz confiança×verdict → instala + lockfile; `name=` instala uma skill de repo-biblioteca;
HIGH+ bloqueia; clawhub/npx só com `allow_exec=true`; `danger=dangerous` (go/no-go). +9 testes.

Rodada **#20** — fechados os 3 itens que o dono pediu para "finalizar a implantação": **computer-use
EMBUTIDO**, **inbound dos 9 canais novos** e os **plugins built-in do Hermes**. Caça adversarial (workflow
de 60 subagentes, 3 céticos por achado) → **10 bugs reais corrigidos**. **2.630 testes passando** · gates
limpos.

### 🖥️ Computer-use EMBUTIDO (opt-in, approval-gated)
- Nova tool `computer_use` (`okami/core/tools/computer_use.py`) — screenshot/click/right_click/double_click/
  move/type/key/scroll — com **3 camadas de segurança**: (1) DESLIGADA por padrão (`computer_use.enabled`)
  + backend presente; (2) **hardline-block** recusa combos destrutivos (cmd+q/logout/lixeira) ANTES de tocar
  no SO; (3) `danger="dangerous"` → cada ação passa por go/no-go. Backend `okami/core/computeruse/`
  (macOS screencapture+cliclick; pyautogui via lazy_deps). Revisão da decisão só-MCP do #17 — agora EMBUTIDO.

### 📥 Inbound dos 9 canais (poll + webhook)
- **Pollable** (`okami/channels/messaging.py`): Signal (`/v1/receive`), Matrix (`/sync` com since-token +
  baseline no `start()`), BlueBubbles/iMessage (dedup por guid, **baseline tardio anti-flood**).
- **Webhook-push** (`okami/channels/inbound_parsers.py` + `WebhookRoute.parser`): DingTalk, WeCom, QQBot,
  WhatsApp, SMS, Weixin — entrega o TEXTO real ao agente (não o prompt sintetizado). XML por regex leaf-only
  com `html.unescape` (anti-XXE, sem ElementTree). Os 14 canais agora são **bidirecionais**.

### 🔌 Plugins built-in do Hermes (portados como plugins reais)
- **`security-guidance`** — hook `before_tool` que varre o código a ser escrito por ~28 padrões inseguros
  (eval/exec, pickle, yaml.load, shell injection, SQL por f-string, XSS, cripto fraca, segredo hardcoded,
  JWT alg=none…). WARN por padrão; `OKAMI_SECURITY_GUIDANCE_BLOCK=1` → VETA.
- **`disk-cleanup`** — hooks `before_tool`+`after_task`: rastreia efêmeros (`.tmp`/`.bak`/dirs scratch) e os
  apaga no fim; conservador (nunca symlink/dir, só do projeto atual).
- Os demais built-in já são nativos (image_gen/kanban/observability) ou ficam na superfície MCP
  (google_meet/teams/spotify) — mapa completo em `plugins/README.md`.

### 🐛 Caça adversarial (10 reais, ≥2/3 céticos)
- **Colisão de nome**: o pacote novo sombreava `okami/core/desktop.py` (notificações) → renomeado
  `computeruse/`. **XML**: entidades não eram decodificadas (`&lt;`→`<`). **DingTalk**: `text` não-dict
  crashava. **Webhook**: `route.chat_id` mutado/compartilhado → corrida de roteamento (agora cópia por
  POST). **BlueBubbles**: LRU por `set` perdia os mais recentes (→ dict ordenado) + flood do backlog se o
  prime falhasse (→ baseline tardio). **disk-cleanup**: `patch` não-string. **security-guidance**: janela de
  contexto do placeholder.

Rodada **#19** — **paridade ~98%** com o Hermes (por presença de capacidade): fechada a cauda-longa que
restava (integrações de nicho + breadth de canais). Subagente adversarial → 1 path-injection + 1 perf
corrigidos. **2.578 testes passando** · gates limpos.
([COMPETITIVE_RESEARCH_19.md](docs/COMPETITIVE_RESEARCH_19.md).)

### 🔌 Integrações de nicho
- **`x_search`** (Grok/xAI no X/Twitter), **`homeassistant`** (IoT: list/state/call; domínios perigosos
  bloqueados), **`feishu_doc_read`** (docs Feishu/Lark) — todas config-driven (`integrations.*`),
  graceful sem credencial, saída externa embrulhada como não-confiável.

### 📡 Canais: de 5 → **14 plataformas**
- Novos (outbound): **DingTalk, WeCom (WeChat Work), QQBot** (`okami/channels/regional.py`) + **WhatsApp,
  Signal, Matrix, SMS, BlueBubbles, Weixin** (`okami/channels/messaging.py`) — registrados no ChannelSpec +
  tool-policy por superfície, deny-by-default.

### 🎬 Vídeo + 🔁 LSP + 🤖 Copilot
- vídeo: **registry de backends nomeados** (veo3/kling/pixverse) + `okami video --list`.
- LSP: **auto-install** (`okami lsp install` via lazy_deps `lsp.pyright`) + **diagnostics multi-linguagem
  wired no write** (gopls/ts/rust/bash/clangd via o cliente persistente).
- **Copilot como backend**: transporte `copilot_cli` (GitHub Copilot via o CLI `copilot`).

## Rodada #18

Endereçados os **3 gaps reais** que o comparativo #17 deixou. Subagente adversarial varreu
o código novo → **1 SSRF real corrigido**. **2.539 testes passando** · gates limpos.
([COMPETITIVE_RESEARCH_18.md](docs/COMPETITIVE_RESEARCH_18.md): paridade honesta ~88–91%.)

### 🔁 Cliente LSP persistente (reuso entre edições)
- `okami/lsp/client.py` (`PersistentLspClient`) mantém o language server VIVO (initialize 1x, didOpen no
  1º arquivo, didChange nos seguintes) — fecha o cold-start (~8s/edição do pyright) — + `okami/lsp/pool.py`
  (`LspPool`: 1 server por (binário, raiz), gateado em git) + **`okami lsp probe <file>`**. Thinner que o
  Hermes (síncrono, ainda não é o default do write) — documentado honestamente.

### 🎬 Geração de vídeo
- `okami/llm/videogen.py` + tool `generate_video` + **`okami video`**: provider-driven (`media.video`),
  text→video e image→video, síncrono + poll assíncrono. A URL de download (do PROVIDER, não-confiável)
  passa pelo **net_guard anti-SSRF** (recusa `file://`/IP interno) antes de baixar; teto de 25MB na imagem.

### 🖱 Computer-use — decisão de escopo soberana
- [docs/COMPUTER_USE.md](docs/COMPUTER_USE.md): o núcleo NÃO embute um automador de desktop (conflita com
  fail-closed); a capacidade é alcançável via **servidor MCP de computer-use trust-gated** (go/no-go por ação).

## Rodada #17

Fechados os **3 gaps reais** que o comparativo #16 achou no Hermes — Mixture-of-Agents,
Google Code Assist (tier grátis de Gemini) e o subsistema LSP. 2 subagentes adversariais varreram o código
novo → **4+ defeitos corrigidos** com TDD (incl. injeção de prompt via referência da MoA e o OAuth do
Code Assist que não completava). **2.525 testes passando** · ruff/bandit-HIGH/secret-scan limpos.

### 🧠 Mixture-of-Agents (amplificação de raciocínio)
- `okami/llm/mixture.py` + tool `mixture_of_agents` + **`okami moa <prompt>`**: roteia um problema DIFÍCIL
  pelos providers JÁ configurados em paralelo (assinatura-only, sem OpenRouter) e sintetiza a melhor
  resposta com o mais forte. Tolera falha de referências (min 1); as respostas de referência entram no
  system do aggregator **embrulhadas como dado não-confiável** (provider comprometido não injeta instrução);
  reporta `total_calls` (transparência do custo N+1).

### 🆓 Google Code Assist (tier grátis de Gemini)
- `okami/llm/code_assist.py` + transporte `gemini_cloudcode` + **`okami gemini login|status|quota`**: acesso
  ao tier GRÁTIS de Gemini via cloudcode-pa (conta Google, sem billing) — fits a constraint assinatura-only.
  Reusa a tradução do `gemini_native`, adicionando o envelope da control-plane + OAuth PKCE (S256). O
  `login` COMPLETA o fluxo: callback local (valida state/CSRF), troca code→token, persiste em
  `~/.okami/auth/google_oauth.json` (0600); renova via refresh_token. Sem credencial → degrada com graça.

### 🔎 LSP (cliente — diagnostics semânticos no write/edit)
- `okami/lsp/*` + **`okami lsp status|list|which`**: o Okami spawna language servers externos
  (pyright/gopls/typescript-language-server/rust-analyzer/bash/clangd) e consome `publishDiagnostics` p/
  enriquecer o write/edit com erros SEMÂNTICOS — filtro delta (só os erros INTRODUZIDOS pela edição) via
  remap de linha diff-aware. Camadas puras (protocol JSON-RPC, range_shift, reporter, workspace git-gateado)
  testadas offline.

### 🖥 Comandos de terminal
- **`okami dashboard`** (alias amigável de `gui`, com `--host`/`--token` p/ self-hosting); `okami help`
  agora lista os comandos novos (moa, dashboard, sessions, cost, lsp, gemini, provider check --live).

---

## Rodada #16

Implementadas as 6 "ideias-forward" que o #15 listou honestamente como ainda-não-feitas
(acima das 13 áreas em paridade). 3 subagentes adversariais varreram o código novo → **4 defeitos reais**
corrigidos com TDD. Novo comparativo (`docs/COMPETITIVE_RESEARCH_16.md`) achou **3 gaps** — fechados no #17.

### ✨ Novas capacidades (acima da paridade)
- **Streaming token-a-token** (TUI + Telegram), atrás de `harness.streaming` (default OFF): o provider
  emite os deltas ao vivo, o harness ainda recebe o `Completion` inteiro p/ parsear a ação; stream que cai
  antes do 1º token cai no caminho robusto (retry/rotação/failover). `on_token` (display) é **best-effort**
  — erro na TUI/edição não trunca a saída nem mascara como falha de provider.
- **Janela nativa do desktop** sem Electron: `okami desktop --native` → pywebview (lazy-install
  `desktop.webview`), com fallback gracioso → chrome `--app` → browser. Seleção pura/testável
  (`_pick_window_backend`).
- **Self-hosting do dashboard**: `okami gui --host 0.0.0.0 --tls-cert <c> --tls-key <k>` — bind público
  (não-localhost) **EXIGE token** (`public_bind_needs_token` recusa antes de bindar); TLS via `SSLContext`;
  meia-config de TLS (só cert ou só key) erra em vez de servir HTTP em silêncio.
- **PluginContext trust-gated** (`okami/plugins.py`): plugin só troca de provider se for `trusted` +
  `allow_provider_override` + o provider estar na `allowed_providers`; não-confiável fica preso ao default
  (plugin de terceiro não redireciona tráfego/gasto à revelia do dono).
- **Telemetria de custo por-vendor**: `okami cost [--json]` — `summarize_by_vendor` agrega por quem
  respondeu (`served_by`); assinatura (claude/codex) = "incluído" (NUNCA inventa $), pay-per-token estima
  pelo pricing conhecido.
- **Validação ao vivo dos providers nativos**: `okami provider check --live` faz uma chamada REAL mínima ao
  vendor se há credencial, senão pula com graça; erro do vendor passa pelo `redact` antes de reportar
  (não vaza credencial).

### 🐛 Caça de bugs (#16, código novo)
- streaming `on_token` best-effort (display não corrompe a saída do modelo).
- `provider check --live` redige segredo no erro reportado.
- `summarize_by_vendor` não cria mais bucket vazio com `served_by` malformado.
- `serve_dashboard` recusa meia-config de TLS (footgun de "achar que está sob TLS").

### 🖥 Revisão TUI/terminal/CLI (3 subagentes: CLI · slash-registry · TUI/REPL)
- **gateway**: comando chat-only (`/skin /mouse /replay /copy /details /agents /exit`) digitado num
  canal remoto (Telegram/REST) **caía como mensagem pro modelo**; agora responde "só funciona no
  terminal" e não inicia turno (checa `CommandDef.scope`).
- **TUI**: `/replay` não tinha handler (ia pro agente) → `_cmd_replay` (paridade com o REPL);
  `on_input_submitted` crashava se `_cmdmenu()` era None no teardown → guard; `_tokbuf` (streaming)
  vazava token parcial entre turnos → zerado no fim do turno.
- **comando faltante**: `okami sessions [list|show|export]` — paridade scriptável com o `/sessions`
  do chat (`session_summaries` puro + sub-Typer read-only).

## [0.9.0-alpha] — 2026-06-16

Salto grande de capacidade. **~100/100 de paridade FUNCIONAL** com o estado-da-arte
(NousResearch/hermes-agent), incluindo **prontidão multi-vendor**. De ~1.7k → **2.447 testes passando**.
~47 defeitos reais caçados por subagentes adversariais e corrigidos com TDD ao longo de 9 rodadas de
pesquisa (#7–#15). O restante p/ "100 absoluto" é só validação em TRÁFEGO real dos providers nativos
(precisa das chaves) — capacidade completa e testada. 🐺

> Nota de método: cada feature abaixo nasceu da comparação arquivo:linha com o Hermes, foi implementada
> com TDD (RED→GREEN), e o código novo passou por caça de bug adversarial (subagentes paralelos que
> precisam REPRODUZIR o defeito antes de ele contar). Gates: pytest · ruff · bandit-HIGH · secret-scan ·
> `okami policy check`.

### 🌐 Multi-vendor (prontidão p/ trocar de provider)
- **Transporte nativo Gemini** (`gemini_native`): traduz mensagens OpenAI ↔ `generateContent` (system →
  systemInstruction, assistant → model), **function-calling completo** (functionDeclarations / functionCall
  / functionResponse), **imagem** (data-uri → inlineData; URL → fileData), probe de tier, erro claro quando
  falta a chave. SDK `google-genai` instalado sob demanda.
- **Transporte nativo Bedrock** (`bedrock_native`): traduz ↔ Converse API (system separado, content em
  blocos), **toolConfig/toolUse/toolResult**, **imagem** (data-uri → image-block), usa a cadeia de
  credencial AWS IAM (sem API key). SDK `boto3` sob demanda.
- **Erro nativo classificado**: `errors._status_of` lê o status escondido no `.response` do boto3
  (ClientError) → ThrottlingException/AccessDenied/ServiceUnavailable etc. roteiam a alavanca certa
  (rotaciona/back-off/failover). `okami provider check <transport>` faz **self-test de capacidade**
  (texto + tools + imagem + tool-call) sem rede/chave.
- **`lazy_deps`** (`okami deps list|install <feature>`): instala backend opcional em runtime (allowlist
  fechada, spec-safe sem URL/path/metachar, venv-scoped via uv→pip, opt-out por
  `security.allow_lazy_installs`). Resolve a fragilidade do extra `[all]` e o bloat.

### 🛡 Segurança & supply-chain
- **threat_patterns** scope-aware (all/context/strict): injeção clássica + promptware/C2 + anti-forense +
  role-hijack + **unicode invisível (Trojan Source)**; pega injeção **ofuscada por markdown** (`**all**`).
- **Scan de arquivo de contexto**: `AGENTS.md`/`CLAUDE.md`/`.cursorrules` de subpasta é escaneado ANTES de
  entrar no contexto — repo clonado hostil não sequestra o brief.
- **Supply-chain de MCP**: scanner de exfil (`shell-interpreter + egress nos args`), **OSV malware-check**
  pré-spawn de npx/uvx (bloqueia MAL-*, fail-open na rede), **OAuth 2.1 + PKCE** p/ MCP protegido
  (`okami mcp --auth`, TokenStore 0600 + refresh automático).
- **Tirith**: scan de CONTEÚDO pré-exec no `run_shell` (URL homograph, pipe-to-interpreter, terminal-
  injection) que o regex não pega. **Auto-install opt-in** com verificação **SHA-256 obrigatória**
  (basename exato), cosign opcional. Graceful sem o binário.
- **ssl_guard**: preflight de CA-bundle no boot (env vars + certifi) com erro acionável.
- `_SENSITIVE_PATH`: agora barra **`.envrc`** (direnv) também; libera `.env.example`/`.env.js` (template/
  código), mantém `.env`/`.env.local`/`.env.production` barrados.

### ⚙️ Resiliência de runtime / provider / modelo local
- **Recuperação reativa de erro** no provider: 401 → refresh de OAuth; imagem grande → shrink; `TurnRetryState`
  com guards one-shot por tentativa.
- **Reparo multi-passe de tool-call JSON** malformado (strict=False, vírgula sobrando, fecha estrutura na
  ordem certa via pilha, escapa control-char) — modelo local não derruba o turno.
- **Sanitização de schema p/ llama.cpp** (GBNF): união nullable anyOf/oneOf → tipo base, strip
  pattern/format — schema de tool MCP externa não dá 400 em modelo local.
- **stall-vs-truncation**: distingue truncação no comprimento (continua) de vazio-stall (escada).
- **edit-format steering** por família de modelo (GPT/Codex → apply_patch V4A; open-weight → edit_file).

### 📱 UX de gateway / Telegram
- **display-config em tiers** por plataforma (Telegram HIGH, Slack sem tool_progress, SMS MINIMAL).
- **Heartbeat de turno longo** ("ainda trabalhando, ~N min"), **panic-hook** (crash → log + stderr),
  **detecção de silêncio multi-marcador** (NO_REPLY/SILENT/…), **merge de álbum de fotos** (rajada vira
  1 turno), **auto-extração de imagem do texto**, `text_to_speech`, file.attach por WebSocket.

### 🤖 Automação & extensibilidade
- **Blueprints** (`okami blueprint list|show|use`): automação parametrizada com slots tipados
  (time/enum/weekdays) que vira job de cron — sem o dono digitar cron cru.
- **Kanban swarm** (`okami swarm <goal> --run`): workers paralelos → verificador → sintetizador com
  blackboard JSON; o `--run` executa de verdade via run_task; worker que explode é isolado.
- **Plugins** (`okami plugins`): descoberta por pasta (`.okami/plugins/<n>/plugin.yaml`) + entry-point pip
  (`okami.plugins`); hooks de plugin em `hooks/<event>/*` **EXECUTAM** no ciclo de vida (before_* pode vetar).
- **Browser supervisor**: listener CDP (diálogos pendentes + árvore de frames/OOPIF) + política de diálogo.
- **Dashboard web** (`okami gui` / `okami desktop`): app single-file (stdlib, **zero-dep**) com abas
  Status/Sessões/Config/Logs; clique na sessão abre o **transcript**; aba Config edita por **form**
  (allowlist de chaves não-segredo → `okami.local.yaml` via secure_write); **auth por token**
  (`--token`, Bearer/`?token=`); `--app` abre em janela app-mode do browser.

### 🧠 Skills & auto-aprimoramento
- **Bundles** (`okami skill bundle`): UM nome carrega N skills. **Config no frontmatter**
  (`metadata.okami.config`) que o sistema pergunta 1x. **Gating por plataforma/ambiente**
  (darwin↔macos normalizado). Review model-driven; recall com framing de dado-não-instrução.

### 🛠 CLI / operações
- `okami completion bash|zsh|fish`, `okami logs --level/--component/--since`, `okami doctor --fix`
  (recupera SQLite malformado via backup + dump/reload), `okami deps`, `okami blueprint`, `okami swarm`,
  `okami plugins`, `okami gui`, `okami desktop`, `okami mcp --auth`.
- Limites de tool-output config-driven (`tools.tool_output`). `env_probe` injeta dica no system prompt
  quando o ambiente Python está torto.

### Changed
- Default `Budget.max_context_chars` 24000 → 64000 (a lista de tools no system-prompt cresceu p/ ~23,5K;
  a 24000 disparava compaction espúria nos testes diretos de Harness; produção sobrescreve com o teto real).
- `usage.normalize_usage`: casos `bedrock_native`/`gemini_native` (antes os tokens vinham 0).
- `as_completion`: `tool_calls` é sempre lista (nunca None) — contrato p/ os callers.

### Fixed
~47 defeitos reais (subagentes adversariais + TDD). Destaques: **XSS** no dashboard (chat_id cru num
onclick inline; esc não escapava aspas → data-attribute + listener delegado); `_SENSITIVE_PATH` não
barrava `.envrc` (direnv); `skill_matches_platform` escondia skill macOS no Mac (sys.platform='darwin'≠
'macos'); injeção ofuscada por markdown escapava o scan; panic-hook crashava com `__str__` ruim;
transporte Gemini perdia o system prompt (kwarg errado), descartava imagem e mandava data-uri malformado
como fileData; erro do boto3 mal-classificado (status escondido no `.response`); checksum do Tirith casava
por sufixo de path; `run_swarm` propagava None; race no `sessions.json.tmp`; YAML malformado derrubava
`load_skills`; `format_tokens(1e9)` dava "1.0B".

---

## [0.1.0-alpha] — 2026-06-05

Primeiro **alpha público**. 🐺

### Highlights
- Harness confiável (action-or-terminate, anti-loop/alucinação, exit criteria verificados, failover entre
  providers, escalonamento sob falha).
- Paridade multi-modelo: Codex/Claude por **assinatura** (OAuth/CLI, nunca pay-as-you-go), LMStudio local,
  MiniMax/MiMo por Token Plan.
- Memória plugável (SQLite FTS5 + embeddings, layer **global** `~/.okami`, consolidação/TTL, citação,
  métricas), Skills + Contracts + Verification Gates (scan de segurança obrigatório).
- TUI de tela cheia: separação de turno, emoji por evento, **rodapé de custo por resposta**, copiar texto.
- Gateway multi-agente no Telegram (1 bot por agente, deny-by-default, go/no-go, voz, reactions).
- Process manager Hermes-grade (kill real, PTY/stdin, watch, paginação, recovery) via `okami ps` e `/process`.
- Postura fail-closed (assinatura-only, segredos só no `.env`, sandbox por perfil, SSRF guard, audit redigido).
- Conformance & release-readiness: `okami policy check --strict` + `okami readiness`.

### Added
- `okami readiness` — prontidão de release (CI green · strict green · strict HEAD match), staleness
  automática, `--refresh` dispara o gate, `--json`.
- Rodapé de custo por resposta no chat (`· ctx N% · X tok (in↑ out↓) · Ys`).
- Copiar texto na TUI (seleção nativa + `^C`).
- Unificação `/agents` · `/background` · `/process` (fila + tarefas + processos OS), `/process log`
  paginado, `/background --process` (promove servidor/build a processo OS, fail-closed).
- Supervisão de processos fora do gateway: `okami ps`, `okami process list|log|kill|signal|wait|clean`.
- Emoji por tipo de evento no chat (🧠 pensar · 🛠️ tool · 🔁 loop · …).

### Changed
- Heurística de exposição de rede unificada entre `lint` e `policy` (gateway só-`reactions` não expõe).
- Separação de turno no chat com régua sóbria `▌ nome · hora` (sem emoji de avatar).
- MiniMax/MiMo promovidos de "experimental" a suportados, com endpoint/auth corretos.

### Fixed
- **MiniMax**: Token Plan usa **Subscription Key** (Bearer, OpenAI-compat `api.minimax.io/v1`), não OAuth
  device-flow — corrige o 401.
- **MiMo**: endpoint regional do Token Plan (`token-plan-{ams|sgp|cn}.xiaomimimo.com/v1`) — corrige o
  erro de parse-JSON.
- `strict` passava a reprovar falsamente por causa de heurística de exposição divergente; agora conforme.
- `config check --json`, escape de `systemd` argv, `.okami` fora do CWD (skills/voice), providers
  opcionais em âmbar (sem alarme de 401).

### License
- O projeto agora é **MIT** ([LICENSE](LICENSE)) — uso/fork/comercial livre, sem garantia.

### Security
- Assinatura-only para Claude/Codex (nunca `ANTHROPIC_API_KEY` pay-as-you-go).
- Segredos só no `.env` (gitignored); `okami.yaml` versionado sem segredo literal.
- Telegram deny-by-default; aprovação fail-closed (`off` ≠ `yolo`); SOUL nunca auto-evolui.
- Sandbox por perfil (local/docker), SSRF guard em URLs controladas por modelo/usuário, audit log redigido.

[0.1.0-alpha]: https://github.com/OkamiOps/Okami-Agent/releases/tag/v0.1.0-alpha
