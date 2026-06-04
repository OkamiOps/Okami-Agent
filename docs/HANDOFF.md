# HANDOFF — estado do projeto e migração de máquina

Snapshot pra continuar o desenvolvimento em outra máquina (ex.: do Windows pro MacBook) sem perder
contexto. Atualizado em 2026-06-04.

## O que é o Okami
Agente de codificação **confiável** (não trava, não inventa), multi-modelo (paridade entre LLMs forte/
fraco/local), multi-agente, evolutivo (persona/skills/memória) e com aderência a design system.
Tagline da marca: **"IA com soberania para PMEs"** (org GitHub: **OkamiOps**).

## Estado atual (o que já funciona)
- **Core/harness** ReAct: a cada turno o agente FALA (`respond`) ou AGE (tool). Conversa de verdade
  (não é chatbot de tarefa) + backstop anti-preguiça p/ modelo fraco. Verificado ao vivo no qwen-4b.
- **Providers**: descoberta de modelos AO VIVO (`/v1/models`) + catálogo p/ OAuth (codex/claude).
  `okami provider add/list/remove/default/login/models`.
- **Setup** estilo Hermes/OpenClaw: fork **Rápido/Completo**, **auto-detecção** (servidor local no ar,
  OAuth logado, chave no ambiente), menus de seta (questionary), seções (`okami setup <seção>`:
  provider/memory/agent/channel/voice/approvals/learning/persona).
- **`okami config`** (show/get/set/unset/path/edit/check — segredo→.env, resto→okami.local.yaml) e
  **`okami status`** (visão resolvida).
- **`okami chat`**: TUI na identidade da marca (logo, painel tools/skills, status bar), sessão
  persistente, slash commands, persona evolutiva.
- **Gateway** Telegram em **background** (`okami gateway` / `--status` / `--stop` / `-f`).
- Memória (sqlite-fts5 / holographic / honcho), skills + scan de segurança, MCP, cron+hooks,
  taste, checkpoints/rollback, voz (Whisper/EdgeTTS), image-gen, browser, ACP. **250 testes passam.**
- **Instalação** via `uv` (1 comando; ver README). Identidade visual aplicada (design-system).

## Próximo passo
**Slack** (adapter de canal, mesma interface `Channel` do Telegram). Depois, backlog do research
Hermes/OpenClaw: `fallback_providers` no setup, model aliases, modelos auxiliares baratos por tarefa
(vision/compaction), `config migrate`, flags `--quick`/`--portal`.

## Restrições que NÃO podem se perder
- **Claude/Codex: usar SEMPRE a ASSINATURA, NUNCA pay-as-you-go** (codex = OAuth device flow lendo
  `~/.codex/auth.json`; claude = CLI oficial `claude`).
- **MiMo**: chave só no `.env` (`MIMO_API_KEY`), nunca commitada.
- **Skills**: validar (scan) antes de instalar; HIGH/CRITICAL bloqueado.
- **LMStudio**: usar SÓ o modelo já carregado (não subir outro — estoura a RAM). Servidor do dev em
  `http://192.168.3.24:4480/v1` (rede local — acessível do Mac se estiver na mesma rede).
- **SOUL/VOICE/PERSONA/.env/segredos**: go/no-go; SOUL nunca auto-evolui.

## Dev no MacBook (3 passos)
```bash
git clone <repo OkamiOps>        # ou clone do bundle (ver abaixo)
cd Okami-Agent
uv sync                          # cria o venv + deps (uv baixa o Python sozinho)
uv run okami doctor              # confere
uv run pytest -q                 # 250 testes
```
Pra usar como comando global: `uv tool install -e .` (editável) → `okami setup`.

## O que NÃO vai no git (recriar/copiar no Mac)
- **`.env`** (segredos — gitignored): recrie com as chaves que usar (ex.: `MIMO_API_KEY=...`).
- **`~/.codex/auth.json`** (login do codex): rode `okami login codex` no Mac (ou copie o arquivo).
- **CLI `claude`**: instale e `claude login` se for usar o provider claude.
- **`agents/`** runtime (gitignored): recriado por `okami setup` (o exemplo fica em
  `examples/company/agents/`, esse sim versionado).
- **Memória do Claude Code** (`~/.claude/.../memory/`): é por-máquina; este HANDOFF + o histórico do
  git são a fonte de verdade portátil.

## Levar o código pra fora desta máquina
1. **Push pra OkamiOps** (pela sua conta com acesso à org):
   `git remote add origin https://github.com/OkamiOps/Okami-Agent.git && git push -u origin main`
   (a conta `mvssantos` do `gh` local NÃO é membro da OkamiOps — use a outra).
2. **Ou bundle** (1 arquivo com TODO o histórico, sem depender de GitHub):
   já gerado em `~/okami-agent.bundle`. No Mac: `git clone okami-agent.bundle Okami-Agent`.
