# Estrutura do Okami

Há **duas** estruturas: o **pacote** (o código, em `okami/`) e o **runtime** (o que aparece em disco
quando você usa o agente — agentes, workspaces, estado). Elas são separadas de propósito: o código é
o motor; os agentes/workspaces são os *dados* de cada instalação (não vão pro git).

## 0. Raiz do repositório  ✅ organizada

```
Okami-Agent/
├── README.md · pyproject.toml · Makefile        # projeto (hatchling; `okami` = okami.cli:app)
├── okami.yaml · .env.example                     # config (template) + segredos de exemplo
├── .gitignore · .dockerignore                    # ignora runtime (agents/ workspaces/ .okami/ inbox/)
├── okami/                                         # 📦 o PACOTE (ver §1)
├── tests/                                         # 223 testes (pytest)
├── docs/         ARCHITECTURE · ROADMAP · STRUCTURE
├── examples/     company/   ← empresa multi-agente de exemplo (cto/ui/backend)
├── skills/       skills empacotadas (humanizer, frontend-shadcn, ...) — escaneadas
├── scripts/      install.sh · install.ps1  ← instaladores 1-comando (Linux/macOS/Windows)
└── deploy/       Dockerfile · docker-compose.yml  ← tudo de container junto
```

**Onboarding** (estilo Hermes): `scripts/install.sh` (ou `.ps1` no Windows) detecta Python 3.11+, cria o
venv e o comando `okami` global. Depois `okami setup` (wizard: provider → login → memória → identidade →
canal) e `okami chat` (REPL no terminal, sem precisar de Telegram). Nada de editar YAML/JSON na mão.

Build em container: `docker build -f deploy/Dockerfile -t okami-agent .` (ou
`docker compose -f deploy/docker-compose.yml run --rm okami doctor`). O `.dockerignore` fica na raiz
porque é o **contexto** do build.

## 1. Pacote (código) — `okami/`  ✅ reorganizado por domínio (Hermes-style)

Antes eram 23 módulos soltos; agora estão agrupados por responsabilidade (como o **Hermes**, que é
Python e usa um pacote único com sub-módulos — `agent/tools/gateway/providers/cron/acp_adapter/...`).
O **OpenClaw** usa monorepo multi-pacote, mas só porque é TypeScript/pnpm (não se aplica a Python).

```
okami/
├── cli.py · config.py · runner.py · contracts.py    # entrypoint + base + orquestração
├── core/          harness · tools · approval                 ❤️ o motor (máquina de estados §3)
├── llm/           providers · transports · oauth · imagegen  acesso a modelos + mídia (§3.5/§16)
├── agents/        __init__(load_agents,Router) · group       MULTI-AGENTE + grupo (§10)
├── gateway/       __init__(run_gateway) · sessions · checkpoints   control plane/chat (§13)
├── channels/      base · telegram · paperclip · (slack)      adapters de canal
├── learning/      __init__(reflect,auto-skill) · taste · persona   auto-aprimoramento (§7/§8/§9)
├── automation/    scheduler · hooks                          cron + event hooks (§11)
├── skills/        __init__(load_skills) · skill_security     skills + validação (§4.2)
├── integrations/  mcp · browser · references · acp           MCP, browser, @refs, IDE/ACP (§12/§13)
├── memory/        sqlite_fts5 · holographic · honcho · layered · compaction · files
└── voice/         stt · tts
```

**Truque sem quebrar imports:** o módulo "dominante" de um pacote virou o `__init__.py` — por isso
`from okami.agents import load_agents`, `from okami.gateway import run_gateway`, `from okami.skills
import load_skills` e `from okami.learning import ...` continuam funcionando. Os demais viraram
sub-módulos (`okami.agents.group`, `okami.llm.providers`, `okami.learning.taste`, etc.).
Imports internos são **absolutos** (`from okami.X import …`) → robustos a futuros moves.

## 2. Runtime (disco) — onde MULTI-AGENTE vive

Multi-agente **não** mora no pacote — cada agente é uma PASTA com config + identidade + memória
próprias. É isso que você não estava vendo. Veja `examples/company/`:

```
seu-projeto/
├── okami.yaml                 # config global: providers (CREDENCIAIS), groups, agents.default
├── agents/                    # 1 pasta por agente (criada por `okami agent new <id>`)
│   ├── cto/
│   │   ├── agent.yaml         # role, default_provider (SEU modelo), channels.telegram.token
│   │   ├── SOUL.md · VOICE.md · PERSONA.md   # identidade (evolui sozinha §8)
│   │   └── .okami/            # memória + sessões + taste + checkpoints DESTE agente
│   │       ├── memory.db · taste.json · persona_signals.json
│   │       ├── sessions/sessions.json + <chat>.jsonl   (transcript append-only)
│   │       └── checkpoints/journal.jsonl
│   ├── ui/        (idem — outro modelo, outra identidade, outra memória)
│   └── backend/
├── workspaces/                # áreas de trabalho (código que o agente edita)
├── skills/                    # skills instaladas (SKILL.md), escaneadas
└── .okami/                    # estado do agente default (cron.json, sessions, tuning.json)
```

**Pontos-chave:**
- **Credenciais globais, modelo por agente:** `providers:` (chaves/OAuth) ficam no `okami.yaml`
  global; cada `agent.yaml` só escolhe `default_provider` → CTO no Codex, UI no MiniMax, etc.
- **Isolamento total:** cada agente tem memória/sessões/identidade/taste/checkpoints próprios em
  `agents/<id>/.okami/`. Rodam separados, não compartilham sessão.
- **Grupo:** `groups:` no `okami.yaml` junta agentes numa "reunião" (moderador decide quem fala).

Rode o exemplo: `cd examples/company && okami agent list && okami room "CTO, e o frontend?"`.
