# Pesquisa profunda nº2: Okami vs Hermes (2026-06-11)

> Segunda varredura de fonte do **NousResearch/hermes-agent** (clone em `/tmp/hermes-agent`), agora
> focada nas 7 áreas que o dono apontou como defasadas/incômodas: **providers · TUI · terminal ·
> gateway · skills · harness · chat**. 6 agentes leram arquivo:linha (5 no Hermes + 1 auditando o Okami).
> Dores nomeadas pelo dono: design do terminal/TUI, o jeito do gateway, **respostas curtas e sem
> formatação em modelos fracos**, o harness, e a **criação de skills "péssima"**.

## Diagnóstico em uma frase por área

| Área | Onde estamos | Onde o Hermes está | Causa-raiz da dor |
|---|---|---|---|
| **Chat (fracos)** | Toda saída é UM bloco `json {"tool":"respond","args":{"message":"…"}}` | Tool-calling NATIVO → texto final é markdown livre | O modelo fraco gasta a capacidade em emitir JSON válido e responde curto/escapado |
| **Harness** | Protocolo JSON-em-texto p/ TODO modelo; manual interno gigante "nunca cite" | Native function-calling p/ capazes; guidance POR FAMÍLIA de modelo | Um protocolo só serve mal os dois extremos |
| **Providers** | 30 presets, `native_tools` opt-in DESLIGADO, sem catálogo vivo de capacidade | models.dev (4000+ modelos) com `tool_call`/`context_window`/custo por modelo | Não sabemos a capacidade real do modelo → tool_mode no chute |
| **Streaming** | Existe na camada llm, NÃO chega ao chat/canal | End-to-end: provider→stream_consumer→edição de msg | Resposta só aparece no fim do turno (sensação de travado) |
| **TUI** | Textual com regiões fixas, aprovação por botão, 1 linha por tool-call | Árvore de tool-calls colapsável, markdown→terminal rico, status com disclosure | Falta densidade visual e markdown renderizado de verdade |
| **Gateway** | 1 loop de polling por canal, 1 endpoint/agente, `if/elif` gigante, sem stream | 1 event loop async, registry de plataformas, ContextVar por tarefa, stream consumer | Polling cru + handler monolítico + sem entrega progressiva |
| **Skills** | frontmatter + corpo; criação via review automático; sem comando de criar | `skill_manage()` (agente escreve a própria skill) + hub com scan/quarentena + 170 skills | Não há fluxo de CRIAR skill (nem do agente, nem do humano) |

---

## 1) CHAT + HARNESS — a dor nº1 (modelos fracos curtos/sem formatação)

### Causa-raiz (a mais importante de todo este documento)
Nosso harness obriga **todo** turno a sair como um único bloco JSON
(`okami/core/harness/prompt.py:48-136`, `okami/core/harness/loop.py` parse_action). Para responder, o
modelo precisa emitir `{"tool":"respond","args":{"message":"<markdown aqui dentro, escapado>"}}`.

Um modelo fraco (MiniMax-M3, local, etc.):
1. Gasta a "atenção" em produzir JSON sintaticamente válido.
2. Escapar markdown multi-linha dentro de uma string JSON é difícil → ele encurta para não quebrar.
3. A instrução de "resposta INTEIRA e ESTRUTURADA em MARKDOWN" (`<entrega>`) está **enterrada** num
   bloco marcado "USO INTERNO — NUNCA cite/narre" → o modelo a trata como ruído a evitar, não como guia.

O Hermes não tem esse problema porque o texto final do assistant é **texto livre** (markdown puro),
nunca embrulhado em JSON — o tool-calling é nativo (`agent/conversation_loop.py:3311`,
`agent/transports/chat_completions.py`). E a disciplina vem de blocos de prompt **por família de
modelo** (`agent/prompt_builder.py:315` p/ GPT/Codex/Grok; `:377` p/ Gemini; `:257` enforcement).

### O que o Hermes faz e nós não (verbatim que importa)
- **Sem limite de comprimento no prompt.** Em vez disso, "completion enforcement": *"Every response
  should either (a) contain tool calls that make progress, or (b) deliver a final result to the user.
  Responses that only describe intentions without acting are not acceptable."* (`prompt_builder.py:257`)
