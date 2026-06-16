# Changelog

Todas as mudanças notáveis do **Okami Agent**. Formato baseado em
[Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versionamento
[SemVer](https://semver.org/lang/pt-BR/) (pré-1.0 = a superfície ainda pode mudar entre alphas).

## [0.9.0-alpha] — 2026-06-16

Salto grande de capacidade — **~94/100 de paridade** com o estado-da-arte (NousResearch/hermes-agent),
incluindo **prontidão multi-vendor**. De ~1.7k → **2.4k testes passando**. 🐺

### Highlights
- **Prontidão multi-vendor**: transportes NATIVOS Gemini (`generateContent`) e Bedrock (Converse/IAM)
  — assinatura-Claude hoje, mas pronto p/ trocar de vendor quando precisar. `lazy_deps` instala o SDK
  só quando ativar.
- **Segurança endurecida**: biblioteca de threat-patterns scope-aware (injeção/C2/anti-forense/unicode),
  scan de injeção em arquivo de contexto (AGENTS.md/.cursorrules), scanner de exfil + OSV malware-check
  em MCP, preflight de CA-bundle SSL, e o **Tirith** (scan de conteúdo pré-exec: homograph/pipe-to-shell).
- **Resiliência de provider/modelo-local**: recuperação reativa de erro (401-refresh, image-shrink),
  reparo multi-passe de tool-call JSON, sanitização de schema p/ llama.cpp, stall-vs-truncation.
- **UX por plataforma**: display-config em tiers, heartbeat de turno longo, panic-hook, detecção de
  silêncio multi-marcador, merge de álbum de fotos, auto-extração de imagem do texto, TTS.
- **Automação & extensibilidade**: Blueprints (automação parametrizada), Kanban swarm (workers →
  verificador → sintetizador), descoberta de plugins (pasta + entry-point pip), browser supervisor (CDP),
  dashboard web leve + `okami gui`.

### Added
- Transportes `gemini_native` / `bedrock_native` (tradução OpenAI↔nativo, dispatch, SDK lazy).
- `okami deps` (lazy-install de backend opcional, allowlist + venv-scoped + opt-out).
- `okami blueprint` (automação parametrizada → cron) e `okami swarm` (plano de enxame + blackboard).
- `okami plugins` (descoberta) · `okami gui` (dashboard web leve, zero-dep) · `okami completion`
  (bash/zsh/fish) · `okami mcp --auth` (OAuth 2.1 + PKCE p/ MCP protegido).
- `okami logs --level/--component/--since`, `okami doctor --fix` recupera SQLite malformado.
- Skills: bundles, config no frontmatter, gating por plataforma/ambiente, tiers de confiança.
- `env_probe`, `text_to_speech`, file.attach por WebSocket.

### Changed
- Default `Budget.max_context_chars` 24000 → 64000 (o system-prompt cresceu; produção sobrescreve).
- `_SENSITIVE_PATH` libera `.env.example`/`.env.js` (template/código), mantém `.env`/`.env.local` barrados.
- PII mascara id colado a `_`; coalesce mescla rajada de fotos do mesmo chat.

### Fixed
- Caça adversarial de bugs por subagentes: ~36 defeitos reais corrigidos com TDD ao longo de #7-#13
  (entre eles: `skill_matches_platform` escondendo skill macOS no Mac; injeção markdown-ofuscada;
  panic-hook que crashava; transporte Gemini perdendo o system prompt; tokens bedrock/gemini zerados).

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
