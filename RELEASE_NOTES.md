# Okami Agent — `v0.14.0-beta` "Instalação Limpa" 🐺

**1 commit · suíte 3.590 → 3.613 testes** · lançada **2026-07-08**.

> ⚠️ **Beta.** A superfície de comandos e config ainda pode mudar até a GA. Recomendado para uso real
> (inclusive em VPS 24/7) — mas rode `okami policy check --strict` antes de expor publicamente. Feedback
> é muito bem-vindo. Ver o [CHANGELOG](CHANGELOG.md) completo.

🌐 Site: **https://okamiagent.com** · 📚 Docs: **https://okamiagent.com/docs**

---

## A história desta release

As últimas releases fecharam gaps de capacidade — imagem, hooks, browser. Esta fecha uma lacuna
diferente, mais operacional: **instalações existentes não tinham um caminho de atualização claro**. O
único jeito de subir de versão era rerodar o instalador do zero, um processo não documentado e que não
confirmava o que de fato mudou. Isso deixava instalações indo ficando presas em versões velhas com o
tempo.

Esta release ataca essa lacuna de ponta a ponta: um comando `okami upgrade` dedicado que sabe identificar
o tipo de instalação e aplicar o caminho de atualização certo, instaladores que verificam o próprio
resultado, e um Docker que finalmente persiste o estado do agente entre reinícios do container. Ao lado
disso, o menu de configuração ganha um jeito interativo de trocar de provider/modelo, e o terminal mostra
mais informação em tempo real (timing por tool-call, tokens/custo ao vivo).

## ✨ Highlights

- **`okami upgrade`** (comando novo) — detecta o tipo de instalação (managed/dev/Docker/ausente) e aplica
  o caminho certo: `git pull --ff-only` + `uv tool install --force`, reportando versão antiga → nova.
  Flags `--check` (só verifica) e `--yes` (sem confirmação).
- **Instaladores endurecidos** — `install.sh`/`install.ps1` verificam o binário recém-instalado e
  reportam versão antiga → nova (antes, atualizavam em silêncio); `install.ps1` trata long-paths do
  Windows.
- **Docker com estado persistente** — `docker-compose.yml` guarda `OKAMI_HOME` (skills, agentes, sessões,
  `.env`, credenciais, cofre) num volume nomeado — antes, tudo isso ia para o home efêmero do container e
  se perdia a cada recriação. `Dockerfile` reconstruído multi-stage, `uv sync --frozen`, não-root,
  `HEALTHCHECK`.
- **`okami config` ganha picker de provider/modelo** — troca interativa direto no menu (aliases
  `sonnet`/`opus`/`fast`/`smart`), mais uma visão de providers configurados; persiste em
  `okami.local.yaml`.
- **Terminal mais informativo** — tool cards mostram tempo de execução; status bar (REPL e TUI) mostra
  tokens/custo ao vivo durante a sessão; toolbar do REPL mostra a tool em execução em vez de um
  "pensando" genérico.

## 📦 Instalação & Upgrade

- `okami upgrade`: detecta 4 cenários — instalação **managed** (checkout git gerenciado pelo instalador),
  **clone de desenvolvimento**, **Docker**, ou **ausente** — e só age no caminho aplicável. Para managed:
  `git pull --ff-only` (nunca reescreve histórico local) seguido de `uv tool install --force`, com
  relatório final de versão antiga → nova. `--check` reporta se há atualização disponível sem aplicar
  nada; `--yes` pula a confirmação interativa (uso em automação).
- `install.sh`/`install.ps1`: depois de instalar, o script agora **verifica o binário final** e imprime a
  transição de versão — antes o resultado era mudo, sem confirmação de que a atualização realmente
  aconteceu.
- `install.ps1`: trata **long-paths do Windows** — checa a chave de registro relevante e habilita
  `core.longpaths` no git quando necessário, evitando falhas silenciosas em instalações com caminho
  profundo.