- **Hint de formatação POR PLATAFORMA** (`prompt_builder.py:481`): no Telegram diz quais marcas de
  markdown são suportadas e *"Telegram has NO table syntax — prefer bullet lists"*. Nós não temos isso.
- **Recuperação de resposta vazia**: após 3 vazias, comprime + faz fallback (`conversation_loop.py:3908`).

### Recomendações (ordem de impacto)
- **[P0] Caminho de resposta em texto livre p/ modelos fracos.** Quando `tool_mode != native`, aceitar
  que o turno final seja **prosa pura** (sem exigir bloco `respond`). Já temos `prose_outside_action`
  (`loop.py:601`) como fallback — promover de fallback a **caminho de primeira classe** quando o modelo
  não está agindo. Isso sozinho resolve "curto e sem formatação". *(M)*
- **[P0] Tirar a `<entrega>`/idioma/markdown do bloco "nunca cite" e colocar num bloco de ESTILO
  visível** (curto, imperativo, fora do manual de JSON). É o que o Hermes faz. *(S)*
- **[P0] Hint de formatação por superfície** no system_extra (Telegram→bullets, CLI→markdown rico,
  Slack→mrkdwn). Análogo ao `MEDIA_HINT` que acabamos de adicionar. *(S)*
- **[P1] Native tool-calling de verdade** (a flag `native_tools` existe mas está OFF — `okami/config.py:95`).
  Ligar p/ modelos com capacidade nativa → libera o texto final de markdown puro. Precisa verificação ao
  vivo por provider (já anotado como pendência histórica). *(L)*
- **[P1] Guidance por família de modelo** (um bloco curto p/ "gpt/codex/grok", outro p/ "gemini/gemma",
  outro p/ "qwen/deepseek/glm") escolhido pelo nome do modelo. *(M)*

---

## 2) PROVIDERS — saber a capacidade real do modelo

### Gap
Temos catálogo estático de 30 presets (`okami/provider_catalog.py`) e `CapabilityProfile.tool_mode`
no chute por provider. O Hermes consulta **models.dev** (`agent/models_dev.py`): 4000+ modelos com
`tool_call`, `reasoning`, `context_window`, `max_output`, custo e `supports_vision/pdf/audio` — cache
em memória (1h) + disco + snapshot offline. Daí derivam: o picker de `/model`, o tool_mode correto, o
limite de contexto real, e o custo.

### Recomendações
- **[P0] tool_mode derivado de capacidade, não de chute.** Hoje cada provider fraco precisa de
  `capability.tool_mode: json_constrained` explícito senão não chama tool (lição registrada na memória).
  Um catálogo de capacidade (mesmo que um JSON nosso enxuto, ou models.dev) elimina o footgun. *(M)*
- **[P1] Integrar models.dev** (offline-first com snapshot) p/ context_window + custo + tool_call por
  modelo. Alimenta o `/model` picker e o gauge de contexto com números reais. *(M)*
- **[P1] `default_max_tokens` por provider** (`providers/base.py`): hoje deferimos ao default do modelo;
  modelos locais truncam. O Hermes seta 65536 p/ Ollama. *(S)*
- **[P2] Catálogo vivo no picker** (`/model`) com fetch + fallback estático (já temos descoberta
  `/v1/models`; falta casar com capacidade). *(M)*

---

## 3) STREAMING — resposta progressiva (sensação de "vivo")

### Gap
`okami/llm/providers.py:289` tem `stream_complete` (yield de deltas), mas o `loop.py` **não** transmite:
gera o turno inteiro e emite uma vez. Nem o TUI nem os canais recebem deltas. O Hermes tem o pipeline
inteiro: agente emite `MessageChunk`/`ToolCallChunk` → `stream_dispatch.py` (router agnóstico) →
`stream_consumer.py` (buffer + throttle) → adapter edita a mensagem (Telegram draft nativo em DM, edição
de msg no resto).

