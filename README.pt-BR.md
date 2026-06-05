<!-- 🌐 [English](README.md) · **Português** -->
<div align="center">

[English](README.md) · **Português**

# 🐺 Okami Agent

**IA com soberania para PMEs.**
Agente de codificação **confiável**, com **paridade de capacidade entre LLMs**, **auto-melhoria**
(skills · persona · memória) e **aderência obrigatória a design systems** — no terminal, no Telegram,
ou onde você quiser.

![version](https://img.shields.io/badge/version-0.1.0--alpha-ff7527)
![python](https://img.shields.io/badge/python-3.11+-3776AB?logo=python&logoColor=white)
![uv](https://img.shields.io/badge/managed%20by-uv-DE5FE9)
![litellm](https://img.shields.io/badge/router-LiteLLM-00A98F)
![tests](https://img.shields.io/badge/tests-880%20passing-3fb950)
![status](https://img.shields.io/badge/status-public%20alpha-orange)

**[🌐 okamiagent.com](https://okamiagent.com)** · **[📚 Documentação](https://okamiagent.com/docs)** · **[🎨 Landing (fonte)](https://github.com/OkamiOps/Okami-Agent-LP)**

</div>

---

> 🐺 **Alpha público (`v0.1.0-alpha`).** O Okami está aberto pra você experimentar. A superfície de
> comandos/config ainda pode mudar entre alphas — para expor publicamente, rode `okami policy check
> --strict` antes. Feedback é muito bem-vindo. Veja o [CHANGELOG](CHANGELOG.md).

O `okami chat` abre um **TUI de tela cheia** na identidade da marca (Onyx + Heat Orange / Volt Cyan):

![okami chat welcome](docs/images/chat-welcome.svg)

Cada turno tem separação clara, emoji por evento (🧠 pensar · 🛠️ tool) e um **rodapé de custo por
resposta** (ctx · tokens · tempo) — você sabe exatamente o que gastou:

![okami chat](docs/images/chat-demo.svg)

**Paridade multi-modelo** com assinatura-only (Codex/Claude por OAuth/CLI, LMStudio local, MiniMax/MiMo
por Token Plan), com fallback automático:

![okami providers](docs/images/providers.svg)

E a prontidão de release é um comando só (`okami readiness` — CI verde · strict verde · strict no HEAD):

![okami readiness](docs/images/readiness.svg)

> Documentação completa em **[okamiagent.com/docs](https://okamiagent.com/docs)**. No repo:
> [Arquitetura](docs/ARCHITECTURE.md) · [Roadmap](docs/ROADMAP.md) · [Estrutura](docs/STRUCTURE.md) ·
> [Produção/GA](docs/PRODUCTION.md) · [Pesquisa competitiva](docs/COMPETITIVE_RESEARCH.md).

---

## Por que o Okami existe (as duas dores)

1. **Harness não-confiável** — o agente diz *"vou fazer"* e não age; cobrado, diz *"pera, tô fazendo"*
   e nunca conclui. Loop sem invariante de ação e sem detecção de conclusão real.
2. **Não adere a skills / design system** — você pede ShadCN/HeroUI e ele inventa CSS feio. Skill como
   sugestão, não como **gate**; sem verificação mecânica.

O Okami resolve as duas **por construção** (harness com *action-or-terminate* + *verification gates*)
e leva o resto além: memória de verdade, **auto-melhoria**, **persona que evolui** e **gosto que
aprende** — tudo plugável e funcionando **com qualquer LLM** (do GPT-5/Claude ao seu modelo local no
LMStudio).

---

## Destaques

| | |
|---|---|
| 🧠 **Harness confiável** | *Action-or-Terminate*, anti-loop, anti-alucinação, *exit criteria* verificados mecanicamente. Protocolo JSON **+** tool-calling nativo (dual-mode). |
| 🔀 **Paridade multi-modelo** | LMStudio (local), **Codex/GPT-5**, **Claude**, MiniMax, MiMo — com **fallback automático** entre eles. **Assinatura-only** (OAuth/CLI), nunca pay-as-you-go. |
| 🎨 **Aderência a design system** | *Contracts* (ShadCN/HeroUI) + *verification gates* que **reprovam** hex inline, CSS cru, e import fora do `@/components/ui`. |
| 🧬 **Auto-melhoria** | Persona que evolui (SOUL/VOICE/PERSONA, com go/no-go), **taste model** (curte/rejeita design), e *closed learning loop* que destila skills. |
| 🗄️ **Memória plugável** | `sqlite-fts5` (default), holográfica, Honcho, ou em camadas — com embeddings, **auto-compaction** e citação de origem. |
| 🛡️ **Segurança fail-closed** | Sandbox real (Docker), aprovação go/no-go persistente, guarda anti-SSRF, redator central de segredos, *trust store* de MCP, journal de checkpoints com HMAC. |
| 📜 **Conformance autorada** | `okami.policy.yaml` versionado + `okami policy check` (gate de CI) + `--strict` (postura de produção/GA). |
| 💬 **Multi-canal** | Terminal (TUI), Telegram (botões inline), Slack, Discord, Mattermost, **API HTTP**, Paperclip e **ACP** (IDE Zed/VS Code). |
| 🔭 **Observabilidade** | Event log com `trace_id`, **replay de trajetória** por turno, `doctor --json/--lint`, usage + custo por sessão, audit log. |
| ⚙️ **Operável** | Processos em background com **PTY interativo**, cron, hooks, hot-reload de config, faxina de disco, perfis de auth. |

---

## Instalação

**O único pré-requisito é o `git`.** O instalador usa o [uv](https://docs.astral.sh/uv/) como motor —
ele baixa o Python, cria o ambiente isolado e instala tudo. **Você não precisa de Python instalado**
e não sofre com long-path no Windows (o uv usa um diretório curto).

**Linux / macOS / WSL:**
```bash
curl -fsSL https://raw.githubusercontent.com/OkamiOps/Okami-Agent/main/scripts/install.sh | bash
```

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/OkamiOps/Okami-Agent/main/scripts/install.ps1 | iex
```

Depois (reabra o terminal se `okami` não for achado):
```bash
okami setup     # configura em 2-3 cliques (detecta seus providers)
okami chat      # conversa no terminal
```

**Tudo numa pasta só — `~/.okami/`** (ou `$OKAMI_HOME`), como o `~/.openclaw`/`~/.hermes`: o instalador
não espalha pelo SO. O código fica em `~/.okami/src`, o venv isolado em `~/.okami/tools`, o launcher em
`~/.okami/bin`, e os dados (skills, agents, sessões, `.env`, credenciais) em `~/.okami/` em runtime.
Atualizar/desinstalar = rodar o instalador de novo / `uv tool uninstall okami-agent`.

<details><summary><b>Dev (rodar do código, sem instalar global)</b></summary>

```bash
uv sync                       # cria o venv + deps a partir do pyproject
uv run okami doctor           # roda sem ativar nada
uv run okami chat
# editável global:  uv tool install -e .   (recarregue deps novas com --force)
make test                     # = uv run pytest -q   (suíte completa em pytest)
```
Sem uv: `python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"`
(no Windows use um caminho curto p/ o venv — ex. `C:\okv` — por causa do long-path do litellm.)
</details>

<details><summary><b>Docker (qualquer SO)</b></summary>

```bash
make docker-build                                            # docker build -f deploy/Dockerfile
docker compose -f deploy/docker-compose.yml run --rm okami doctor
docker compose -f deploy/docker-compose.yml run --rm okami task "crie hello.txt" -e file_exists:hello.txt
docker run --rm --entrypoint python okami-agent -m pytest -q  # roda a suíte na imagem Linux
```
> Para um LMStudio na máquina host, aponte `api_base` para `http://host.docker.internal:PORT/v1`.
</details>

**Extras opcionais** (`uv sync --extra <nome>`): `voice` (Whisper + Edge TTS) · `browser`
(Playwright) · `honcho` (memória Honcho) · `dev` (pytest).

---

## Primeiros passos

```bash
okami                      # visão geral dos comandos (= okami help)
okami setup                # assistente de configuração (menus de seta ↑↓)
okami doctor               # diagnostica config, chaves e conectividade
okami chat                 # conversa no terminal (TUI com sessão persistente)
okami chat "diga oi"       # uma pergunta e sai (scripts/pipe)
okami task "crie um endpoint /health em FastAPI" \
  -e file_exists:app/health.py -e "file_contains:app/health.py:/health"
okami gateway              # sobe os bots de Telegram (1 por agente)
```

- **Configuração** é sempre por **menu de seta** (↑↓ Enter); sem terminal interativo, cai num menu numerado.
- **Segredos** vão pro `.env` (projeto) ou `$OKAMI_HOME/.env` (global, default `~/.okami/.env`) — **nunca** pro `okami.yaml`, que é versionado.
- Sem instalar o entry point, dá para rodar com `python -m okami.cli ...`.

---

## O Harness confiável (resolve a Dor #1)

O coração do Okami é um loop ReAct com **invariantes de confiabilidade** — não é "deixa o modelo
conversar até cansar":

- **Action-or-Terminate** — todo passo OU executa uma tool OU termina explicitamente
  (`task_complete` / `task_blocked` / `need_input`). Não existe "tô pensando" infinito.
- **Exit criteria verificados** — você declara o critério (`file_exists:x`, `file_contains:x:txt`,
  `cmd_succeeds:pytest -q`) e o harness **confere mecanicamente** antes de aceitar a conclusão. Se o
  modelo declara `task_complete` mas o critério falha → `complete_rejected`, ele continua.
- **Anti-loop / anti-stall** — *fingerprint* das ações detecta repetição; comandos read-only não
  enganam o watchdog (`shell_has_effect`).
- **Dual-mode** — protocolo JSON (`{"tool": ..., "args": ...}`) para paridade entre LLMs **e**
  tool-calling nativo (Responses API do Codex; opt-in por provider).
- **Checkpoints & rollback** — toda escrita registra o estado anterior num journal append-only com
  **lock + HMAC encadeado**; `okami rollback N` desfaz as últimas N escritas.
- **Orçamento** — teto de passos/tokens por turno; *auto-compaction* da história quando o contexto enche.

---

## Skills, Contracts & Verification Gates (resolve a Dor #2)

- **Skills** (`skills/<nome>/SKILL.md`) são procedimentos versionados que o agente carrega sob demanda
  (`use_skill`). Já vêm várias: `frontend-shadcn`, `frontend-heroui`, `tdd`, `writing-plans`,
  `delegate-codex`, `humanizer`, `kanban-orchestrator`, …
- **Supply-chain** — toda skill instalada passa por **scan de segurança** (prompt-injection, malware,
  exfiltração de segredo, *trojan-source*, unicode oculto); **HIGH/CRITICAL é bloqueado**. Um
  `skills-lock.json` (sha256) detecta adulteração.
- **Contracts** (`okami.yaml → contracts.ui`) declaram o design system: `library: shadcn`,
  `forbid_inline_hex`, `forbid_raw_css`, `require_component_source`.
- **Verification gates** — `okami gate <dir>` (e os gates internos) **reprovam** mecanicamente código
  que viola o contrato. Skill deixa de ser sugestão e vira **gate**.

---

## Providers & paridade multi-modelo

Roteador via **LiteLLM** + transportes próprios. **Política dura: Claude e Codex são SEMPRE por
assinatura (OAuth/CLI), NUNCA pay-as-you-go.**

| Provider | Modelo (default) | Auth | Tier |
|---|---|---|---|
| **lmstudio** | `qwen3.5-4b-mtp` (local) | api_key local | local |
| **codex** | `gpt-5.5` | **OAuth device flow** (`okami login codex`) | strong |
| **claude** | `claude-opus-4-8` | **CLI oficial `claude`** (assinatura) | strong |
| **minimax** | `MiniMax-M3` | **Subscription Key do Token Plan** (`MINIMAX_API_KEY`) | weak |
| **mimo** | `mimo-v2.5-pro` | **API key do Token Plan** (`MIMO_API_KEY` no `.env`) | weak |

- **Fallback automático** — cada provider tem uma cadeia (`codex → [claude, minimax, lmstudio]`); se
  o principal cair (529/timeout/resposta vazia) o turno faz *failover* sem morrer.
- **Capability profile adaptativo** — `tier` (`strong`/`weak`/`local`) e `tool_mode`
  (`json_constrained`) preparam o agente para o modelo que você tem.
- **Descoberta ao vivo** — `okami provider models <nome>` lista os modelos via `/v1/models`, senão cai
  no catálogo. Troque o modelo da sessão com `/model <id>` e o esforço de raciocínio com `/think`.
- **Usage & custo** — tokens (incl. *cache read*) e custo acumulados por sessão; `okami status`/`/usage`.

---

## Memória plugável

- **Backends**: `sqlite-fts5` (default, BM25), **holográfica** (vetores `dim=1024`), **Honcho** (SaaS),
  ou **em camadas**. Busca **híbrida** (léxica + embeddings quando disponível; degrada p/ BM25 offline).
- **Política de escrita** — classifica cada fato (fato/preferência/decisão/skill/erro) e **barra o
  efêmero/trivial** antes de persistir.
- **Citação de origem** — toda memória injetada vem com `[categoria · origem · confiança]`.
- **Auto-compaction** — quando o contexto enche, turnos antigos viram nós de *summary* sem perder o fio.
- **Escopo + memória global** — `scope` (global/workspace/…) por item; com `memory.global`, preferências
  `scope=global` moram em `~/.okami` e valem em **qualquer** projeto, mas memória de um projeto **não**
  contamina outro. Schema com `confidence`, `expires_at` (TTL) e `supersedes_id` (consolidação).
- **Auditoria** — cada recall é logado (`retrieval_logs`); `okami memory explain <id>` mostra de onde a
  memória veio e quando/por que apareceu. `forget` (some) e `archive` (some, marcado) são reversíveis no histórico.
- **Consolidação** (heurística, sem LLM) — pós-tarefa e via `okami memory consolidate`: expira TTL vencido e
  funde quase-duplicatas (marca `superseded`, **não apaga**), respeitando confiança (não rebaixa preferência
  explícita por inferência fraca).
- **Persona Compiler** (`okami/learning/compiler.py`) — bloco CURTO de direção por turno (read-only): puxa p/
  precisão quando um papo casual tem assunto técnico, e adapta a abertura ao estado emocional da pessoa (sem
  distorcer a solução). A identidade inteira (SOUL/VOICE/PERSONA) segue sempre injetada; isto é só o delta do turno.
- CLI: `okami memory add|search|list|explain|forget|archive|consolidate|export` (`--global` p/ a casa). Arquivos
  de identidade/core (`SOUL/VOICE/PERSONA/AGENTS/USER/MEMORY`) são sempre injetados (limites configuráveis).

---

## Auto-melhoria (vai além do Hermes)

- **Persona evolutiva** — `SOUL.md` (quem é), `VOICE.md` (como fala), `PERSONA.md` (tom). Evoluem a
  partir de feedback (`/feedback`, `okami persona-evolve`) **com go/no-go + changelog + rollback**.
  O `SOUL.md` **nunca** evolui sozinho.
- **Taste model** — `okami taste like|dislike|different`: aprovações viram *atratores*, rejeições
  viram *repulsores*, e o *steering* resultante é injetado nos prompts de UI.
- **Closed learning loop** — tarefa não-trivial e bem-sucedida é refletida e pode **destilar uma
  skill** nova (que ainda passa pelo scan de segurança).

---

## O terminal (TUI)

`okami chat` é um **TUI de tela cheia em Textual**, na identidade da Okami (Onyx/Bone + Heat Orange
`#ff7527` · Volt Cyan `#00dfe8` · Neon Magenta `#ff39d1`):

- **Regiões fixas** — header · log rolável · painel de aprovação · input · barra de status pinada.
- **Digite enquanto o agente trabalha** — fila FIFO; 1 worker, sem corrida (via `call_from_thread`).
- **Tool-calls ao vivo** — cada passo aparece com ✓/✗; *loop detectado* e *aprovação* sinalizados.
- **Aprovação por botão** — go/no-go sem digitar; **Ctrl-C** aborta o turno, **Ctrl-D** sai.
- **Mouse + scroll**, status com *spinner* e *gauge* de contexto.
- **Fallback gracioso** — sem TTY (pipe/CI) cai num REPL concorrente; `--no-tui` força o REPL simples.

Dentro do chat, **comandos `/`** (saem de um registro declarativo único — help, autocomplete, "did you
mean"):

| categoria | comandos |
|---|---|
| sessão | `/new` `/stop` `/retry` `/compact` `/sessions` `/resume <n>` `/export [arq]` `/exit` |
| modelo | `/model [id]` `/models` `/think <nível>` |
| identidade | `/feedback <texto>` `/persona <preset>` `/undo` `/like` `/dislike` `/different` |
| info | `/help` `/commands` `/status` `/usage` `/tools` `/whoami` |
| sistema | `/yolo` `/normal` `/config` `/reload` |

---

## Canais & Gateway

Uma interface `Channel` única; cada canal é *deny-by-default* (allowlist explícita).

- **Telegram** — botões inline para aprovação (com **nonce** anti-stale), *split* de mensagens >4096,
  retry/backoff, dedup por turno, *typing*, e nota de voz → transcrição.
- **Slack · Discord · Mattermost** — REST-polling, mesma interface, anti-loop (ignora o próprio bot).
- **API HTTP** — `okami serve` (POST `/chat`, **Bearer `OKAMI_API_TOKEN`** fail-closed, bind `127.0.0.1`).
- **Paperclip** — `okami heartbeat` pega a issue atribuída e trabalha (com go/no-go).
- **ACP** — `okami acp`: a IDE (Zed/VS Code) dirige o Okami pelo Agent Client Protocol.

`okami gateway` sobe **1 bot por agente**; `okami room` é um **brainstorm multi-agente** com moderador
que decide quem fala (ou ninguém), com cooldown e caps anti-stampede.

> **Default de segurança:** sem `allow_chats`, o bot **não responde ninguém** (deny-by-default).
> Libere com `channels.telegram.allow_chats: [<seu_id>]` (ou `allow_all: true`, inseguro).

---

## Voz, imagem, browser e processos

- **Voz** — `okami voice` (turn-based: fala no mic → o agente responde **falando**), `okami transcribe`
  (Whisper local), `okami say` (Edge TTS).
- **Imagem** — `okami image "..."` (gpt-image-2 via assinatura Codex; `--ref foto.png` para edição).
- **Browser** — tool `browse` (Playwright; sem ela, *fetch* read-only) — **toda URL passa pela guarda
  anti-SSRF**.
- **Processos em background** — `process_start/poll/wait/log/list/kill/write/signal`: roda comando longo
  sem bloquear o turno, com estado em disco que **sobrevive ao restart**, **PTY interativo**
  (`process_write` manda stdin), `notify_on_complete`, `watch_patterns` com *strikes*, e *reconcile* de
  órfão. Tudo sob a mesma política de sandbox do `run_shell`.

---

## Modelo de Segurança

Segurança *fail-closed* é o diferencial do Okami para uso real/exposto. (Detalhes operacionais em
[docs/PRODUCTION.md](docs/PRODUCTION.md).)

- **Assinatura-only & segredos** — Claude/Codex sempre por OAuth/CLI; chaves só no `.env`
  (projeto ou global `$OKAMI_HOME/.env`, default `~/.okami/.env`, `chmod 600`), **nunca** no YAML versionado. O `config set` recusa
  segredo literal em chave pontilhada e manda usar `${ENV}`.
- **Aprovação go/no-go** — modos `manual` · `smart` (auto-aprova risco baixo) · `off`
  (**fail-closed**: sem prompt = nega o sensível) · `yolo` (bypass explícito por sessão). A aprovação é
  um **objeto persistente single-use** (`approval_id`, `args_hash`, `expires_at`, `used_at`) — clicar de
  novo (mesmo após restart) é recusado, e ela é amarrada aos **args exatos** da ação.
- **Sandbox** — backend **local** (cwd + env sanitizado + timeout + teto de saída + rlimits) ou
  **docker** (isolamento real: `--network none`, **não-root**, `--cap-drop ALL`, rootfs read-only, só o
  workspace montado, no-new-privileges). Perfis `dev` / `hardened` / `hardened-strict`, **endurecimento
  por superfície** (Telegram/API/… endurecem por padrão) e **egress allowlist** via proxy filtrante
  (com bloqueio anti-rede-interna).
- **Anti-SSRF** — `okami/core/net_guard.py`: toda URL controlada por usuário/modelo valida esquema
  http(s), resolve o host e **recusa** loopback/privada/link-local (incl. `169.254.169.254` metadata) e
  revalida cada redirect.
- **Redator central** — segredos (chaves, Bearer, JWT, AWS/GitHub/Slack tokens) são mascarados antes de
  ir pra log, saída de tool, audit (`.okami/audit.jsonl`) ou contexto do modelo.
- **File-safety** — *jail* de workspace (anti path-traversal/symlink), escrita atômica, teto de tamanho.
- **MCP trust store** — capabilities por tool (read/write/network/shell/secret-access), níveis de trust
  (`untrusted`/`reviewed`/`trusted`), HTTPS/local-only, e go/no-go por capability; tool de servidor
  não-confiável **sem manifesto** exige aprovação (não confia no nome bonitinho).
- **Checkpoints com integridade** — journal sob lock, **HMAC encadeado** (adulterar/inserir quebra a
  cadeia → rollback ignora a entrada forjada).

---

## Conformance & Política

Estilo OpenClaw *policy*: a postura é um **artefato autorado e versionado**.

```bash
okami policy check            # avalia config+workspace contra okami.policy.yaml (gate de CI)
okami policy check --strict   # postura de PRODUÇÃO/GA (exposto sem isolamento real = FAIL)
okami policy show [--strict]  # política efetiva
okami policy init             # scaffold de okami.policy.yaml
okami doctor --lint           # lint de postura (pass/warn/fail) — aprovação, segredo, sandbox, MCP…
okami auth list               # perfis de auth (tipo/status/onde mora a credencial — nunca o valor)
okami status --json           # status resolvido p/ monitoramento
```

O `okami.policy.yaml` governa: `approvals.mode_allow`, allowlist de **providers** e **modelos**,
**ingress** de canal (proíbe `allow_all`), **trust** de MCP, segredo fora do YAML, exposição do gateway,
metadata de tool e retenção. O modo `--strict` (overlay de produção) é o **gate de prontidão para GA**.

---

## Observabilidade

- **Event log** — `.okami/events.jsonl` (timeline append-only, redigida, com `trace_id` por turno).
- **Replay de trajetória** — `okami replay` lista os turnos; `okami replay <trace>` reconstrói o turno
  (▶ start · 🧠 llm · ✓✗ step · ⚠ approval · ⨯ failure · ■ desfecho); `--json` para ferramenta.
- **Doctor** — `okami doctor` (config/chaves/toolchain/sandbox), `--json` (saúde p/ CI), `--fix`
  (lock órfão, perms do `.env`, temp), `--lint` (postura).
- **Audit & usage** — `.okami/audit.jsonl` (toda tool + decisão de aprovação) e tokens/custo por sessão.
- **Faxina** — `okami clean [--deep]` (lock órfão, temp, áudio, sessões, checkpoints, process logs).

---

## Referência de comandos (CLI)

<details><summary><b>Ver todos os comandos</b></summary>

| Comando | O que faz |
|---|---|
| `okami setup` | Assistente de configuração (providers, login, memória, identidade, canal). |
| `okami chat [msg]` | Conversa no terminal (TUI); `-a <agente>`, `--no-tui`. |
| `okami task <goal> -e <crit>` | Roda o harness até COMPLETE/BLOCKED/NEEDS_INPUT/FAILED. |
| `okami run <prompt> [-p prov]` | Ida-e-volta crua ao provider (sem sessão/harness). |
| `okami doctor [--json\|--fix\|--lint]` | Diagnóstico / saúde / reparo / lint de postura. |
| `okami status [--json]` | Visão resolvida (agente, modelo, providers, toggles). |
| `okami login <provider>` | Autentica provider de assinatura (device flow / CLI). |
| `okami provider add\|list\|remove\|default\|login\|models` | Gerencia providers (menu de seta). |
| `okami auth list\|status` | Perfis de auth (metadata, sem segredo). |
| `okami policy check\|init\|show` | Conformance autorada (`--strict` p/ GA). |
| `okami config show\|get\|set\|unset\|path\|edit\|check` | Config efetiva (segredo → `.env`). |
| `okami memory add\|search\|list\|explain\|forget\|archive\|consolidate\|stats\|export` | Memória híbrida + auditoria/CRUD/consolidação/métricas (`--global` = casa `~/.okami`). |
| `okami taste like\|dislike\|different\|show\|steer` | Taste model de design. |
| `okami persona-init\|persona-evolve\|persona-log\|persona-rollback` | Identidade evolutiva. |
| `okami skills` / `okami learn <fonte>` / `okami scan <path>` | Skills + scan de segurança. |
| `okami agent new\|list` | Multi-agente (`agents/<id>`). |
| `okami gateway` / `okami serve` / `okami room` | Telegram bots / API HTTP / sala multi-agente. |
| `okami service install\|start\|stop\|status` / `okami logs -f` | Gateway como serviço do SO (launchd/systemd, sobe no boot) + log ao vivo. |
| `okami ps` / `okami process log\|kill\|signal\|wait\|clean` | Supervisão dos processos em background do agente, do terminal (kill real, sinais, PTY). |
| Telegram: menu `/` (setMyCommands) · reações 👀/👍/👎 (`gateway.reactions`) · botões inline de aprovação ✅/❌ | UX nativa do Telegram. |
| `okami cron add\|list\|remove\|run\|tick` | Agendamento. |
| `okami hooks` / `okami mcp` | Event hooks / servidores MCP. |
| `okami voice` / `okami transcribe` / `okami say` / `okami image` | Voz, STT, TTS, imagem. |
| `okami paperclip` / `okami heartbeat` / `okami acp` / `okami route` | Paperclip / ACP / roteamento. |
| `okami gate <dir>` | Verification gate de design. |
| `okami events` / `okami replay [trace]` | Timeline / replay de trajetória. |
| `okami rollback [N]` / `okami clean [--deep]` | Desfaz escritas / faxina de disco. |
| `okami tools` / `okami tune` / `okami version` | Tools do agente / auto-tune / versão. |

</details>

## Ferramentas do agente

26 tools declaradas com **categoria · tier · sensibilidade** (`okami tools` lista; um teste anti-drift
garante que toda tool tem metadata):

`respond` `read_file` `write_file` `edit_file` `list_dir` `find_files` · `run_shell` ·
`process_start/poll/wait/log/list/write/signal/kill` · `remember` `recall_memory` `remember_user` ·
`use_skill` · `spawn` (subagente) · `browse` · `generate_image` · `finish_setup` `task_complete`
`task_blocked` `need_input`.

A **policy por superfície** restringe o que cada canal pode (ex.: Telegram sem `run_shell`, grupo mais
restrito ainda); ações sensíveis sempre passam por go/no-go.

---

## Configuração

| Arquivo | Papel | Versionado? |
|---|---|---|
| `okami.yaml` | Config base (providers, memória, contracts, voz, learning). | ✅ sim |
| `okami.local.yaml` | Overrides locais (ex.: IP do LMStudio). | ❌ gitignored |
| `.env` / `$OKAMI_HOME/.env` (default `~/.okami/.env`) | **Segredos** (chaves de API, tokens). | ❌ gitignored |
| `okami.policy.yaml` | Postura de conformance autorada. | ✅ sim |

Cada provider tem `model` (string LiteLLM), `api_base` opcional, `api_key_env`/`api_key`, `transport`,
`tier`, `fallback` e `capability`. Segredo nunca vai no YAML — `okami config set OPENAI_API_KEY <v>`
roteia pro `.env`; `okami config set providers.x.api_key '${OPENAI_API_KEY}'` referencia por env.

> **Idioma (i18n):** a interface é **inglês por padrão**, com português disponível. Troque com
> `okami --lang pt`, `OKAMI_LANG=pt`, ou `lang: pt` no `okami.yaml`.

---

## Desenvolvimento & CI

```bash
make test           # uv run pytest -q   → suíte completa
make doctor
bash scripts/secret-scan.sh              # mesmo gate da CI (allowlist por `# pragma: allowlist secret`)
```

A CI (`.github/workflows/ci.yml`) é **gate de verdade** (sem `|| true`), com actions **pinadas por SHA**:

- **test** — `pytest` + **`okami policy check --json`** (conformance, com artefato) + build do wheel + smoke.
- **secret-scan** — script compartilhado (CI ≡ pytest); vetor fake de teste é marcado e auditável.
- **security** — **Ruff** · **Bandit (HIGH)** · **pip-audit** (CVE) · **Semgrep** (`p/security-audit`).

> CodeQL exige GitHub Advanced Security (indisponível em repo privado) → trocado por **Semgrep**, que
> roda 100% no runner e mostra os achados no log.

---

## Estrutura do projeto

```
okami/
  core/        harness, tools, sandbox, approval, redact, net_guard, file_safety,
               policy, lint, processes, ptyproc, egress_proxy, reload, tool_registry…
  llm/         providers, transports (codex/claude/minimax), usage, retry, errors
  memory/      sqlite-fts5 / holographic / honcho / layered, policy, citation, embeddings
  channels/    telegram, slack, discord, mattermost, paperclip (+ _http base)
  gateway/     AgentEndpoint, GroupEndpoint, sessions, checkpoints, approvals
  cli/         _app, _shared, commands/ (basics, task, chat, config, policy, auth, …)
  voice/       bridge, tts, stt          observability/  events, trajectory
  learning/    reflexão → memória → skill          skills/  lockfile + scan
agents/        perfis multi-agente (agents/<id>/agent.yaml + identidade)
skills/        skills versionadas (frontend-shadcn, tdd, …)
docs/          ARCHITECTURE · ROADMAP · STRUCTURE · PRODUCTION · COMPETITIVE_RESEARCH
deploy/        Dockerfile + docker-compose.yml      scripts/  install.sh/.ps1 · secret-scan.sh
tests/         suíte completa (pytest)
```

---

## Documentação

- 🌐 **Site**: [okamiagent.com](https://okamiagent.com) — visão geral do produto.
- 📚 **Docs**: [okamiagent.com/docs](https://okamiagent.com/docs) — guia completo de uso.
- 🎨 **Landing (fonte)**: [github.com/OkamiOps/Okami-Agent-LP](https://github.com/OkamiOps/Okami-Agent-LP).
- 📦 **Releases**: [github.com/OkamiOps/Okami-Agent/releases](https://github.com/OkamiOps/Okami-Agent/releases) · [CHANGELOG](CHANGELOG.md).

No repositório:
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — arquitetura completa (harness, skills, providers,
  memória, auto-melhoria, multi-agente, segurança).
- [docs/PRODUCTION.md](docs/PRODUCTION.md) — checklist de GA + como ligar a postura hostil.
- [docs/ROADMAP.md](docs/ROADMAP.md) · [docs/STRUCTURE.md](docs/STRUCTURE.md) ·
  [docs/COMPETITIVE_RESEARCH.md](docs/COMPETITIVE_RESEARCH.md) (Hermes × OpenClaw × Okami).

---

<div align="center">

**Okami Agent** — © OkamiOps · [okamiagent.com](https://okamiagent.com). Construído com
[uv](https://docs.astral.sh/uv/) · [LiteLLM](https://github.com/BerriAI/litellm) ·
[Textual](https://textual.textualize.io/).

*Custom Solutions · AI Innovation*

</div>
