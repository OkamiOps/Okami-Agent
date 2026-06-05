# Okami Agent — `v0.1.0-alpha` 🐺

**Primeiro alpha público.** Um agente de codificação confiável, multi-modelo e auto-evolutivo, que roda
no seu terminal e no Telegram — com **assinatura-only** (Claude/Codex via OAuth/CLI, nunca pay-as-you-go)
e postura de segurança fail-closed por padrão.

> ⚠️ **Alpha.** A superfície de comandos e config pode mudar entre alphas. Não recomendado p/ produção
> sem isolamento (rode `okami policy check --strict` antes de expor publicamente). Feedback é muito bem-vindo.

🌐 Site: **https://okamiagent.com** · 📚 Docs: **https://okamiagent.com/docs**

---

## ✨ Highlights

- **Harness que não trava e não finge concluir** — action-or-terminate, anti-loop, anti-alucinação,
  *exit criteria* verificados, escalonamento p/ modelo mais forte sob falha, e *failover* entre providers.
- **Paridade multi-modelo (forte / fraco / local)** — Codex e Claude por **assinatura** (OAuth/CLI),
  LMStudio local, e MiniMax/MiMo por Token Plan. Protocolo de ação único → o modelo fraco também executa.
- **Memória plugável** — SQLite FTS5 + embeddings, memória **global** (`~/.okami`) que vale em qualquer
  projeto, consolidação/TTL, citação de origem e métricas de recuperação.
- **Skills + Contracts + Verification Gates** — adesão obrigatória a design system; toda skill passa por
  *scan* de segurança antes de instalar (HIGH/CRITICAL bloqueado).
- **TUI de tela cheia** na identidade da marca — separação clara de turno, emoji por evento (🧠 pensar ·
  🛠️ tool), **rodapé de custo por resposta** (ctx · tokens · tempo) e **copiar texto** (seleção + `^C`).
- **Gateway multi-agente no Telegram** — 1 bot por agente, cada um respondendo do seu próprio workspace;
  deny-by-default, aprovação go/no-go, reactions, voz (STT/TTS), tópicos/sessões.
- **Process manager Hermes-grade** — processos OS reais (kill imediato `os.killpg`/`docker kill`), PTY/stdin,
  watch patterns, paginação de log, recuperação de órfão; supervisão por CLI (`okami ps`) e chat (`/process`).
- **Postura de segurança fail-closed** — assinatura-only, segredos só no `.env`, sandbox por perfil
  (local/docker), Telegram deny-by-default, SOUL nunca auto-evolui, SSRF guard, audit log redigido.
- **Conformance & release-readiness** — `okami.policy.yaml` versionado + `okami policy check --strict`
  (gate de GA) + `okami readiness` (CI green · strict green · strict HEAD match).

## 🔧 Changes (o que vem no alpha)

- CLI completa: `okami setup · config · status · doctor · chat · gateway · providers · login · policy ·
  readiness · ps/process · clean · events · replay · auth · memory · skills`.
- `okami readiness` — prontidão de release com frescura automática (stale quando o HEAD anda após o
  strict verde); `--refresh` dispara o gate, `--json` p/ automação.
- Chat: régua de turno sóbria (`▌ nome · hora`), emoji por evento, rodapé `· ctx N% · X tok · Ys`,
  seleção + `^C` p/ copiar.
- Unificação `/agents` · `/background` · `/process`: visão única (fila + tarefas + processos OS), `/process
  log` paginado, `/background --process` p/ promover servidor/build a processo OS (kill real, fail-closed).
- Process manager exposto fora do gateway (`okami ps`, `okami process list|log|kill|signal|wait|clean`).
- Memória: schema aditivo, layer global, consolidação/TTL, métricas (precision@k/recall/MRR), CRUD com
  namespaces (`global:`/`project:`).

## 🐛 Fixes (endurecimento no run-up ao alpha)

- **MiniMax/MiMo corrigidos pela doc oficial** — MiniMax usa **Subscription Key** (Bearer, OpenAI-compat),
  não OAuth device-flow (causa do 401); MiMo aponta p/ o endpoint regional `token-plan-*.xiaomimimo.com`
  (causa do parse-JSON). Agora suportados, fora do "experimental".
- **Heurística de exposição unificada** entre lint e policy — um bloco `gateway:` só com `reactions` não
  é mais falsamente "exposto"; `strict` passa limpo num checkout de produção.
- `config check --json`, `okami service`/`logs`, escape de `systemd` argv, `.okami` fora do CWD em
  skills/voice, providers opcionais em âmbar (sem alarme de 401).

## ✅ Release verification

- **880 testes** passando (`uv run pytest`).
- **Lint**: `ruff check okami tests` limpo. **Segurança**: `bandit -c pyproject.toml -r okami` limpo.
- **Conformance estrita**: `okami policy check --strict` **conforme** na postura versionada (0 falhas);
  o gate `production-conformance` (enforce=true) roda **bloqueante** no commit desta tag.
- **Supply-chain**: wheel + sdist com **SBOM (CycloneDX)** e **build provenance** (attestation sigstore),
  gerados por `release.yml` (actions pinadas por SHA).
- Reprodução local:
  ```bash
  uv sync --frozen
  uv run pytest -q
  uv run ruff check okami tests
  uv run bandit -c pyproject.toml -r okami -q
  uv run okami policy check --strict
  ```

## 📦 Assets

- `okami_agent-0.1.0a0-py3-none-any.whl` — wheel
- `okami_agent-0.1.0a0.tar.gz` — sdist
- `sbom.cdx.json` — SBOM CycloneDX
- *build provenance attestation* (sigstore) anexada à wheel

## 🚀 Instalação

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/OkamiOps/Okami-Agent/main/scripts/install.sh | bash
# Windows (PowerShell)
irm https://raw.githubusercontent.com/OkamiOps/Okami-Agent/main/scripts/install.ps1 | iex

okami setup     # configura em 2-3 cliques
okami chat      # conversa no terminal
```

## 🔗 Links

- 🌐 Landing: https://okamiagent.com
- 📚 Documentação: https://okamiagent.com/docs
- 💻 Agente (este repo): https://github.com/OkamiOps/Okami-Agent
- 🎨 Landing page (fonte): https://github.com/OkamiOps/Okami-Agent-LP
