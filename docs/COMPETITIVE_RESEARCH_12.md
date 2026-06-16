# Pesquisa Competitiva #12 — comparativo Hermes × Okami pós-#11

**Data:** 2026-06-16
**Alvo:** `NousResearch/hermes-agent` @ `5bfed0fe0` (2026-06-15)
**Método:** 3 subagentes Explore paralelos (runtime/provider/learning · tools/segurança/MCP ·
gateway/TUI/CLI/apps), cada um grepando o código REAL do Okami pós-#11 p/ provar ausência.
**Contexto:** o #11 acabou de implementar ~35 features (Tiers 1-5 + borderline). Esta rodada caça o que
SOBROU.

> **Veredito:** **paridade profunda confirmada de novo.** O núcleo (runtime loop, memória, learning,
> error-handling, prompt-cache, compaction, segurança, MCP, multimodal, UX de plataforma) está em par.
> O que resta são features de **provider multi-vendor** (fora de escopo: assinatura-única Claude-only) e
> **distribuição/UX pesada** (web/desktop — dep pesada), mais **4 candidatos genuínos in-scope**.

---

## ✅ Confirmado em paridade (não re-reportar)

`prompt_caching` (5m/1h TTL), `ClassifiedError`+failover, compaction com aux model, curator de skills,
`stream_diag`, `image_refs` (extração de imagem do texto), strip de `<think>`, insights cross-sessão,
process registry (process_start/poll/log/wait/kill/list), checkpoints, goals+subgoals, ACP+edit-approval,
cron (output histórico/next_run/script), suggestions, mirror, clarify, e **tudo do #11** (threat_patterns,
mcp_security, osv_check, ssl_guard, mcp_oauth, schema_sanitizer, json_repair, display_config, heartbeat,
panic_hook, silence, photo-burst, completion, logs-filter, skill bundles/config/gating).

---

## ⛔ Fora de escopo (constraints duras)

| Feature | Hermes | Por que fora |
|---|---|---|
| **Bedrock native adapter** | `agent/bedrock_adapter.py` (1342 ln) — boto3 Converse API, IAM | Multi-vendor + AWS enterprise. Okami é **assinatura-única Claude**; litellm já cobre o caminho compat. |
| **Gemini native adapter** | `agent/gemini_native_adapter.py` (1001 ln) — REST nativo + tier probe | Multi-vendor (Gemini). Okami é **Claude-only**. |
| **Web dashboard** | `web/` React 19+Vite + `web_server.py` (FastAPI :9119) | Cadeia de dep pesada (React/Vite/FastAPI/uvicorn). Constraint "sem dep pesada". |
| **Desktop app (Electron)** | `apps/desktop/` + `gui.py` | Electron+Node. Idem dep pesada; CLI/TUI já cobrem. |
| **Tirith binary scanner** | `tools/tirith_security.py` (822 ln) — binário externo p/ scan de homograph/pipe | Binário externo + cosign. Okami prefere zero-dep; `threat_patterns`+`approval` cobrem o regex-level. |
| **lazy_deps (install em runtime)** | `tools/lazy_deps.py` (648 ln) — instala extra no 1º uso | Mudança arquitetural (install em runtime) contra o modelo `check()`-poda do Okami (mais simples/seguro). |

---

## 🎯 Candidatos GENUÍNOS in-scope (o que dá p/ implementar)

Ordenados por ROI/aderência. **Nenhum é buraco crítico** — são features de produtividade/robustez.

### 1. Blueprints — automação parametrizada multi-superfície  **[M · in-scope · alto ROI]**
- **Hermes:** `cron/blueprint_catalog.py` + `hermes_cli/blueprint_cmd.py`. Um blueprint = automação
  templada (schedule + prompt) com SLOTS tipados (time/enum/text/weekdays). Fonte única renderiza no
  dashboard (form), CLI (`/blueprint nome slot=val`), TUI (o agente preenche conversando) e docs. Não
  cria 2º motor de job — valida/preenche os slots e chama o `create_job()` padrão.
