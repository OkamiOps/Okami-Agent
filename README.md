# Okami Agent

> **IA com soberania para PMEs.** Agente de codificação confiável, com paridade de capacidade
> entre LLMs, auto-melhoria (skills/persona/memória) e aderência obrigatória a design systems.

Veja [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) e [docs/ROADMAP.md](docs/ROADMAP.md).

## Preview

O `okami chat` abre um TUI na identidade da marca (Onyx + Heat Orange / Volt Cyan):

![okami chat](docs/chat-welcome.png)

Toda a configuração é por menu de seta (`okami setup`, `okami provider add`):

![menus](docs/menu-demo.gif)

## Status: Fase 0 (fundação)

Config + providers via LiteLLM + CLI `okami run`. Providers: **LMStudio** (local, já funciona),
**Codex/GPT**, **Claude**, **MiniMax**, **MiMo** (aguardando chaves/ids).

## Setup

Roda em **Linux, macOS, Windows e Docker** (código 100% `pathlib`/stdlib; portabilidade
verificada com a suíte de testes rodando em container Linux).

### Instalação em 1 comando

**Linux / macOS / WSL** (detecta Python 3.11+, cria venv e o comando `okami`):
```bash
curl -fsSL https://raw.githubusercontent.com/okami-agent/okami-agent/main/scripts/install.sh | bash
# ou, dentro do repo já clonado:  ./scripts/install.sh
```

**Windows (PowerShell)** — cria o venv num caminho curto (`C:\okv`) p/ evitar o limite de 260 chars do OneDrive:
```powershell
irm https://raw.githubusercontent.com/okami-agent/okami-agent/main/scripts/install.ps1 | iex
# ou, dentro do repo:  .\scripts\install.ps1
```

Depois, **configure e converse** (sem editar YAML na mão):
```bash
okami setup     # wizard: provider + login + memória + identidade + canal
okami chat      # conversa no terminal (sessão persiste; /help p/ comandos)
```

### Manual (dev)

<details><summary>Linux/macOS</summary>

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # atalhos: make install | make test | make doctor
```
</details>

<details><summary>Windows</summary>

```powershell
python -m venv C:\okv          # caminho curto evita o limite de 260 chars no OneDrive
C:\okv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env
```
> Alternativas ao caminho curto: habilitar *Long Paths* no Windows, mover o repo p/
> `C:\dev\Okami-Agent`, **ou usar Docker** (abaixo) — que ignora o problema.
</details>

### Docker (qualquer SO)
```bash
docker compose build
docker compose run --rm okami doctor
docker compose run --rm okami run "diga oi"
docker compose run --rm okami task "crie hello.txt" -e file_exists:hello.txt
# rodar os testes na imagem Linux:
docker run --rm --entrypoint python okami-agent -m pytest -q
```
> Para um LMStudio na máquina host, aponte `api_base` para `http://host.docker.internal:PORT/v1`.

## Uso

```powershell
okami                             # visão geral dos comandos (= okami help)
okami setup                       # assistente de configuração (menus de seta ↑↓)
okami setup provider              # pula direto pra uma seção (provider|memory|identity|channel)
okami provider add                # adiciona um modelo do catálogo (Codex, OpenAI, Ollama…) sem editar YAML
okami chat                        # conversa no terminal (TUI com sessão persistente)
okami chat "diga oi"              # uma pergunta e sai (scripts/pipe)
okami chat -a cto                 # conversa COMO um agente (agents/cto)
okami doctor                      # diagnostica config, chaves e conectividade
okami run "explique recursão" -p claude   # ida-e-volta crua (sem sessão/harness)
okami gateway                     # sobe os bots de Telegram (1 por agente)
```

Toda configuração é por **menu de seta** (↑↓ Enter); sem terminal interativo, cai num menu numerado.
Chaves de API vão pro `.env` (nunca pro `okami.yaml`, que é versionado).
Dentro do `okami chat`: `/help` `/new` `/status` `/stop` `/yolo` `/feedback <estilo>` `/persona <preset>` `/undo`.

> Sem instalar o entry point, dá para rodar com `python -m okami.cli ...`.

## Configuração

Providers em [`okami.yaml`](okami.yaml); chaves em `.env`. Cada provider tem `model`
(string LiteLLM), `api_base` opcional, `api_key_env`/`api_key` e `tier`
(`strong`/`weak`/`local`) — este último prepara o capability profile adaptativo (§3.5).
