# Changelog

Todas as mudanças notáveis do **Okami Agent**. Formato baseado em
[Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versionamento
[SemVer](https://semver.org/lang/pt-BR/) (pré-1.0 = a superfície ainda pode mudar entre alphas).

## [Não lançado]

## [0.14.0-beta] — 2026-07-08

As releases anteriores fecharam gaps de capacidade (imagem, hooks, browser). Esta fecha uma lacuna
operacional que ficava só implícita: **instalações existentes não tinham um caminho de atualização
documentado** — o único jeito de subir de versão era rerodar o instalador do zero, sem confirmação do
que mudou. Onda focada em confiabilidade de instalação/atualização multi-plataforma, mais polimento de
config e terminal. Suíte: **3.590 → 3.613 testes**.

### 📦 Instalação & Upgrade
- **Correção crítica no `install.sh`**: em locales UTF-8 (pt_BR, en_US) o instalador abortava com
  `unbound variable` logo após clonar, deixando o binário desatualizado — uma expansão `$VAR` colada a um
  caractere não-ASCII fazia o `bash` sob `set -u` incluir os bytes do caractere no nome da variável.
  Corrigido e **validado executando o instalador de ponta a ponta** sob `pt_BR.UTF-8`.
- **`okami upgrade`** (comando novo): detecta o tipo de instalação (managed via `git`, clone de
  desenvolvimento, Docker, ou ausente) e aplica o caminho certo — `git pull --ff-only` + `uv tool install
  --force` para instalações managed, relatando a versão antiga → nova ao final. Flags `--check` (só
  reporta se há atualização disponível, sem aplicar) e `--yes` (não pergunta confirmação).
- `install.sh`/`install.ps1` passam a **verificar o binário recém-instalado** e reportar versão
  antiga → nova — antes, a instalação/atualização acontecia em silêncio, sem confirmação do resultado.
- `install.ps1` trata **long-paths do Windows** (checagem de registro + habilitação de
  `core.longpaths` no git quando necessário) — instalação em caminhos profundos deixa de falhar
  silenciosamente.

### 🐳 Docker
- `deploy/docker-compose.yml` passa a **persistir `OKAMI_HOME` em volume nomeado** (`okami-data`) —
  antes, skills, agentes, sessões, `.env`, credenciais e o cofre de segredo iam para o home efêmero do
  container e se perdiam a cada recriação.
- `deploy/Dockerfile` reconstruído **multi-stage**: `uv sync --frozen` (build reprodutível), usuário
  não-root, `HEALTHCHECK` configurado, imagens base pinadas por digest.

### ⚙️ Config
- O menu `okami config` ganha um **picker interativo de provider/modelo** (reaproveitando o mesmo fluxo
  do comando `okami model`, com os aliases `sonnet`/`opus`/`fast`/`smart`) e uma visão de **providers
  configurados** — antes o menu não tinha como trocar de provider ou modelo, só editar config manualmente.
  Persiste em `okami.local.yaml`.

### 🖥️ Terminal
- Os cartões de tool-call finalizados agora mostram o **tempo de execução** de cada chamada.
- A barra de status (tanto no REPL de linha quanto no TUI de tela cheia) mostra **tokens/custo ao vivo**
  durante a sessão, em vez de só ao final.
- A toolbar do REPL mostra a **tool em execução** no lugar de uma linha genérica de "pensando".

### 🚧 Em andamento, fora desta release
- Correções de conexão com provider seguem em andamento em paralelo: crash de streaming do Claude e
  resolução do cofre de credenciais do Codex — previstas para uma release de acompanhamento.

### 🧪 Suíte
- **3.613 testes passando** (3.590 → 3.613).

## [0.13.0-beta] — 2026-07-08

Depois da `v0.12.0-beta` fechar 3 gaps de uso real, o objetivo desta release passou de "manter paridade"
para **ultrapassar o Hermes nos pontos onde ele ainda está na frente**. Mapeamos 6 dimensões (mídia,
gateway, TUI/humanização, harness/tools, memória/skills/plugins, computer/browser), achamos pontos
concretos onde o Hermes ganha (GPT Image via assinatura, qualidade de tool-call, skills, humanização,
browser, mídia/PDF) — e também pontos onde **já estávamos na frente** (HTML→PDF sem Chromium, identidade
em 3 arquivos SOUL/VOICE/PERSONA vs blob genérico do Hermes, checkpoints, cofre de segredo cifrado). Esta
release é a **primeira onda de implementação**, 4 frentes em paralelo. Suíte: **3.572 → 3.576 testes**.

### 🎨 Geração de imagem nativa via assinatura Codex
- Diagnóstico: geração de imagem estava **quebrada** — postava pro `api.openai.com/v1/images` (REST
  pago), voltava `401` porque exige uma API key paga separada, fora do modelo de assinatura.
- `imagegen.py` reescrito: passa a postar pro **endpoint da assinatura**
  (`chatgpt.com/backend-api/codex/responses` + tool `image_generation`, modelo `gpt-image-2`) —
  **texto→imagem E imagem→imagem na MESMA chamada** (`input_image` parts).
- Host precisa ser `gpt-5.5` (`gpt-5.1` retorna `HTTP 400`).
- `codex_headers.py` (novo): headers anti-Cloudflare (`originator`/User-Agent `codex_cli_rs` +
  `ChatGPT-Account-Id`) — o `account_id` normalmente NÃO vem no claim do JWT, então resolve por fallback
  em `~/.codex/auth.json` → `tokens.account_id`; `oauth.codex_account_id()` novo.
- `transports.py`: retrofit dos MESMOS headers no chat codex — conserta um `403` **latente** que já
  existia na VPS (mesma causa-raiz, nunca tinha sido diagnosticada).
- Fallback pra `flux`/`openrouter` (padrão `IMAGE_BACKENDS`, como no `videogen`); `GenerateImage.check()`
  já consulta o fallback.
- **VERIFICADO AO VIVO**: PNG real gerado via assinatura (861KB), fim a fim.
- Nova skill **`editar-pdf`**: `info`/`extract`/`metadata`/`patch`/`rotate`/`merge`/`split` via `pypdf`
  (dependência lazy, só carrega se a skill for usada).

### 🛡️ Segurança + quick wins
- **SSRF**: auditoria confirmou que `net_guard` já bloqueava metadata endpoint, IP privado e redirect
  (com `allow_private` explícito), já plugado em `web_extract`/`browse`/`references` — sem regressão,
  documentado.
- Busca de arquivos ganha backend **ripgrep** com fallback pure-Python automático quando `rg` não está
  instalado — respeita `.gitignore` nos dois caminhos.
- **`ANTISLOP.md`** (novo): 15 padrões PT-BR anti-"cara de chatbot" injetados no `core_block` todo turno
  (banido: "Como posso ajudar?", hedging excessivo, entusiasmo vazio, bullet-slop, etc.) — shipado como
  default **versionado** em `okami/builtin/identity` (instalação nova já nasce com ele; override local
  continua tendo prioridade).

### 🔌 Barramento de hooks unificado
- **15 pontos de hook** (eram ~4, espalhados em dois sistemas que não se falavam): `pre_tool_call` /
  `post_tool_call`, `pre_llm_call` / `post_llm_call`, `pre_verify`, ciclo de vida de sessão,
  `subagent_start` / `subagent_stop`, entre outros.
- Bridge dos hooks shell existentes pro barramento novo — nenhum hook antigo quebra.
- Wiring cirúrgico em `loop.py`/`runner.py`; `register_*` novo pra plugins registrarem hooks sem tocar no
  core.

### 🌐 Browser em segundo plano + edição de PDF
- **Sessão persistente** (`browser_session.py`, thread-bound, com idle reaper): clicar login → dashboard
  → relatório **sem re-navegar** a cada passo — antes cada ação de browser era stateless.
- Ações novas: `scroll`, `back`, `press`, `eval` (guardado contra exfiltração de cookie/localStorage),
  `close_session`.
- Screenshot exposto como **image block** nativo (helper compartilhado `image_block.py`).
- Diálogos JS (`alert`/`confirm`/`prompt`) com auto-dismiss — sem travar a sessão esperando um clique que
  nunca vem.
- Idle reaper garante que uma VPS 24/7 **nunca vaza processo Chromium** aberto.

### 🧭 Onde já estávamos na frente (confirmado, sem mudança)
- HTML→PDF sem depender de Chromium (o Hermes depende).
- Identidade em 3 arquivos (`SOUL`/`VOICE`/`PERSONA`) vs blob genérico único do Hermes.
- Checkpoints de sessão; cofre de segredo cifrado (`v0.12.0-beta`).

### 🚧 Em andamento, fora desta release
- 3 sessões de fix de provider rodando em paralelo: crash de streaming do Claude, bug do token-store do
  Codex (token corrompido de 9 caracteres ofuscava o token válido da CLI — **precisa ser corrigido pra
  geração de imagem funcionar fim a fim** num usuário novo), parser do `claude_cli`.

### 🧪 Suíte
- **3.576 testes passando** (3.572 → 3.576).

## [0.12.0-beta] — 2026-07-08

A afirmação de "paridade com o Hermes" das releases anteriores era real para auditoria de código, mas
otimista demais para uso real. Esta release fecha 3 gaps de **uso real** — do tipo que só aparece operando
o agente no dia a dia, não lendo diff de código. No meio do caminho de mapear o primeiro, apareceu também
uma regressão autoinfligida da própria onda de auditoria anterior (`v0.10.0-beta`): **todo turno pelo
gateway do Telegram estava quebrado**. Suíte: **3.468 → 3.500 testes**.

### 🔥 Regressão crítica — gateway crashava TODO turno (`da85c42`)
- `run_task`/`Harness.__init__` não aceitavam `set_no_interrupt`, param que o endpoint do gateway injeta
  desde a onda P0 (`7939d6e`) — `TypeError` mascarado como `❌ error` em CADA turno vindo do Telegram. O
  E2E anterior só cobria o caminho CLI (`okami task`), que não passa esse hook — nunca pegou.
- Corrigido: `run_task` ganha `set_no_interrupt`, encadeado no `_hkw` (padrão do `set_remote`);
  `Harness.__init__` aceita e guarda (`self._set_no_interrupt`, no-op no CLI).
- Efeito colateral bom: o demote guard do `/busy` interrupt — morto até agora, nada setava
  `no_interrupt=True` — **passa a funcionar de verdade**: `_compact()` marca a compactação como fase
  não-interrompível.
- Regressão travada em `test_it11_fixes.py` (contrato runner↔Harness).

### 🎯 `/steer` — injeta no turno em andamento sem cancelar
- `/steer <texto>`: injeta uma **MENSAGEM DIRETA DO USUÁRIO** no contexto do turno já rodando (marcador
  anti prompt-injection + nota de trust explícita no system prompt) — SEM cancelar. Ao lado do `/busy`
  interrupt (cancela e recomeça), agora existe também `/busy steer` (toda mensagem nova durante um turno
  vira steer em vez de interromper).
- `Session.pending_steer` + `steer_source` encadeados `run_task → Harness` (mesmo padrão do
  `set_no_interrupt`); drenado após cada resultado de tool; se não houver onde anexar, fica **deferido**
  (nunca é perdido); `/cancel`, `/stop` e `/retry` limpam o steer pendente.

### 🔑 Onboarding de provider — assinatura/token-plan sem refém de CLI
- Diagnóstico: Okami já NÃO dependia de CLI pra minimax/mimo/grok (já eram `api_key` direto) nem pro
  Codex (já OAuth device-flow nativo) — o gap real era **descoberta** no menu, não arquitetura.
- Presets novos em `provider_catalog.py`: `minimax-oauth` (assinatura), `minimax-cn` (região China,
  `api.minimaxi.com`), `xai-oauth` (SuperGrok/Premium+, `client_id` real); `custom` reetiquetado como
  "traga seu próprio provider" (token-plan/API-key/endpoint OpenAI-compat).
- Nenhum transport novo — só torna visível o que já existia.

### 🔐 Segredo via chat — cofre cifrado, apaga e confirma
- Cenário: usuário remoto sem acesso ao `.env` manda a API key direto no Telegram, o agente guarda seguro
  e continua. Contrato de segurança: **salvar, apagar a mensagem original e confirmar** + **valor só no
  cofre, nunca exposto ao LLM**.
- Detecção no **INBOUND do gateway, ANTES do modelo ver** (`okami/core/redact.py`): prefixos de chave
  conhecidos (`ghp_`/`sk-`/`xai-`/`AKIA`/…) + padrão `NOME=valor` com keyword sensível e valor ≥12 chars
  sem espaço; guard contra falso-positivo (linguagem natural tipo "a senha é X" e valores curtos não
  disparam).
- Cofre cifrado novo (`okami/core/secretvault.py`): Fernet, chave 32B em `$OKAMI_HOME/.secret_key` (0600,
  lazy), vault JSON **só-ciphertext** (0600, escrita atômica); `resolve_secret` resolve `vault > env >
  .env`; `apply_vault_to_environ` popula `os.environ` no boot (`config._load_env`) — providers/oauth leem
  do cofre **sem editar nada**.
- Fluxo de captura: `vault_set` → `deleteMessage` no Telegram → confirmação `🔐 guardei a credencial X` →
  texto sanitizado in-place segue pro histórico/`run_task` (o modelo vê só a nota, nunca o valor).
- Bug de ordering corrigido no caminho: `redact(reply)` rodava DEPOIS de persistir — vazava no
  transcript/histórico; agora roda antes.
- Nova dependência: `cryptography>=42`. +40 testes de segurança; verificação independente confirma valor
  cru ausente do disco (só ciphertext, 0600), sem falso-positivo.

### ⚠️ Sobre a paridade
A alegação de "paridade com Hermes" das releases anteriores era real pra auditoria de código, mas
**superestimada pra uso real** — os 3 gaps acima (e a regressão do gateway) só apareceram operando o
agente de verdade, não lendo diff. Esta release fecha essa lacuna e assume o erro.

### 🧪 Suíte
- **3.500 testes passando** (3.468 → 3.500).

## [0.11.0-beta] — 2026-07-08

Lançada no MESMO DIA da `v0.10.0-beta`. 1 commit (`4bfbc14`), mas denso: **5 ondas paralelas** atacando 3
frentes de fricção no uso real — troca de provider/modelo pouco visível, qualidade baixa nas chamadas de
tool e falta de skills práticas para workflows do dia a dia (pesquisa, monitoramento, automação). Suíte:
**3.364 → 3.443 testes**. E2E real (minimax): task `COMPLETE` com auto-verificação (od/wc/sha256),
inclusive interceptando e corrigindo sozinho um bug de `echo -n` no meio da execução. 🐺

### 🔀 Troca de modelo
- **`okami/llm/model_aliases.py`**: resolver ÚNICO de alias/tier — aliases semânticos (`sonnet`, `opus`,
  `haiku`, `codex`, `gpt`, `minimax`, `mimo`, `grok`, …), tiers dinâmicos `fast`/`smart`, validação contra
  o catálogo de providers, extensível via `model_aliases:` no yaml.
- **`okami model`** (novo comando): picker interativo, switch direto, `list --json`.
- **`/model`** no gateway/Telegram passa a usar o MESMO resolver — ganha `--save` (persiste em
  `okami.local.yaml`) e `/models` numerado (uso mobile sem digitar nome completo).
- Typo de alias agora vira erro com sugestão (did-you-mean) em vez de aplicar um override silencioso errado.

### 🛠️ Tools — schema rico (causa #1 diagnosticada das chamadas ruins)
- `to_openai_schema` passa a emitir `enum`/`default`/`minimum`/`maximum` (`arg_constraints`) — antes todo
  parâmetro de "modo" era texto livre, sem contrato, e o modelo chutava valor. Aplicado em
  `search_files`, `spawn_jobs`, `todo_write`, `spawn`, `manage_skill`, `browse`.
- Bug real corrigido: `spawn.background` sem tipo `boolean` — a string `"false"` virava `True` no runtime.
- `todo_write`: leitura sem args, merge por `id`, status `cancelled` (paridade com o `TODO_SCHEMA` do
  Hermes).

### ✏️ Edit — paridade de cadeia de estratégias fuzzy (Hermes)
- Novas estratégias: `escape_normalized` (`\n` literal), `trimmed_boundary`, `block_anchor` (ancora
  primeira+última linha, `difflib` no meio) — mais de 1 match seguem sendo tratados como ambíguo, o edit
  nunca escolhe sozinho entre candidatos.
- Did-you-mean top-3 com números de linha; `read_file` ganha `line_numbers` opt-in.

### 🧩 Skills práticas (sem pokemon)
- **`watchers`**: RSS/GitHub/JSON com poll + watermark dedup — a base de "me avisa quando X mudar" via
  cron → Telegram.
- **`pesquisa-web`** ganha scripts: `arxiv` + `wikipedia`, com HTTP compartilhado.
- **`stocks`**: cotações via Yahoo Finance, sem API key.
- **`github`**: CI/merge/issues, `gh`-first com fallback via `gh_api.py`.
- Mecanismo novo: frontmatter `requires_tools`/`fallback_for_tools` esconde a skill quando o tooling
  necessário não está disponível (paridade Hermes).

### 🔌 Plugins
- Hook `transform_tool_result`: não-bloqueante, componível, isolado por plugin.
- `security-guidance`: veto vira aviso ANEXADO ao resultado da tool — o próprio modelo vê e se
  autocorrige, em vez de a tool simplesmente falhar sem explicação.

### 🧪 Suíte
- **3.443 testes passando** (3.364 → 3.443). E2E real com minimax: `COMPLETE` com auto-verificação
  mecânica (od/wc/sha256).

## [0.10.0-beta] — 2026-07-08

Primeiro **beta**: promoção do alpha por MATURIDADE, não por feature nova. Motivo — auditoria E2E completa
vs Hermes (8 agentes, uso real com minimax) achou a causa-raiz de o agente parecer "burro/lento" em
campo, e 3 ondas de correção (P0 `7939d6e` · P1 `c030281` · P2 `29d648e`) fecharam do sintoma à causa.
Desde o `v0.9.0-alpha`: **193 commits · 403 arquivos · +23.841/−1.021 linhas · suíte 2.408 → 3.364
testes**. 🐺

### 🔎 Auditoria E2E vs Hermes (uso real, 8 agentes) — por que o agente "parecia burro"
Sintoma em uso real: respostas lentas, tarefa simples travando, formatação quebrada no Telegram.
Não era 1 bug — era uma cadeia de degradação silenciosa. Achados e correções, do sintoma à causa:
- **probe de tool-calling nativo quebrado (TypeError silencioso)**: todo provider NÃO-hardcoded (ex.:
  minimax) caía pro rail JSON-em-texto sem avisar — perdia tool-calling nativo, thinking vazava no texto,
  contexto inchava. Verdict agora persiste em disco (`native_verdict.json`); hint explícito do catálogo
  pula o probe.
- **retry zero com 1 credencial só**: `max_retries` estava acoplado ao tamanho do key-pool — com 1 chave
  só, zero retry. Agora desacoplado (default 3) + timeout por tier (local 1800s / cloud 600s, antes 150s
  flat matava geração longa de modelo local).
- **tool-results cortados 8K/1.5K flat**: agora o orçamento ESCALA com a janela do modelo (15%/30% do
  contexto, floor 8K/16K, cap 100K/200K) — modelo com janela grande não perde ferramenta por corte cego.
- **Telegram dividia ANTES de formatar**: resposta >4096 chars perdia toda a formatação HTML (tags cortadas
  no meio) — agora renderiza o HTML completo primeiro, divide por unidades UTF-16 com tags balanceadas
  entre cortes, sanitiza marcador desbalanceado.
- **STT/link-summary bloqueavam o poll loop de TODOS os chats**: uma transcrição de áudio ou resumo de
  link travava o gateway inteiro por chat nenhum receber mensagem; agora rodam fora do poll loop
  compartilhado (spawn por chat) + cap de fila 32 + demotion guard de interrupt.
- **MEMORY.md poluído por auto-write mecânico**: `_extract_on_complete` despejava "goal → result" cru na
  memória — só `remember`/`remember_user`/`reflect` escrevem lá agora; gate de durabilidade (≥2 passos com
  efeito) pra memória ranqueada; dedup near-duplicate por Jaccard.
- **hooks builtin sem bit +x**: `security-guidance`/`disk-cleanup` vetavam TODA tool com exit 126
  silencioso (script sem permissão de execução) — corrigido o bit no pacote.
- **`okami run` alucinava tool-calls**: sem aviso explícito de "sem tools disponíveis" no system prompt, o
  modelo fraco inventava `tool_call` que não existia — agora avisa explícito + strip de `<think>` no
  output exibido.
- **streaming × rail nativo em conflito**: `streaming_enabled` checava o TIER antes de saber se o provider
  suportava tools nativas — ligar streaming pra minimax (rail nativo) quebrava porque o caminho de
  streaming nunca anexava `tools=` no payload (regressão exposta pela própria correção do probe P0). Agora
  `streaming_enabled` consulta `native_supported` primeiro.
- **E2E real (minimax), antes → depois**: BLOCKED/alucinando/vazamento de `<think>` → **COMPLETE** com
  verificação mecânica (sha256), formatação íntegra no Telegram, `tokens_in` 6.4-7K → 2.7K por turno.

### ⚙️ Onda P2 — quick-wins de qualidade (harness, gateway, run, TUI)
- **loop-guard avisa antes de bloquear**: warn no repeat #2, bloqueia só no #5 (paridade Hermes
  warn-then-block); contador unificado fecha loophole nome-ruim↔arg-faltando.
- **verify-on-stop**: `task_complete` com efeitos NÃO verificados ganha 1 nudge antes de aceitar (aceita na
  2ª tentativa — sem risco de loop infinito).
- **`spawn` promovido a tool core** — modelos fracos agora decompõem tarefa em subagentes por padrão.
- **`okami prompt-size`**: breakdown de chars/tokens por seção do prompt (diagnóstico de inchaço).
- **mensagens proativas do cron espelhadas no transcript** (PII mascarado só na cópia da sessão);
  `session_limit.py` morto removido.
- **TUI hardening**: bracketed-paste defensivo (paste-end perdido não trava input), focus-report ESC[I/O
  ignorado (lixo em iTerm2/Ghostty), `/redraw` + repaint em SIGWINCH, `okami sessions delete`,
  version-drift no `doctor`, verbos pt-BR nos tool-calls + sufixo `[exit N]` em falhas.
- Suíte: **3.364 testes passando**.

### 🐛 Revisão adversarial (4 bugs que a própria campanha introduziu)
Review adversarial pós-campanha achou 4 regressões reais introduzidas pelas ondas P0-P2 — corrigidas antes
do beta (detalhe: `7b4395b`).

### 🤖 paridade multi-vendor/Telegram/gateway/plugins (~190 commits desde o alpha)
O grosso do trabalho entre `v0.9.0-alpha` e o beta: fechar o diff funcional vs Hermes (74 gaps
missing/59 parciais mapeados) em ondas por área — loop → tools → telegram → gateway → plugins. Destaques
(lista completa nas seções abaixo, já documentadas no [Não lançado] anterior):
- **multi-agente supervisor** (`okami agent up/down/status/supervise`), **portabilidade** Windows/Mac/Linux
  (14 breaks corrigidos), **provisão remota VPS-first** (ssh/git bootstrap sem depender da máquina do
  usuário), `system_monitor`/`restart_gateway`/`env_check`, WebFetch resiliente com auto-fallback Playwright.
- **Telegram rico**: tabelas, listas, task lists GFM (☐/☑), clarify com botões inline, batch-delay
  adaptativo, entity flattening inbound.
- **gateway**: LRU de sessões, dedup de reenvio, auto-resume <1h, `typed_command_prefix` por canal.
- **multi-vendor**: reasoning-echo (DeepSeek/Kimi/MiMo), cap de output, recalibração de contexto via erro
  do provider, OpenRouter routing hints, `num_ctx` do Ollama.
- **codex**: replay de reasoning (`encrypted_content`) no mesmo turno, captura de deltas de raciocínio do
  stream Responses.
- **plugins**: lifecycle completo (register tools/commands/context, LLM gated).
- **edit fuzzy** unicode→ASCII (aspas curvas/travessão/nbsp não derrubam mais a edição).

### 🤖 Onda 3 — MULTI-AGENTE: cada agente seu próprio gateway, supervisionado (watchdog + auto-restart)
Objetivo: suportar N agentes, cada um com gateway/cron/heartbeat/tasks próprios. A fundação já existia (homes
isolados em agents/<id>/, tokens próprios, load_agents) — faltava o ciclo de vida em runtime.
- **`okami/gateway/supervisor.py` (AgentSupervisor)**: sobe cada agente como SEU PRÓPRIO processo de
  gateway (`okami gateway --foreground --agent <id>`), com registro durável em ~/.okami/runtime/agents.json
  (anti-PID-reuse via start-time), cross-plataforma. up/down/status + **supervise_once (watchdog)** que
  ressobe quem caiu. spawn_fn/agent_ids_fn injetáveis → lógica 100% testada.
- **`okami gateway --agent <id>`**: roda o gateway de UM agente só (bot/cron/heartbeat isolados).
- **CLI `okami agent up | down | status | supervise`**: liga/desliga/vê/vigia a frota; `supervise` é o
  laço de watchdog (Ctrl+C sai, os gateways seguem no ar).
+4 testes (sobe-uma-vez, watchdog ressobe morto, stop/down, registro durável entre instâncias).

### 🛰️ Onda 2 (continuação) — graceful drain + auto-diagnóstico + remote-from-chat
- **env_check** (tool + okami/core/envhealth.py): auto-diagnóstico do ambiente (pip/venv gravável,
  binários git/ssh/rg/ffmpeg…, disco) com issues acionáveis; alerta o usuário no boot se algo está ruim.
- **parada graciosa**: SIGTERM/SIGINT → drena e persiste o dedup; _seen_msgs sobrevive ao restart
  (.okami/seen_msgs.json) → não reprocessa mensagem após reiniciar.
- **remote_add** (tool): cadastra host SSH/Tailscale pelo chat (config.set_local → okami.local.yaml),
  validado contra injeção; libera o alias no remote_connect (inclusive Telegram).

### 🛰️ autonomia na VPS (auditoria × Hermes, wave 1) — monitor de host, auto-restart, web resiliente
Auditoria de VPS-readiness vs Hermes (8 dimensões → roadmap). Wave 1 (os itens críticos priorizados):
- **`system_monitor`** (tool, novo `okami/core/sysmon.py`): saúde do HOST — disco/RAM/CPU/load/uptime,
  cross-plataforma (stdlib p/ disco sempre + psutil auto-instalado p/ o resto), com alertas acionáveis
  (disco/RAM/cpu altos) pra o agente decidir adiar/limpar antes de tarefa pesada. (antes o memwatch só
  via o próprio processo).
- **`restart_gateway`** (tool): o AGENTE reinicia o próprio gateway (pega código/config novos, recupera de
  estado ruim) via o `schedule_self_restart` já existente — antes só dava pelo `/restart` no chat.
- **WebFetch resiliente** (`integrations/browser.py:fetch`): RETRY com backoff exponencial + jitter em erro
  TRANSITÓRIO (429/5xx/timeout, honrando `Retry-After`); PERMANENTE (403/404) falha na hora. Numa VPS a
  rede oscila e fonte com rate-limit não pode matar a tarefa no 1º erro.
- **computer_use** já poda em Linux headless (fix da rodada de portabilidade) → sem falsa promessa de
  controle de tela na VPS. +1 teste confirmando.
+10 testes. Resto do roadmap (env auto-repair, multi-agent lifecycle, graceful drain, etc.) em ondas.

### 🖥️ portabilidade Windows/Mac/Linux × VPS/local — 14 breaks REAIS corrigidos (auditoria adversarial)
Auditoria por 7 finders + triagem rigorosa (51 brutos → 14 confirmados, 30 descartados por degradarem
gracioso). Novo `okami/core/platform_compat.py` centraliza o que difere entre POSIX e Windows.
- **Crashes no Windows:** `processes.py` usava `os.getpgid` (AttributeError, não OSError → escapava do
  handler) e `start_new_session=True` (ValueError no Windows) e `os.mkfifo` → agora `terminate_pid()` +
  `popen_session_kwargs()` (creationflags no Windows) + modo interativo barrado com erro claro.
  `ptyproc.py` (pty/select POSIX-only) ganha guarda de import.
- **Segredo/chave exposto:** `os.chmod(0o600)` é no-op no Windows (NTFS=ACL) e o ssh RECUSA chave frouxa
  → `secure_chmod()` (POSIX chmod+VERIFICA / Windows ACL via icacls) em provision/config/safe_io/backup.
- **VPS headless:** Playwright agora `headless=True` (senão crasha sem $DISPLAY); backend pyautogui poda
  em Linux sem $DISPLAY; serviço systemd vira multi-user.target (root) ou user-service+linger (boota sem
  login); `attach` checa TTY antes do input (não trava em cron/headless).
- **Encoding/paths:** pidfiles com `encoding='utf-8'` (Windows = cp1252 por default → UnicodeDecodeError);
  socket de controle usa `tempfile.gettempdir()` em vez de `/tmp` hardcoded (inexistente no Windows).
+15 testes. 2770 passed. O agente roda nas 3 plataformas, VPS ou local, sem depender de sorte.

### 🌐 provisão remota (VPS-first) — o agente bootstrappa o PRÓPRIO acesso (SSH + GitHub)
Falha de arquitetura: o agente assumia que o host já tinha as credenciais do usuário (gh/git/ssh
herdados) — errado pra uma VPS 24/7, onde não existe login herdado. Pior, o jail `.ssh`/`.env` e o
`sanitized_env` IMPEDIAM o agente de se provisionar. Agora ele monta o acesso sozinho, dirigido pelo
usuário via canal:
- **`okami/integrations/provision.py`**: primitivas sancionadas (furam o jail só aqui) — gerar chave
  ed25519, importar chave privada (0600), ssh-keyscan→known_hosts, configurar GitHub por token
  (credential-helper FILE-BASED → funciona mesmo com env sanitizado) ou por SSH (url.insteadOf), status
  e verify. Segredo NUNCA volta no retorno; HOME injetável (não polui ~/.gitconfig real).
- **Tools `ssh_identity` e `git_auth`** (danger=dangerous → approval-gated; negadas no Telegram sem o
  grant). O usuário cola um PAT (store_secret) ou deixa o agente GERAR a chave e mostrar só a pública.
- **Skill nativa `acesso-vps`**: ensina o procedimento ponta-a-ponta (token vs chave SSH, guiar o usuário
  a adicionar a pubkey no GitHub, verificar) — dispara em "git push/clone/permission denied/ssh".
+21 testes (módulo + tools). Instalação remota deixa de depender da máquina do usuário.

### 🎙️ voz EMBUTIDA + recursos NATIVOS (skills e plugins que viajam no pacote)
- **STT (Whisper) ligado por padrão + auto-install**: nota de voz enviada ao agente ficava sem resposta —
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
era fire-and-forget pro USUÁRIO — o agente pai não conseguia USAR o resultado (não dava pra encadear). O
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
resultado em `.okami/spawn/<id>.json` e **avisa no chat que pediu** (captura o `ctx.notify` daquele
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
  Ainda NÃO vence captcha (decisão de escopo: handoff p/ browser real, na fila). +10 testes.

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
  usa o token do PRÓPRIO agente (channels.telegram), target=chat_id ou vazio→destinatário padrão;
  `danger=sensitive`
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

Rodada **#20** — fechados os 3 itens que faltavam para completar a implantação: **computer-use
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
  (plugin de terceiro não redireciona tráfego/gasto à revelia do usuário).
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
  (time/enum/weekdays) que vira job de cron — sem precisar digitar cron cru.
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

[0.14.0-beta]: https://github.com/OkamiOps/Okami-Agent/releases/tag/v0.14.0-beta
[0.13.0-beta]: https://github.com/OkamiOps/Okami-Agent/releases/tag/v0.13.0-beta
[0.12.0-beta]: https://github.com/OkamiOps/Okami-Agent/releases/tag/v0.12.0-beta
[0.11.0-beta]: https://github.com/OkamiOps/Okami-Agent/releases/tag/v0.11.0-beta
[0.10.0-beta]: https://github.com/OkamiOps/Okami-Agent/releases/tag/v0.10.0-beta
[0.1.0-alpha]: https://github.com/OkamiOps/Okami-Agent/releases/tag/v0.1.0-alpha