- **Okami:** `grep blueprint` → zero. Criar job é só CLI ou mediado pelo agente; sem template parametrizado.
- **Por quê:** dono-único ganha muito com automação de-1-toque ("briefing diário", "vigia e-mail
  importante", "sincroniza repos") — tira a fricção de "eu poderia agendar" p/ feito. Aproveita o cron
  que já existe.

### 2. Kanban swarm v1 — orquestração paralela de especialistas  **[S/M · in-scope]**
- **Hermes:** `hermes_cli/kanban_swarm.py`. Topologia fina SOBRE o kanban existente: task-raiz + N
  workers paralelos (cada um com profile/skills/prompt próprios) + verificador + sintetizador.
  Blackboard compartilhado = comentários JSON na task-raiz (sem DB novo). Estado todo em task_comments/
  task_events.
- **Okami:** `grep swarm` → zero. (O Okami tem `spawn`/delegação async, mas não a topologia
  workers→verificador→sintetizador com blackboard no kanban.)
- **Por quê:** "espalha p/ especialistas, depois mescla" — pesquisa (um entrevista, outro lê docs,
  verificador julga). Dono-único satisfeito: uma pessoa controla o swarm inteiro. Sem dep nova.

### 3. Browser supervisor — listener CDP persistente  **[L · robustez]**
- **Hermes:** `tools/browser_supervisor.py` (1475 ln). 1 WebSocket persistente por sessão de browser,
  auto-subscribe em `Page/Runtime/Target` (detecção OOPIF/worker), snapshot thread-safe de diálogos
  pendentes + frame tree, política de diálogo (`must_respond`/`auto_dismiss`/`auto_accept`), paginação
  do frame-tree (página cheia de ad).
- **Okami:** `integrations/browser.py` não mantém listener CDP persistente nem estado de diálogo
  (grep "supervisor/OOPIF/dialog_policy" → zero).
- **Por quê:** alert/confirm/prompt nativo trava a thread do agente sem isto; iframe/worker viram falha
  cega. Necessário p/ automação de browser robusta em SPA pesada. Usa a dep websockets que já existe.

### 4. Ecossistema de plugins — entry-points pip + middleware  **[M · borderline]**
- **Hermes:** `hermes_cli/plugins.py` (450+ ln) + `middleware.py`. Descoberta de plugin: bundled,
  user (`~/.hermes/plugins/`), project, e **entry-point pip** (`hermes_agent.plugins`). `PluginContext`
  com acesso LLM trust-gated; hooks ricos (`pre_llm_call`, `post_tool_call`, `before_skill_install`).
- **Okami:** tem hooks (`automation/hooks.py`) mas **sem sistema de descoberta de plugin** — sem
  entry-point pip, sem `PluginContext`, sem camada de middleware/interceptação.
- **Por quê:** dono instala plugin verificado (observability, backend de memória custom, scaffolding de
  safety) sem forkar. Espelha a norma do ecossistema Python (setuptools/pip). Borderline: é
  self-improvement via ecossistema, não comportamento de runtime.

---

## Ordem recomendada (se/quando implementar — fora do escopo deste goal, que pediu só "verificar")

**Onda A (produtividade, in-scope, baixa dep):** Blueprints (1) → Kanban swarm (2). Maior ROI p/ um
agente pessoal, aproveitam cron/kanban existentes, sem dep nova.

**Onda B (robustez, opcional):** Browser supervisor (3) — só se o uso de browser automation crescer.
Ecossistema de plugins (4) — se quiser abrir p/ extensões de terceiro.

**Não recomendado** (fora-de-escopo): adapters Bedrock/Gemini (multi-vendor), web/desktop (dep pesada),
tirith (binário externo), lazy-deps (install em runtime).

> Este documento é a entrega da fase "novo comparativo com o Hermes p/ verificar o que mais dá pra
> implementar". A conclusão honesta: **o Okami alcançou paridade profunda**; o que sobra é
> produtividade/distribuição, não capacidade central. Os 4 candidatos in-scope ficam registrados p/ uma
> decisão futura.