### Recomendações
- **[P1] Streaming no TUI primeiro** (mais fácil; `rich.live.Live`): harness emite deltas no `on_event`,
  o Textual renderiza progressivamente. Mata a sensação de travado no terminal. *(M)*
- **[P2] Streaming por edição no Telegram** (envia 1 msg, edita com throttle ~1-2s; rola nova no
  overflow >4096). Depende do harness emitir deltas. *(L)*
- Vocabulário de eventos tipado (estilo `stream_events.py`): `MessageChunk`, `ToolCallChunk`,
  `ToolCallFinished` — o agente diz O QUE, o canal decide COMO renderizar. *(M, fundação)*

---

## 4) TUI — densidade e markdown de verdade

### Gap (o design que incomoda)
Já temos as regiões fixas e aprovação por botão. Falta o que dá o "feeling profissional" do Hermes:
- **Árvore de tool-calls colapsável** (`thinking.tsx`): `├─ ● nome_tool… (0.3s)` com spinner braille,
  args/result como filhos colapsáveis, contagem de tokens, heatmap em subagentes. Nós temos 1 linha.
- **Markdown→terminal rico** (`markdown.tsx`): headings em cor de acento, code-fence com label de
  linguagem `─ python` + syntax highlight (8 langs), **diff colorido intra-linha** p/ edições, tabelas,
  blockquote `│ `, listas `• `. Hoje renderizamos markdown mas sem esse mapeamento.
- **Status com disclosure por largura** (`appChrome.tsx:390`): modelo abreviado, `12k/32k tok`,
  barra de contexto colorida por faixa (verde<50%<dourado<80%<laranja<95%<vermelho), custo, bg tasks,
  duração — cada um aparece/some conforme a largura.
- **Composer**: prompt `❯`, glyph muda p/ azul quando começa com `!` (shell), multi-linha com
  Shift+Enter, paleta de comandos fuzzy.

### Recomendações
- **[P0] Tool-call como card em árvore** (1 widget colapsável: ícone+nome+tempo, args/result filhos).
  É o maior salto visual por menos esforço. *(M)*
