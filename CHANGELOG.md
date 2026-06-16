# Changelog

Todas as mudanças notáveis do **Okami Agent**. Formato baseado em
[Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versionamento
[SemVer](https://semver.org/lang/pt-BR/) (pré-1.0 = a superfície ainda pode mudar entre alphas).

## [0.9.0-alpha] — 2026-06-16

Salto grande de capacidade. **~99/100 de paridade FUNCIONAL** com o estado-da-arte
(NousResearch/hermes-agent), incluindo **prontidão multi-vendor**. De ~1.7k → **2.433 testes passando**.
~44 defeitos reais caçados por subagentes adversariais e corrigidos com TDD ao longo de 8 rodadas de
pesquisa (#7–#14). 🐺

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
  Status/Sessões/Config(read-only, só nomes de env)/Logs; `--app` abre em janela app-mode do browser.

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
~44 defeitos reais (subagentes adversariais + TDD). Destaques: `_SENSITIVE_PATH` não barrava `.envrc`
(direnv); `skill_matches_platform` escondia skill macOS no Mac (sys.platform='darwin'≠'macos');
injeção ofuscada por markdown escapava o scan; panic-hook crashava com `__str__` ruim; transporte Gemini
perdia o system prompt (kwarg errado) e descartava imagem; checksum do Tirith casava por sufixo de path;
`run_swarm` propagava None; race no `sessions.json.tmp`; YAML malformado derrubava `load_skills`;
`format_tokens(1e9)` dava "1.0B".

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
