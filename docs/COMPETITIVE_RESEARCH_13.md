# Pesquisa Competitiva #13 — Hermes × Okami COM SCORE de paridade (pós-#12)

**Data:** 2026-06-16
**Alvo:** `NousResearch/hermes-agent` @ `5bfed0fe0`
**Contexto:** o #12 implementou TODOS os candidatos (inclusive os fora-de-escopo: Gemini/Bedrock
nativos, Tirith, lazy_deps, Blueprints, Kanban swarm, plugins, browser supervisor, web/gui). Esta
rodada **pontua** a paridade por área e lista o resíduo honesto.

---

## 🏆 Score de paridade por área (0-100)

> Metodologia: paridade FUNCIONAL (o Okami faz o que o Hermes faz naquela área?), ponderada por peso da
> área p/ um agente de código dono-único assinatura-only. Cada nota tem a justificativa do que falta p/ 100.

| Área | Score | O que ainda separa de 100 |
|---|---:|---|
| Runtime loop / error-recovery | **98** | refactors organizacionais (TurnFinalizer/TurnRetryState) feitos; nada funcional falta |
| Memória / learning / curator | **98** | paridade efetiva; honcho identity-tree é multi-usuário (N/A dono-único) |
| Prompt / context engineering | **97** | edit-format steering + scan de contexto + wcwidth ok; faltam nuances de cache cosméticas |
| Segurança / supply-chain | **95** | threat-lib + exfil-MCP + OSV + ssl_guard + **Tirith** ok; Tirith SEM auto-install (download+cosign não-portado, é graceful) |
| MCP | **97** | OAuth-PKCE + exfil-scan + OSV-block; falta refresh de token interativo automático no hot-path |
| Multimodal | **95** | MIME-sniff + auto-extração + álbum; vídeo nativo é multi-vendor (N/A Claude-only) |
| Provider / multi-vendor | **90** | **Gemini + Bedrock nativos** traduzidos e roteados (prontidão), mas NÃO battle-tested em rede real; litellm cobre o caminho prático hoje |
| Gateway / UX / canais | **96** | heartbeat + display-tiers + álbum + panic-hook + silêncio; falta polish de sticker-cache |
| CLI / operações | **96** | completion + logs-filtro + deps + blueprint/swarm/plugins/gui; sem polish menor |
| Skills | **97** | bundles + config + gating + tiers; paridade efetiva |
| Automação (cron/blueprints/swarm) | **95** | Blueprints + Kanban swarm (plan+blackboard); a EXECUÇÃO do swarm reusa spawn (sem orquestrador dedicado) |
| Extensibilidade (plugins) | **90** | descoberta (pasta + entry-point pip) ok; execução profunda de middleware/hook de plugin é parcial |
| Distribuição (web/desktop) | **72** | dashboard web LEVE (stdlib, zero-dep) + `okami gui` (abre no browser); SEM SPA React/Vite nem app Electron (decisão consciente: zero-dep > paridade pixel) |

### **Score global ponderado: ~94 / 100**

Ponderação (peso): runtime/memória/prompt/segurança/MCP/skills pesam mais (núcleo de um coding agent);
distribuição (web/desktop) pesa menos p/ um agente dono-único de CLI/Telegram. Média ponderada ≈ **94**.

---

## ✅ O que o #12 fechou (antes era gap)

- **Multi-vendor**: `gemini_native` + `bedrock_native` (tradução OpenAI↔nativo, dispatch, lazy-SDK) —
  pronto p/ cancelar assinatura e trocar de vendor no futuro.
- **Tirith**: scan de conteúdo pré-exec (homograph/pipe-to-interpreter) no `run_shell` — graceful sem o binário.
- **lazy_deps**: install de backend opcional em runtime (allowlist, venv-scoped, opt-out) — `okami deps`.
- **Blueprints**: automação parametrizada com slots → cron — `okami blueprint`.
- **Kanban swarm**: workers→verificador→sintetizador + blackboard — `okami swarm`.
- **Plugins**: descoberta pasta + entry-point pip — `okami plugins`.
- **Browser supervisor**: listener CDP (diálogo/frame) + política de diálogo.
- **Web/gui**: dashboard leve + `okami gui`.

---

## ⚠️ Resíduo honesto (o que NÃO está 100%)

1. **Provider nativo não battle-tested (90):** a tradução Gemini/Bedrock é testada por unidade (sem
   rede). A 1ª chamada real pode revelar ajuste de schema de tool/streaming. É *prontidão*, não uso ativo.
2. **Tirith sem auto-install (95 → seg):** o download de release + verificação cosign do Hermes NÃO foi
   portado (pesado/arriscado às cegas). O dono instala o binário; sem ele, é inerte (o approval-regex
   segue valendo).
3. **Web/desktop leve (72):** dashboard é stdlib server-rendered (não SPA React) e `gui` abre o browser
   (não é app Electron empacotado). Decisão consciente pela constraint "zero-dep". Paridade funcional de
   status/visualização, não de chrome nativo.
4. **Plugins — execução de middleware parcial (90):** a DESCOBERTA está completa; rodar hooks de plugin
   no ciclo de vida reusa o HookManager existente, mas o `PluginContext` trust-gated + middleware de
   interceptação do Hermes não foi portado por inteiro.
5. **Swarm — orquestrador (95):** o plano + blackboard estão prontos; a execução paralela reusa
   `spawn`/`run_task` (não há um orquestrador-de-swarm dedicado persistindo no kanban como o Hermes).

---

## Veredito

Com o #12, o Okami passa de "paridade profunda" p/ **paridade quase-total (~94/100)**, incluindo a
prontidão multi-vendor que o dono pediu. O resíduo é (a) coisas que só se provam em uso real
(provider nativo), (b) escolhas conscientes de zero-dep (web/desktop leve) e (c) profundidade extra
opcional (middleware de plugin, orquestrador de swarm, auto-install do Tirith). Nenhum é buraco de
capacidade central — são acabamento e robustez-em-produção.

> Próximo passo do goal: subir o release **v0.9-alpha** + melhorar o README + ajustar as release notes.