- **[P0] Diff colorido** no resultado de `edit_file`/`write_file` (`difflib` + realce). *(S-M)*
- **[P1] Syntax highlight** em blocos ``` (já temos `rich.syntax.Syntax`, só ligar nas respostas). *(S)*
- **[P1] Barra de contexto colorida por faixa** + disclosure por largura (já temos gauge; falta cor+tail). *(S)*
- **[P2] Composer multi-linha + paleta fuzzy** (model/persona/sessão). *(M)*

---

## 5) GATEWAY — o jeito que funciona

### Gap (o que incomoda no funcionamento)
Nosso gateway: 1 thread de polling por canal, 1 `AgentEndpoint` por agente, sessão por chat_id, slash
commands num handler grande, texto enviado só no fim. O Hermes:
- **Registry de plataformas declarativo** (`platform_registry.py`): adicionar canal = registrar um
  `PlatformEntry` (factory+validação+env), sem editar o core. Nós temos `build_endpoints` já
  channel-agnóstico, mas os canais ainda são hardcoded.
- **ContextVar por tarefa** (`session_context.py`) em vez de estado global → sem contaminação entre
  mensagens concorrentes. (Nós usamos locks por sessão, ok, mas o padrão ContextVar é mais limpo.)
- **Lock por sessão como `asyncio.Event`** + cache LRU de agentes (128, TTL 1h).
- **Pairing dinâmico** (`pairing.py`): usuário não-autorizado recebe um código de 8 chars (TTL 1h,
  rate-limit, lockout após 5 erros) → aprova sem editar allowlist na mão. **Ótimo p/ PME.**
- **Home channel** (`delivery.py`): destino p/ resultado de cron (`telegram:123` / `origin` / `local`).
- **Hooks de ciclo de vida** (`hooks.py`): `session:start`, `agent:step`, `command:*` carregados de
  `~/.hermes/hooks/` (temos hooks, mas menos pontos).

### Recomendações
- **[P1] Pairing dinâmico** (código de aprovação) — resolve a dor real de "configurar allowlist na mão"
  que registramos no setup. Casa com deny-by-default. *(M)*
- **[P1] Home channel** p/ entrega de cron (já temos cron; falta o destino configurável). *(S-M)*
- **[P2] Registry de plataformas formal** (PlatformEntry) p/ destravar mais canais sem mexer no core. *(M)*
- **[P2] Streaming no gateway** (ver §3). *(L)*
- Avaliar migrar o loop de polling-por-thread p/ um event loop async único (decisão grande; só vale se
  formos escalar muitos canais/sessões). *(L, decisão)*

---

## 6) SKILLS — a criação "péssima"

### Gap (a dor mais concreta)
Hoje **não existe** um fluxo de criar skill: o agente não tem ferramenta p/ escrever a própria skill, e
o humano não tem comando. Temos só carregamento + um review automático que decide salvar
(`okami/skills/__init__.py`, `learning/`). O Hermes tem:
- **`skill_manage()`** (`tools/skill_manager_tool.py`): o **agente escreve a própria skill** —
  `create`/`edit`/`patch`/`delete`/`write_file`. Valida nome/tamanho, scan de segurança opcional,
  grava em `~/.hermes/skills/<nome>/SKILL.md`. Disponível na hora via `/<skill>`.
- **Progressive disclosure em 3 tiers** (`skills_tool.py:680`): Tier 1 = só nome+descrição no system
  prompt (barato); Tier 2 = `skill_view(name)` carrega o corpo inteiro sob demanda; Tier 3 = arquivos
  ligados (scripts/refs) um a um. Controla custo de token.
- **Hub/marketplace** (`skills_hub.py`): instala de GitHub/catálogo oficial com quarentena, scan AST
  (exec/eval/__import__), detecção de prompt-injection, `lock.json` com proveniência, `skills update`
  com diff antes de aplicar.
- **170 skills** (73 bundled + 97 opcionais). Frontmatter rico: `platforms`, `environments`,
  `requires_toolsets`, `required_environment_variables` com prompt de setup.

### Recomendações
- **[P0] Ferramenta `create_skill`/`manage_skill`** p/ o agente escrever a própria skill (create/edit/
  patch + write_file de scripts/refs), gravando em casa, com nosso `skill_security.scan_path` já
  existente como gate. É o conserto direto da dor. *(M)*
- **[P0] Comando `/skill new` no chat e `okami skill new` no CLI** (wizard: nome→descrição→triggers→
  corpo) — humano cria skill sem editar arquivo na mão. *(M)*
- **[P1] Progressive disclosure de verdade**: hoje injetamos catálogo + forçadas; adotar Tier-1 (só
  nome+descrição) + `use_skill`/`skill_view` sob demanda reduz token e melhora foco. *(M)*
- **[P1] Frontmatter `requires_toolsets`/`required_environment_variables`** com prompt de setup. *(S-M)*
- **[P2] Hub instalável** (git/catálogo) com scan + lockfile (já temos `lockfile.py` parado e
  `skill_security`; falta o instalador + quarentena). *(L)*

---

## Sequência recomendada (do que mais dói pro que mais escala)

1. **Chat/Harness P0** — caminho de resposta em texto livre p/ fracos + bloco de ESTILO visível + hint
   por superfície. *Resolve a dor nº1 com baixo risco e sem rewrite.*
2. **Skills P0** — `create_skill` (agente) + `/skill new` (humano). *Conserta a criação "péssima".*
3. **TUI P0** — tool-calls em árvore + diff colorido + syntax highlight. *Mata o "design ruim".*
4. **Providers P0/P1** — tool_mode por capacidade (+ models.dev). *Tira o footgun dos fracos.*
5. **Streaming no TUI (P1)** → depois Telegram (P2). *Sensação de vivo.*
6. **Gateway P1** — pairing dinâmico + home channel. *Escala/operação.*
7. **Decisões grandes** — native tool-calling ao vivo, event loop async, hub de skills.

> Fonte da verdade do estado atual: README + auto-memória. Refs do Hermes: `/tmp/hermes-agent`.
