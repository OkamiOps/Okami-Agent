# Changelog

Todas as mudanças notáveis do **Okami Agent**. Formato baseado em
[Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versionamento
[SemVer](https://semver.org/lang/pt-BR/) (pré-1.0 = a superfície ainda pode mudar entre alphas).

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