## 🐳 Docker

- `deploy/docker-compose.yml`: `OKAMI_HOME` passa a viver num **volume nomeado** (`okami-data`) —
  skills, agentes, sessões, `.env`, credenciais e o cofre de segredo cifrado agora sobrevivem a
  recriações do container. Antes, esse estado ia para o home efêmero do container e desaparecia a cada
  `docker compose up` novo.
- `deploy/Dockerfile`: reescrito **multi-stage**, com `uv sync --frozen` (build reprodutível a partir do
  lockfile), usuário não-root, `HEALTHCHECK` configurado e imagens base pinadas.

## ⚙️ Config — troca de provider/modelo pelo menu

- `okami config` ganha uma opção de **picker interativo de provider/modelo**, reaproveitando o mesmo
  fluxo do comando `okami model` (aliases `sonnet`/`opus`/`fast`/`smart`), e uma tela de **providers
  configurados**. Antes o menu não oferecia caminho para trocar de provider ou modelo — só edição manual
  de config. A escolha persiste em `okami.local.yaml`.

## 🖥️ Terminal — mais visibilidade em tempo real

- Cartões de tool-call finalizados mostram **quanto tempo a chamada levou**.
- A barra de status — no REPL de linha e no TUI de tela cheia — mostra **tokens e custo ao vivo** durante
  a sessão, não só no resumo final.
- A toolbar do REPL mostra qual **tool está em execução** no momento, em vez de uma linha genérica de
  "pensando".

## ⚠️ Beta — caveats e trabalho em andamento

- Comandos e chaves de config ainda podem mudar até a GA (sem promessa de estabilidade de superfície).
- Recomendado pra uso real (VPS 24/7 inclusive), mas rode `okami policy check --strict` antes de expor
  publicamente e acompanhe o [CHANGELOG](CHANGELOG.md) a cada atualização.
- **Em andamento, fora desta release** — correções de conexão com provider seguem em paralelo: crash de
  streaming do Claude e resolução do cofre de credenciais do Codex. Previstas para uma release de
  acompanhamento.

## ✅ Release verification

- **3.613 testes** passando (`uv run pytest -q`), subindo de 3.590.
- Reprodução local:
  ```bash
  uv sync --frozen
  uv run pytest -q
  uv run ruff check okami tests
  uv run bandit -c pyproject.toml -r okami -q
  uv run okami policy check --strict
  ```

## 🚀 Instalação / upgrade

```bash
# instalação nova (macOS / Linux)
curl -fsSL https://raw.githubusercontent.com/OkamiOps/Okami-Agent/main/scripts/install.sh | bash
# Windows (PowerShell)
irm https://raw.githubusercontent.com/OkamiOps/Okami-Agent/main/scripts/install.ps1 | iex

# upgrade de instalação existente
okami upgrade            # detecta o tipo de instalação e atualiza no lugar
okami upgrade --check    # só verifica se há atualização, sem aplicar

okami setup     # configura em 2-3 cliques
okami doctor    # confirma que a versão instalada bate com o pyproject (sem version-drift)
okami chat      # conversa no terminal
```

Nenhuma dependência Python nova nesta release — a mudança é toda em instalação/Docker/CLI. `okami.yaml`/
`okami.local.yaml` existentes continuam válidos.

## 📄 License

**MIT** ([LICENSE](https://github.com/OkamiOps/Okami-Agent/blob/main/LICENSE)) © 2026 OkamiOps — use it,
fork it, ship it commercially, no strings attached and no warranty.

## 🔗 Links

- 🌐 Landing: https://okamiagent.com
- 📚 Documentação: https://okamiagent.com/docs
- 💻 Agente (este repo): https://github.com/OkamiOps/Okami-Agent
- 🎨 Landing page (fonte): https://github.com/OkamiOps/Okami-Agent-LP
- 📋 Changelog completo: [CHANGELOG.md](CHANGELOG.md)
