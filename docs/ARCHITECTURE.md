# Okami Agent — Arquitetura

> Documento de arquitetura. Versão 0.6 — 2026-06-03.
> Agente de codificação confiável, com gateway (Telegram → Slack → Paperclip), múltiplos
> providers (Claude Code, Codex, MiniMax, MiMo, LMStudio local), que **resolve as duas dores
> que motivaram o projeto** (harness que nunca trava; aderência obrigatória a design system)
> e **melhora com o tempo** — incluindo a própria persona e o próprio gosto de design.
>
> Mudanças v0.3 (baseadas no estudo do código real do Hermes):
> - Memória plugável alinhada ao ciclo de vida de providers do Hermes (§6), com **Honcho** e
>   **holographic/HRR** detalhados a partir da implementação real.
> - **Harness adaptável a qualquer LLM** (§3.5): invariantes valem sempre; o andaime se ajusta
>   à capacidade do modelo em uso.
> - **Identidade & Persona evolutiva** (§8): `SOUL.md` + `PERSONA.md`/`PROFILE.md` + `VOICE.md`
>   + sections, **por agente**, que **evoluem** (o Hermes mantém SOUL.md estático — aqui não).
> - **Aprendizado de gosto de design** (§9): aprovado atrai, recusado repele, "diferente" explora.
>
> Mudanças v0.4:
> - **Stack fechada: Python** (§2), tendo como referência rodável o repo
>   [build-your-own-openclaw](https://github.com/czl9707/build-your-own-openclaw) (18 passos) +
>   Hermes. Providers via **LiteLLM**; Honcho via SDK Python; holographic com **numpy nativo**.
> - Padrões adotados do repo de referência: `PromptBuilder` de camadas (§8), roteamento por
>   **bindings com tiers de regex** + `AGENT.md` (§10), `ContextGuard` de compaction (§6.4),
>   `SKILL.md`, YAML com hot-reload.
>
> **Importante (qualidade de frontend ≠ linguagem):** o frontend feio do Hermes NÃO vem de ele
> ser Python — vem da ausência de contratos/gates/taste. O agente escreve `.tsx` de ShadCN igual,
> seja o runtime Python ou Node. A beleza é garantida por §4.3 (gates) + §9 (taste) + §4.4
> (scaffolds), camada **agnóstica de linguagem**. Logo: Python **e** design bom, sem conflito.

---

## 0. Por que o Okami existe (as duas dores)

1. **Harness não-confiável** (OpenClaw): diz *"vou fazer"*, não age; cobrado, diz *"pera, tô
   fazendo"* e nunca conclui. Loop sem invariante de ação e sem detecção de conclusão real.
2. **Não adere a skills / design system** (Hermes): pede ShadCN/HeroUI e ele inventa CSS feio.
   Skills como sugestão, não como gate; sem verificação mecânica.

§3 e §4 resolvem isso por construção. §6–§9 são as capacidades que te fazem gostar do Hermes,
levadas além: memória de verdade, **auto-melhoria**, **persona que evolui** e **gosto que
aprende**. Tudo plugável e funcionando **com qualquer LLM** (§3.5).

---

## 1. Visão geral

```
                        ┌─────────────────────────────────────────────┐
   Telegram ─┐          │                  OKAMI CORE                  │
   Slack   ──┼─► Gateway│  ┌──────────┐   ┌───────────┐   ┌─────────┐  │
   Paperclip─┘ (channels)──►│ Harness  │──►│  Skills   │──►│ Tools / │  │
   (heartbeat)            │  │ +state   │   │ +gates    │   │  MCP    │  │
   Cron/Events ──────────►│  │ +cap-adapt│  └───────────┘   └─────────┘  │
                          │  └────┬─────┘        ▲                       │
   CLI / TUI ────────────►│       │              │                       │
                          │  ┌────▼─────┐  ┌─────┴─────┐   ┌──────────┐  │
                          │  │ Providers│  │ Identity  │   │  Memory  │  │
                          │  │ router + │  │ persona + │   │ plugável │  │
                          │  │ fallback │  │ voice +   │   │ (Honcho/ │  │
                          │  └──────────┘  │ taste     │   │  HRR…)   │  │
                          │                └───────────┘   └──────────┘  │
                          └─────────────────────────────────────────────┘
   Learning loop (§7) observa execuções → escreve skills, memória, PERSONA/VOICE e taste ▲
```

Princípios: **local-first**, **action-or-terminate**, **contracts são lei**,
**provider-agnóstico**, **plugável**, e **evolutivo** (skills, memória, persona e gosto melhoram
com o uso).

### 1.1 Diferenciais vs. o repo de referência (não seguir às cegas)
O `build-your-own-openclaw` (e o próprio OpenClaw/Hermes) entrega o **plumbing/table-stakes**. Os
**diferenciais do Okami** são construídos **por cima** — o repo não tem nenhum deles:

| Table-stakes (do repo/OpenClaw/Hermes) | Diferencial do Okami (nosso) |
|---|---|
| chat loop, tools, SKILL.md, channels, cron | **Harness com paridade entre LLMs** (§3.5) ⭐⭐ |
| compaction por sumarização (ContextGuard) | **Auto-compaction que promove fato p/ long-term** (§6.4) |
| prompts multi-camada estáticos | **Persona/SOUL/VOICE que EVOLUEM** (§8) |
| memória básica | **Honcho + holographic plugáveis, sem degradar** (§6) |
| — | **Closed learning loop: auto-skill/persona/tune** (§7) |
| — | **Modelo de gosto de design** (§9) |
| skills como sugestão | **Skills como gate + verification gates de UI** (§4) |

Regra de ouro: tudo que é table-stakes a gente **reaproveita** do repo; tudo que é diferencial a
gente **projeta e verifica** (não herda).

---

## 2. Stack e estrutura

- **Runtime**: **Python 3.11+** (ver `requires-python` no pyproject). Gerenciador: **uv**. Tipagem estrita (mypy/pydantic).
- **Providers**: **LiteLLM** unifica Claude Code, Codex, MiniMax, MiMo e LMStudio (§5).
- **Estado**: SQLite + FTS5 + arquivos markdown versionáveis.
- **Memória**: backend `honcho` via **SDK Python**; `holographic` com **numpy nativo** (sem ponte IPC).
- **Config**: **YAML com hot-reload** (padrão do repo de referência).
- **Sandbox**: Docker opcional.
- **Referência rodável**: [build-your-own-openclaw](https://github.com/czl9707/build-your-own-openclaw) (18 passos) + Hermes.
- **Frontends gerados** (artefato, não o runtime): TS/React + **ShadCN/HeroUI** + Tailwind
  pré-instalados. **Painel de controle** (`web/`): app React/TS separado. A linguagem do agente
  não afeta a qualidade desses frontends — quem garante é §4.3 + §9.

```
okami/
├─ okami/                   # pacote principal Python
│  ├─ core/                 # HARNESS: state machine + watchdog + cap-adapt  (§3)
│  ├─ contracts/            # contratos + verification gates                 (§4)
│  ├─ skills/               # runtime skills (SKILL.md) + router + skill.sh   (§4, §7)
│  ├─ learning/             # closed learning loop (skill/persona/taste/tune) (§7)
│  ├─ providers/            # LiteLLM + router + fallback + cap profiles      (§5, §3.5)
│  ├─ memory/               # memória plugável (lifecycle 6 passos)           (§6)
│  │  └─ backends/          #   sqlite_fts5 | honcho | holographic            (§6)
│  ├─ identity/             # PromptBuilder: SOUL/PERSONA/VOICE/sections      (§8)
│  ├─ taste/                # modelo de gosto de design (aprende)             (§9)
│  ├─ agents/               # AgentLoader + bindings (routing por tiers)      (§10)
│  ├─ scheduler/            # cron + heartbeat + event bus                    (§11)
│  ├─ tools/                # tools nativas + cliente MCP                     (§12)
│  ├─ channels/             # telegram, slack, paperclip                      (§13)
│  └─ cli.py                # entrypoint "okami"
├─ web/                     # painel de controle (React + ShadCN, TS) — app separado
├─ skills/                  # SKILL.md (agentskills.io)
├─ workspaces/              # 1 dir isolado por agente, com identidade própria:
│  └─ <agent>/              #   AGENT.md · SOUL.md · PERSONA.md · VOICE.md · sections/ · memory/
├─ default_workspace/       # templates/exemplos (como no repo de referência)
├─ okami.yaml               # config raiz (hot-reload)
└─ docs/{ARCHITECTURE,ROADMAP}.md
```

---

## 3. O Harness confiável (resolve a Dor #1)

O loop **não confia na prosa do modelo**; decide pelo estado e por efeitos observáveis.

### 3.1 Máquina de estados
```
PENDING ─► IN_PROGRESS ─► COMPLETE   (exitCriteria verificados pelo harness)
                 ├─► BLOCKED  (razão estruturada)
                 ├─► NEEDS_INPUT
                 └─► FAILED   (orçamento de passos/tempo estourado)
```
Nunca fica IN_PROGRESS pra sempre: `maxSteps`, `maxWallClock`, stall detector (§3.3).

### 3.2 Invariante Action-or-Terminate (conserto do "vou fazer")
Todo turno termina em **tool call** OU **sinal terminal** (`task_complete`/`task_blocked`/
`need_input`). Texto em futuro ("vou", "let me", "I'll") **sem ação** é rejeitado e re-prompted:
*"Você disse que faria X mas não agiu. Execute agora ou declare bloqueio."* O **Intent–Action
reconciler** (PT/EN) detecta o compromisso sem ação. `task_complete` só vale se `exitCriteria`
baterem (§3.4) — "concluído" é asserção do harness, nunca só do modelo.

### 3.3 Watchdog / stall detector
`K` passos sem efeito observável → forcing function → persistindo, `FAILED` com diagnóstico.
Heartbeat de progresso para usuário/painel.

Cada chamada ao modelo também recebe um `RequestContext` novo, com orçamento total, TTFB e idle,
cancelamento linearizado e callbacks de abort do transporte. Retry e fallback da mesma chamada
compartilham esse contexto; uma nova geração ou escalada começa com outro contexto. Assim, timeout
e cancelamento atravessam provider, streaming e transport sem reaproveitar relógios de chamadas
anteriores.

### 3.4 Critérios de saída verificados
`exitCriteria` checáveis (build passa, testes verdes, arquivo existe, gate de contrato §4).
Falha → lista exata do que falta → volta a trabalhar.

### 3.5 Paridade de capacidade entre LLMs (o diferencial gigante) ⭐⭐

**Por que Hermes/OpenClaw falham com Haiku, GPT-5.4-mini ou modelos locais:** eles **assumem um
modelo forte** — jogam no modelo o planejamento, a gestão de um system prompt gigante e a emissão
de tool-calls perfeitos. Modelo fraco/pequeno/local: faz drift, alucina schema de tool, se perde em
contexto longo, e os erros se acumulam sem verificação.

**Tese do Okami:** a inteligência mora no **harness**; o modelo é uma **função estreita e trocável**.
Quanto mais fraco o modelo, **mais** o harness decompõe, restringe, verifica e compensa. O resultado
tende à **paridade**, porque o harness fornece o que o modelo não tem. Mecanismos concretos:

1. **Decomposição externalizada.** O planejamento vive no harness, não no modelo. Em vez de pedir a
   um modelo fraco "faça a tarefa grande", o harness quebra em **micro-passos totalmente
   especificados** e entrega um de cada vez. O tamanho do chunk escala com a capacidade (forte =
   chunks maiores e mais latitude).
2. **Camada de confiabilidade de tool-call** (o maior motivo de falha). Três modos, auto-selecionados
   pelo capability profile: **tool-calling nativo** → **JSON com schema/grammar constrained** →
   **ReAct parseado** (fallback). Todo tool-call é **validado contra o schema → auto-reparado →
   re-perguntado com o erro exato**. Tool-call malformado **nunca é fatal**. Para locais
   (LMStudio/llama.cpp): **constrained decoding via GBNF / JSON-schema** — o modelo fica *impossibilitado*
   de emitir inválido. (Hermes/OpenClaw não fazem isso.)
3. **Minimização de contexto / just-in-time.** O system prompt gigante (SOUL+persona+memória+skills+
   40 tools) não cabe bem em modelo pequeno. O harness injeta **só** a skill/memória/tools relevantes
   ao micro-passo atual (recall §6) e faz **tool subsetting** (expõe poucas tools por passo → menos
   erro de seleção). Modelo forte recebe mais; fraco recebe janela enxuta e focada.
4. **Piso de qualidade por verificação.** Gates (§4.3) + `exitCriteria` (§3.4) + Action-or-Terminate
   (§3.2) capturam e corrigem o erro do modelo fraco automaticamente. A qualidade do output tem
   **piso no verificador** (não no modelo) e teto no modelo → *modelo fraco + verificação forte ≈
   output decente*.
5. **Self-consistency + cascata de escalonamento.** Em decisões críticas, amostra N e **vota**
   (self-consistency); ou usa modelo barato para amplitude e **escala para um forte só quando a
   confiança é baixa** (cost-aware). O capability profile decide quando ensemblar vs single-shot.
6. **Skills/persona model-aware.** Skill carrega metadado de dificuldade e **auto-expande** em guia
   mais granular para modelos fracos; persona/voice (§8) são renderizadas mais explícitas para fracos
   (precisam de mais direção para não sair do personagem).

**Capability profile** por `(provider × modelo)` parametriza tudo acima:

| Knob | LLM fraco/local | LLM forte |
|---|---|---|
| Decomposição (#1) | micro-passos | chunks grandes |
| Modo de tool-call (#2) | JSON/grammar constrained → ReAct | nativo |
| Contexto/tools por passo (#3) | enxuto, subset pequeno | amplo |
| Self-consistency (#5) | vota N / escala cedo | single-shot |
| Estritura do reconciler (§3.2) + retries | alta / mais | relaxada / menos |
| Verbosidade corretiva + reflexão (§7) | passo-a-passo | concisa |

- **Bootstrap**: defaults por tier conhecido + **probe de calibração** no 1º uso de um modelo novo.
- **Auto-tune**: o `learning` (§7) mede os **modos de falha por modelo** (rejeição em gates, stalls,
  tool-calls malformados) e ajusta o profile — mais decomposição, grammar mais estrita, retries,
  subsets menores. Cada modelo ganha um andaime cada vez melhor ajustado a ele.
- **Resultado:** Haiku, GPT-5.4-mini e modelos locais chegam **perto da paridade** — sem nunca abrir
  mão das invariantes (§3.2–3.4). É o diferencial que Hermes/OpenClaw não têm.

### 3.6 Anti-loop (chega de loop infinito de tool-calling) ⭐
Modelo fraco adora repetir a mesma tool, oscilar entre dois estados e re-rodar o comando que falha.
O harness detecta e quebra isso — não depende do modelo "perceber":

1. **Fingerprint + dedup de ações.** Cada chamada vira hash `(tool, args normalizados)`. Repetiu o
   mesmo fingerprint N vezes → é loop: a chamada é **bloqueada** e injeta-se *"você já fez X e o
   resultado foi Y; não repita — faça algo diferente ou declare bloqueio"*.
2. **Detecção de ciclo.** Janela recente de fingerprints detecta padrões `A,B,A,B` / `A,B,C,A,B,C`.
   Ciclo detectado → quebra com nudge corretivo.
3. **Circuit breaker de falha repetida.** Mesmo comando falhando N vezes com o mesmo erro → aquela
   abordagem é **proibida**; força estratégia diferente ou `BLOCKED`.
4. **Orçamento por progresso (≠ stall §3.3).** Progresso é medido contra os `exitCriteria` (violações
   de gate caindo, testes passando subindo). Plano/oscilante por uma janela → quebra. (§3.3 cobre
   "nenhum efeito"; aqui cobre "muito efeito, zero progresso".)
5. **Tetos duros.** `maxToolCalls` por tarefa + cap por-tool; avisos ao se aproximar.
6. **Escada de escalonamento** (nunca gira em silêncio): nudge com evidência do loop → re-decompõe
   diferente (§3.5 #1) → **escala p/ modelo mais forte** (cascata §3.5 #5) → `BLOCKED` com diagnóstico.

### 3.7 Anti-alucinação ⭐
Em código, alucinação = API/import/pacote inexistente, conteúdo de arquivo inventado, ou "sucesso"
fingido. Defesa em camadas:

1. **Grounding obrigatório.** Afirmação sobre o código precisa estar lastreada numa **observação real
   no contexto** (resultado de tool). Generaliza o *Read-before-Edit*: não edita arquivo que não leu;
   "cite a fonte". **Tool result é a verdade, não a memória do modelo.**
2. **Gates como filtro de alucinação** (§4.3). `build`/`typecheck`/testes pegam API/import alucinado
   na hora → erro volta pro modelo. **Código alucinado não passa no gate.**
3. **Checagem de existência.** Antes de usar símbolo/import/**pacote**, verifica que existe (no
   arquivo / lockfile / registry). **Bloqueia instalar pacote não-verificável** (anti-slopsquatting).
4. **Abstenção é first-class.** *"Não sei / preciso checar"* → tool de verificação ou `need_input` é
   **mais barato** que chutar. O harness favorece olhar a verdade a inventar.
5. **Proveniência na memória.** Recall (§6) devolve fatos **com fonte**; "fato" sem fonte é suspeito
   (Honcho/holographic carregam origem). O modelo não inventa fato fora da memória.
6. **Self-consistency / crítico** para afirmações não-verificáveis mecanicamente (§3.5 #5).
7. **Model-aware.** Modelo fraco → grounding mais estrito, verificação mais frequente, limiar de
   abstenção mais alto (no capability profile §3.5).

Sinergia: a invariante Action-or-Terminate (§3.2) já mata o *"rodei os testes, passou"* sem a tool
call; os `exitCriteria` (§3.4) já matam o *"concluído"* falso. §3.6/§3.7 cobrem o resto.

---

## 4. Skills + Contracts + Verification Gates (resolve a Dor #2)

### 4.1 Project Contracts
`okami.config.json` declara regras duras e verificáveis:
```json
{ "contracts": { "ui": {
  "library": "shadcn",                  // ou "heroui"
  "componentSource": "@/components/ui",
  "forbidRawCss": true, "forbidInlineHexColors": true,
  "minComponentReuse": 0.8
}, "tests": { "required": true } } }
```
Contrato é injetado no contexto **e** vira `exitCriteria` (§3.4).

### 4.2 Seleção de skills: forçadas + progressive disclosure (estilo Claude Code)
O harness **sabe usar skills**, não só tools. Dois caminhos:
- **Forçadas por contrato/keywords** (router): para tipos cobertos por contrato, a skill
  (`frontend-shadcn`/`frontend-heroui`) é **injetada inteira** e vira gate (COMPLETE só com o
  checklist da skill **e** os gates §4.3 verdes).
- **Progressive disclosure** (Claude Code): as demais skills aparecem como **catálogo leve**
  (nome + descrição) sempre no prompt; o agente **carrega a relevante sob demanda** com a tool
  **`use_skill`** — barato e escalável (não despeja tudo no contexto).
Skills passam pelo **scan de segurança (§4.5)** antes de entrar no catálogo/uso. Formato
**agentskills.io**; instalação via **skill.sh** (`okami learn <fonte>`). O loop de auto-melhoria
(§7) cria skills pelo mesmo caminho.

**Skills empacotadas** (14, customizadas/menos genéricas, no `skills/`): `frontend-shadcn`,
`frontend-heroui`, `claude-design` (HTML one-off), `humanizer` (responder humano), `proactive-agent`
(proatividade + write-ahead), `tdd`, `writing-plans`, `communication-131` (regra 1-3-1), `code-wiki`,
`page-agent`, `kanban-orchestrator` (decompõe→profiles §10), `honcho-memory`, `delegate-claude`,
`delegate-codex` (quando escalar pro provider forte §3.5). Todas passam no scan (§4.5). Mais via `okami learn`.

### 4.3 Verification Gates (conserto do "CSS feio")
Antes de aceitar conclusão de UI: (1) **AST de imports** (vêm de `componentSource`? reuso ≥
`minComponentReuse`?); (2) **anti-CSS-ad-hoc** (sem `<style>` solto / hex inline fora dos
tokens); (3) **lint de design tokens**; (4) **build + typecheck**; (5) **self-check visual**
(render headless → screenshot → critic, fase ≥2). Qualquer falha → violações arquivo:linha →
re-prompt. **Não dá pra declarar pronto com CSS genérico.** O **gosto de design** (§9) entra
como crítico *soft* por cima deste gate *hard*.

### 4.4 O agente instala/inicializa a lib (não pré-instalado)
A skill de frontend (§4.2) **ensina o agente a instalar e inicializar** a lib via `run_shell`
(`npx create-next-app`, `npx shadcn init`/`add`, ou `npm i @heroui/react`) — sem scaffold
pré-instalado. A skill traz o "como"; o gate (§4.3) verifica o "resultado".

### 4.5 Validação de segurança de skills (CRÍTICO)
Skills são código + instruções que entram direto no contexto/execução do agente — vetor de
prompt injection, exfiltração de segredos (inclui credenciais OAuth!), `rm -rf`, `curl|bash`,
malware. Regra: **nada entra em `skills/` sem passar por scan**.
- `okami/skill_security.py`: scanner estático (regex), severidade INFO→CRITICAL. Detecta prompt
  injection / prompt-leak / stealth, shell destrutivo (rm -rf, fork bomb, pipe-to-shell),
  exfiltração (webhooks Discord/Slack/Telegram, requestbin/ngrok/pastebin), acesso a segredos
  (`~/.ssh`, `.aws`, `.codex/auth`, `.okami/credentials`), RCE/ofuscação (eval/exec/base64) e o
  combo **segredo + rede no mesmo arquivo**. HIGH/CRITICAL = bloqueado.
- **Quarentena**: `okami learn <fonte>` baixa para `.okami/quarantine`, escaneia e **só promove
  para `skills/` se passar** (ou `--force` com aviso). Fontes: skill.sh (`owner/repo`, URL, git)
  e **ClawHub** (`clawhub:<slug>`).
- **Defesa em profundidade**: o router (§4.2) reescaneia antes de injetar e **se recusa a injetar**
  skill bloqueada. `okami scan <path>` valida sob demanda. **Escaneia TUDO que é injetado** (corpo,
  descrição, metadados — fecha o gap do Hermes #8884 onde DESCRIPTION.md ia sem scan).
- **Anti-evasão** (gap do Hermes #7072): detecta ofuscação (`__import__`, `getattr`+import,
  namespace dinâmico, hex/char-code strings), **unicode oculto/Trojan Source** (zero-width, bidi),
  e **binários empacotados** (não escaneáveis → flag).
- **Strip de env nos subprocessos**: `run_shell` e `shell_ok` rodam com `sanitized_env()` —
  chaves/tokens/segredos REMOVIDOS do ambiente, então nem prompt injection nem código gerado
  conseguem exfiltrar credencial via shell (padrão do Hermes).
- **Design futuro** (anotado): manifesto de permissões por skill (fs/rede/env declarados +
  enforcement, estilo OpenClaw), sandbox com **rede `none` por padrão** (§12), revisão por LLM, e
  — IMPORTANTE — as **skills criadas pelo agente** no learning loop (§7) DEVEM passar pelo mesmo
  scan antes de virar ativas (gap do Hermes #16461: agent-created sem scan).

---

## 5. Providers (router + fallback)

O núcleo resolve `(provider, model, endpoint, api_mode, transport, credencial, capabilities,
billing)` em um `RuntimeTarget` imutável. `TargetResolver` é a entrada única para aliases,
overrides e fallbacks; credenciais entram no target apenas como referência segura, nunca como
segredo resolvido.

`TransportRegistry` seleciona adapters nomeados para CLI, OAuth, APIs nativas e LiteLLM. O
**LiteLLM agora é um adapter explícito de compatibilidade**, e não o lugar onde o roteamento vive:
chamadas, streams e detecção de parâmetros suportados ficam isolados em `litellm_compat.py`, com
política de descarte por request e sem mutar globals no import.

Fallback aceita tanto o formato legado `fallback: [provider]` quanto destinos estruturados com
`provider`, `model`, `base_url` e `api_mode`. A cadeia é normalizada, deduplicada e filtrada antes
da execução; cancelamento impede novas tentativas e o resultado registra o provider/modelo que
realmente serviu a resposta.

| Provider | Auth | Papel sugerido |
|---|---|---|
| **Claude Code** (sub US$100) | OAuth/CLI | raciocínio/código/frontend |
| **Codex** (sub US$200) | sub/CLI | alternativa forte / fallback |
| **MiniMax** (US$20) | API key | alto volume / barato |
| **MiMo** (Xiaomi, US$20) | API key | leve / classificação / router |
| **LMStudio** (local) | OpenAI-compat | privado/offline |

Cada provider carrega seu **capability profile** (§3.5). Subscrições Claude Code/Codex via auth de
CLI/sub (risco §16).

---

## 6. Memória (plugável) + auto-compaction

Alinhada ao modelo real do Hermes: **camada de arquivos sempre ativa** + **um backend externo por
vez**, ambos seguindo um ciclo de vida comum.

### 6.1 Camadas (sempre on) — identidade + tier "core" .md (estilo Hermes)
**SEMPRE injetados** no system prompt (`files.core_block`), nesta ordem (PromptBuilder §8), cada um
com **limite configurável (default 4000 chars** — maiores que os do Hermes):
- **Identidade** (limite default **6000**): **`SOUL.md`** (valores) → **`VOICE.md`** (tom) →
  **`PERSONA.md`**/`PROFILE.md` (self-model). **Evolução AUTOMÁTICA e GRADUAL ✅** (`okami/persona.py`,
  §8): um **observador** (`observe`) lê cada fala do usuário e DEDUZ traços de estilo — palavrão,
  apelido, sarcasmo, registro técnico×casual, pedidos explícitos. Acumula sinais e **promove sozinho**
  (sem perguntar — pedido do usuário) quando o padrão cruza o limiar (`min_count`: explícito=1,
  inferido=2+ → anti-overfitting), evoluindo **VOICE/PERSONA *e* USER.md** juntos. REVERSÍVEL:
  changelog `.okami/persona_history.jsonl` + `rollback`/`/undo`. **SOUL é PROTEGIDO** (âncora
  anti-drift): só muda com `allow_soul` (pedido explícito) + go/no-go. A evolução entra no `core_block`
  (vai pro prompt). Config `persona.observe`/`gradual_scale`. CLI `persona-evolve|persona-log|
  persona-rollback`; no Telegram `/feedback <...>` e `/undo`. Camada LLM: `propose_llm`/`observe` heur.
  **SEGURANÇA (estilo Hermes, que escaneia o SOUL):** como o observador grava texto DERIVADO da conversa
  na identidade (→ vai pro prompt), `is_safe_identity_text` reusa `skill_security.scan_text` e BLOQUEIA
  prompt-injection/unicode oculto antes de gravar (fecha o vetor "me chama de \<payload\>"). **`/persona
  <preset|texto|off>`** (estilo Hermes `/personality`): overlay de persona **só na sessão** (não grava) —
  `PERSONA_PRESETS` (conciso/técnico/professor/casual/direto/pirata) no `extra_context`. **Seções
  (estilo Hermes Identity/Style/Avoid/Technical):** os traços aprendidos entram em `## Estilo`/`##
  Evitar`/`## Postura técnica`/`## Especialidade` (mais legível p/ o modelo). **`observe_llm`**:
  leitura periódica por LLM (constrained) que pega o que a heurística não vê (sarcasmo pelo tom) e
  alimenta o MESMO acumulador gradual (min_count=2, anti-alucinação); liga com `persona.llm_every: N`.
- **Core** (limite default 4000): **`AGENTS.md`** (projeto) → **`USER.md`** (usuário) → **`MEMORY.md`** (fatos).

A ideia: o que é frequente/durável mora aqui, evitando consultar a memória (tier archival §6.2/§6.3)
toda hora. **O agente EVOLUI** escrevendo de volta: `USER.md` via tool `remember_user`, `MEMORY.md`
via `remember` + extract (§6.2 passo 4) — instruído no system prompt (regra 6). `okami persona-init`
cria os stubs de identidade. `working memory` é o alvo da auto-compaction (§6.4).

### 6.2 Ciclo de vida do backend (interface comum)
Todo backend implementa o mesmo fluxo automático (espelhando o Hermes):
1. **inject** contexto no system prompt · 2. **prefetch** antes de cada turno · 3. **sync** do
turno depois da resposta · 4. **extract** no fim da sessão · 5. **mirror** das escritas do
built-in · 6. **tools** próprias de busca/gestão. Só **um** backend externo ativo por vez.

### 6.3 Backends (`memory.backend`)
| Backend | Como funciona | Quando |
|---|---|---|
| **`sqlite-fts5`** (default) | **HÍBRIDO** (SOTA): **BM25** (FTS5, ranking real, **insensível a acento** PT) + **recência** (decay) + **importância** (heurística) — e **embeddings OPCIONAIS** somados (relevância semântica). Retrieval funde os sinais (Generative Agents/Mem0). **Dedup no write** + **forget** (anti context-rot). Embedder é qualquer endpoint **OpenAI-compat** (**llama.cpp** `llama-server`, Ollama, LMStudio) com **probe + circuit breaker**: se não houver LLM local, degrada para BM25 — **nunca depende de embeddings**. | padrão local-first |
| **`honcho`** ✅ | SDK `honcho-ai` (`peer`/`session`/`add_messages`, **`peer.chat`** dialético = oráculo; `session.context()` = user-model). **`base_url` REMOTO** (VPS dedicada via Tailscale). Dep opcional `[honcho]`. Combina com holographic via `LayeredMemory` (daily-driver do user). | modelagem rica do usuário **e do agente** (alimenta a persona §8); remoto/distribuído |
| **`holographic`** ✅ | **HRR/VSA** (numpy local, dim 1024): codebook de tokens + **trigramas** de char (accent-fold) → superposição = vetor do texto, **SEM servidor de embedding**. Pluga no backend rápido (reaproveita BM25 + recência + importância + cosine vetorizado). **Binding/unbind/cleanup** (composicional). | local sem máquina de embedding; daily-driver do user junto com honcho |

**Melhoria sobre o Hermes:** o holographic do Hermes **degrada silenciosamente** pra FTS5 quando
falta numpy ([issue #17350](https://github.com/NousResearch/hermes-agent/issues/17350)). No Okami:
numpy é dep **declarada**, com **WARNING** explícito e check no `okami doctor` — nunca degrada em
silêncio. (Idem: garantir que o recall realmente dispara antes do turno — bug #31263.)

### 6.3b Deployment: nativo vs remoto (importante)
- **NATIVOS no agente** (in-process, mesma máquina, sem rede): harness (§3), **holographic** (HRR/numpy —
  igual ao Hermes; NUNCA roda em outra máquina), skills/router, contracts/gates. O `sqlite-fts5` também é
  nativo (arquivo local), com embedder remoto **opcional**.
- **REMOTOS** (opcionais, por host/Tailscale): **honcho** (instância dedicada), o **embedder** do
  `sqlite-fts5`, e os **LLMs/providers**. Só esses cruzam a rede.
- Topologia distribuída típica do user: VPS-agente (harness + holographic nativos) + VPS-honcho +
  VPS-LLM(embedding/inferência), tudo via Tailscale. Holographic fica **com o agente**, não vira serviço.

### 6.4 Auto-compaction sem perder contexto — **adaptativa à janela do modelo**
Threshold **por modelo**: `context_window` (tokens) no provider → comprime em ~72% da janela
(`compaction_threshold_chars`). Qwen 32K comprime cedo (~94k chars); Claude 200K, tarde (~576k);
MiniMax 1M, muito tarde. No gateway, o histórico da sessão também escala (~12% da janela). **Nada
se perde**: antes de comprimir, os fatos são PROMOVIDOS à memória de longo prazo (e voltam via
recall) — então mesmo num modelo de 32K a conversa do Telegram não perde contexto.
Base no `ContextGuard` do repo de referência (estimar tokens via LiteLLM → truncar tool-results
grandes → sumarizar antigas; mantém recentes + schemas + system prompt; comandos `/context` e
`/compact`). **Superset do Okami:** antes de sumarizar, (1) **particiona** fatos duráveis vs ruído;
(2) **promove** os fatos p/ backend + `MEMORY.md`; (3) sumariza com **ponteiros recuperáveis**;
(4) **reidrata** sob demanda via `recall`. Compaction = **promover + apontar**, nunca esquecer
(o repo só sumariza; nós persistimos primeiro). Testes adversariais "compactou e esqueceu".

---

## 7. Auto-melhoria — Closed Learning Loop  ✅ fatia 1 (reflexão→memória)

`packages/learning` faz o agente (e tudo nele) melhorar com o uso, observando as execuções.

```
executa ─► registra trajetória (passos, tools, erros, gates, feedback)
   ▲                         │ reflexão pós-tarefa
   │   ┌─────────────────────┼───────────────────────────────────────┐
 aplica │ cria/atualiza SKILL (via skill.sh §4.2)                     │
        │ escreve FATO / ANTI-PADRÃO na memória (§6)                  │
        │ ajusta capability profile do modelo (§3.5)                   │
        │ propõe evolução de PERSONA/VOICE (§8)                        │
        └ atualiza modelo de GOSTO de design (§9) ────────────────────┘
```
- **Auto-skill**, **anti-padrões** (falha recorrente vira regra negativa/guard-rail),
  **auto-tune de roteamento e de capability profile** (§3.5).
- **Curadoria/dreaming** periódica (`reflect`) consolida e poda — evita memória podre.
- **Human-in-the-loop opcional**: mudanças sensíveis (persona, skill permanente) podem exigir
  aprovação (integra governança do Paperclip §13). Tudo versionado e reversível.

---

## 8. Identidade & Persona evolutiva ⭐ (vai além do Hermes)

No Hermes, `SOUL.md` é o slot #1 do system prompt mas é **estático** (só edição manual). No Okami,
**cada agente nasce único e evolui** sua personalidade com o tempo.

### 8.1 Arquivos de identidade (por agente, no workspace)
| Arquivo | Conteúdo | Velocidade de mudança |
|---|---|---|
| **`SOUL.md`** | Núcleo: valores, princípios, limites, identidade. Slot #1. | **lenta/protegida** |
| **`PERSONA.md`** (`PROFILE.md`) | Self-model: traços, expertise, backstory que se aprofunda. | média |
| **`VOICE.md`** | Tom, estilo de fala, léxico, o que evitar. | média/rápida |
| **`sections/*.md`** | Blocos modulares compostos no prompt por slots de prioridade. | conforme o bloco |

**Sections** = composição do system prompt por blocos com prioridade, via um **`PromptBuilder`**
(padrão do passo 13 do repo de referência: Identity → Personality → Bootstrap → Runtime → Channel
hint, concatenados). No Okami os slots são: SOUL → VOICE → PERSONA → bootstrap(`AGENT.md`/cron) →
memória → skills → contratos → runtime/channel → overlays. Modular e editável por peça; extensível
(ex.: injeção de memória como camada própria).

### 8.2 Unicidade no nascimento
Ao criar um agente, um passo de **gênese** gera uma identidade distinta (nome, valores, voz,
semente de backstory) — não um default compartilhado. Dois agentes nunca começam iguais.

### 8.3 Evolução da persona
- Sinais: trajetórias (§7) + **"AI self-representation / identity card" do Honcho** (§6.3), que já
  modela o self do agente ao longo do tempo.
- O `learning` propõe **edits versionados** a `VOICE.md`/`PERSONA.md` (e, raramente e sob aprovação,
  a `SOUL.md`) — a persona ganha textura/personalidade com o uso.
- **Guard-rails**: `SOUL.md` (valores) muda devagar e pode exigir aprovação; `VOICE`/`PERSONA`
  evoluem mais rápido. Changelog append-only + rollback. Evita "drift" descontrolado.
- Resultado: o agente vai ficando *mais ele mesmo* — mais criativo e com mais caráter — em vez de
  genérico.

---

## 9. Aprendizado de gosto de design (taste model) ⭐ ✅ `okami/taste.py`

Resolve o pedido: *"recusei o design X → faça outro; aprovei → refine pra aquele; pedi diferente →
perto do que gostei, longe do que recusei."* IMPLEMENTADO: `TasteProfile` (atratores/repulsores+peso)
persistido em `<ws>/.okami/taste.json`. Design = tags+descritor → **vetor esparso** (Counter, cosine,
namespace único → texto livre casa com tags; sem servidor de embedding). `record_feedback(ws, verdict,
descritor)`; `score(cand)`; `steer()` → bloco "PREFIRA/EVITE" injetado no `run_task` quando a tarefa é
de UI (gated por `contracts.ui` ou skill de frontend). CLI `okami taste like|dislike|different|show|
steer`; Telegram `/like /dislike /different`. VERIFICADO ao vivo: curtido +0.69, rejeitado −0.78,
"diferente" −0.20.

### 9.1 Representação
Cada design gerado vira um **vetor de atributos** (tokens extraídos do artefato + do prompt):
paleta/família de cor, densidade, raio de canto, classe tipográfica, arquétipo de layout, estilo
de componente, tags de "vibe". Um **taste profile** por usuário (e por projeto) guarda:
- **Atratores** (designs aprovados) e **Repulsores** (recusados), cada um com **peso/trust** —
  reaproveitando a ideia de trust scoring + `fact_feedback` do holographic (§6.3).

### 9.2 Feedback
Cada interação de design emite evento: `approved` | `rejected` | `want_different`.
- **approved** → vira atrator (peso alto); o estilo pode ser **promovido** para `VOICE.md`/memória
  como preferência durável (§8, §6).
- **rejected** → vira repulsor; regenera afastando-se dele.

### 9.3 Steering na geração (o comportamento que você descreveu)
Ao gerar, injeta o taste profile como restrições/few-shot. Para escolher entre N candidatos:
```
score(c) = w1·sim(c, atratores) − w2·sim(c, repulsores) − w3·sim(c, design_atual)
```
- **"Faça diferente"**: maximiza distância do design atual **e** dos repulsores, **mantendo**
  proximidade aos atratores → novo, mas dentro do que você gosta.
- **"Refine este"**: minimiza distância ao atrator aprovado, ajustando detalhes.
- Sem histórico ainda? Gera variedade e aprende do primeiro feedback.

### 9.4 Relação com os gates
O gate de design system (§4.3) é **hard** (obrigatório: ShadCN/HeroUI, sem CSS feio). O taste é
**soft** (estético/criativo, dentro do que o gate permite). Os dois juntos = bonito **e** correto.

---

## 10. Multi-agente (profiles + workspaces)

- **Profile/Agente** (`workspaces/<id>/AGENT.md`): definição do agente; um **`AgentLoader`** escaneia
  o diretório (padrão do passo 11 do repo). Inclui providers preferidos, skills, contratos, escopo de
  memória, budget e ponteiro p/ a **identidade** (§8).
- **Workspace** (`workspaces/<id>/`): dir isolado com estado/memória/identidade/sandbox próprios.
- **Roteamento por bindings com tiers de regex** (padrão do repo): tier 0 exato → tier 1 regex →
  tier 2 wildcard; primeiro match vence; fallback p/ agente default. Mapeia origem (canal/peer/
  heartbeat) → profile+workspace; mapping origem→sessão persistido. Sessões por (profile×workspace).

### 10.1 Conversa em GRUPO — turn-taking (quem fala, quem cala) ✅
Vários agentes num mesmo grupo (ex.: CTO + 4 managers) conversando **como uma reunião de empresa** —
sem spam, sem precisar de @ toda hora. Problema mal resolvido no Hermes/OpenClaw (feature aberto no
OpenClaw #18869). `okami/group.py` `GroupRoom` (channel-agnóstico):
- **Dispatch + eligibility gating** (anti "LLM stampede"): filtra candidatos por **cooldown**,
  participação recente e **@menção** (que FORÇA).
- **Moderador** (LLM barato, estilo AutoGen SelectorGroupChat): escolhe **quem fala a seguir ou
  NINGUÉM**, por relevância ao **`role`** do agente; prefere o silêncio.
- **Silêncio intencional**: o agente escolhido pode responder **`PASS`** (nada a acrescentar).
- **Cooldown**: falou → cala N turnos (a não ser @mencionado).
- **Cap bot-to-bot**: máx. mensagens de agente seguidas sem humano → evita loop infinito.
- Ex.: usuário fala de Bootstrap com o CTO → CTO responde **e** o manager de UI/UX intervém **uma
  vez** (ShadCN/HeroUI melhor) → depois fica quieto até ser chamado. CLI `okami room "..."`.
- **1 modelo POR AGENTE**: o responder usa `effective_config(global, agent)` → cada agente fala no
  **seu próprio provider/modelo** (CTO no Codex, UI/UX no MiniMax, etc.), credenciais `providers:`
  **globais**; execução **isolada** (1 chamada single-shot/agente, janelas separadas — conversa de
  grupo é FALA, não tarefa). O moderador usa **constrained enum** (id válido ou `none`) → confiável
  até em modelo fraco (Qwen-4b). Decline-and-retry: PASS do eleito não silencia o grupo.
- **Grupo no Telegram** (`GroupEndpoint` + `TelegramGroupChannel`): N bots num mesmo chat — **um
  listener** lê as mensagens humanas (ignora as dos próprios bots → anti-loop) e **cada agente
  responde pela SUA token**. `run_gateway` sobe DMs + grupos juntos. Config: `groups:` em okami.yaml
  (members + moderator.provider + cooldown + max_bot_streak) + `channels.telegram.token` por agente.
- **Orquestração**: um profile delega subtarefas a outros (subagentes isolados). Peer model do
  Honcho (§6.3) casa com profiles ("o que o agente A sabe sobre o projeto/usuário").

---

## 11. Scheduling & Eventos
`apps/scheduler`: **cron** (`okami cron add`), **heartbeat** (pulsos que acordam o agente; é o
contrato do Paperclip §13), **event bus** + triggers (webhook, msg recebida, arquivo alterado,
evento MCP → tarefa de um profile). Toda execução proativa passa pela **mesma máquina de estados
do harness** (§3) — agendado também nunca trava.

## 12. Tools / MCP  ✅
Tools nativas (read/write/list/shell, `remember`/`recall_memory`/`remember_user`, `use_skill`) +
terminais do harness, todas com **args validados** e **try/except** (uma tool nunca derruba o loop).
**Cliente MCP** ✅ (`okami/mcp.py`, stdio JSON-RPC síncrono, sem dep extra): conecta servidores
(`mcp.servers`), lista as tools e as **embrulha como tools nativas** (`mcp__<server>__<tool>`) — entram
no mesmo registry e passam pelas MESMAS invariantes (args, anti-loop, go/no-go §12). `okami mcp` lista.
HTTP/SSE = futuro. Toda tool entra no log append-only (memória §6, learning §7, report Paperclip §13).

## 13. Channels / Gateway ✅ (estrutura robusta estilo OpenClaw)
Gateway **channel-agnóstico**: abstração `Channel` (`channels/base.py`: poll/send/allowed) com
adapter **`TelegramChannel`** — adicionar Slack/Discord = implementar a interface. Por agente: um
Channel (seu bot) → **Sessões por chat** (`Session`: histórico injetado como contexto = continuidade
de conversa) → `runner.run_task` no workspace do agente.
- **Slash commands**: `/new`·`/reset` (limpa a conversa), `/status`, `/stop` (CANCELA de verdade —
  callback `cancel` checado a cada passo do harness), `/yolo`·`/normal` (auto-aprovação por sessão), `/help`.
- **Concorrência**: uma tarefa por sessão (guard `busy`); nova mensagem enquanto ocupado → avisa.
- **Go/No-Go por chat**: respeita o modo (off/yolo/smart/manual) + `/yolo` da sessão; senão pergunta
  no chat (`/yes`·`/no`, timeout fail-closed).
- **Voz** ✅ (`okami/voice/`, opcional `[voice]`): áudio recebido → **Whisper local** (faster-whisper)
  transcreve → vira texto pro harness; resposta → **TTS** (Edge grátis / MiniMax token plan) → enviada
  como áudio. Config `voice.stt`/`voice.tts` (global ou por agente). CLI `okami transcribe`/`okami say`.
- `okami gateway` sobe um long-poll por agente; `allow_chats` por agente; cliente urllib (sem dep).
- **Paperclip** ✅ (`okami/channels/paperclip.py`, §11): control plane que ACORDA o agente num
  *heartbeat*. `run_heartbeat` faz UMA batida: `GET /api/agents/me` → lista issues atribuídas →
  **checkout** (409 = de outro agente, NUNCA repete) → contexto → **harness** (`run_task`) →
  `PATCH` status (done/blocked/in_review). Go/No-Go vira `POST .../interactions` (request_confirmation):
  `--mode defer` adia ações sensíveis p/ confirmação humana (issue fica in_review), `yolo`/`off` auto-aprova.
  Auth `Bearer $PAPERCLIP_API_KEY` + `X-Paperclip-Run-Id`. CLI `okami heartbeat` (uma batida, chamada pelo
  Paperclip) e `okami paperclip` (doctor). Trabalho longo/paralelo = **issue filha** (sem polling).
- **Persistência + retomada de sessão ✅** (estudado em Hermes/OpenClaw). **Modelo 2 CAMADAS estilo
  OpenClaw** (`okami/sessions.py` `TranscriptStore`): `sessions.json` = mapa pequeno de METADADOS
  (`node_count`, `last_role`, timestamps, yolo, overlay, resume_attempts), reescrito **atomicamente**
  (temp+`os.replace`); `<chat>.jsonl` = transcript **APPEND-ONLY** em árvore (`id`/`parentId`), UMA
  linha por turno → nunca reescreve a conversa inteira (crash-safe: uma queda perde no máx. a última
  linha — e o `read` ignora linha truncada; escalável: conversa gigante não vira write gigante).
  `session()` faz rebuild da cauda do transcript → **restart NÃO perde o contexto**. O `_run` faz
  `append` do turno do USER **antes** de rodar → se cai no meio, fica "pendente" (último nó = USER,
  sem AGENTE = `interrupted()`). `/new` ARQUIVA o transcript (`*.reset.jsonl`, não apaga).
  - **Boot**: `prune_sessions` (poda velhas/excedentes, estilo OpenClaw `session.maintenance`:
    `max_sessions`, idade) + `resume_interrupted` — detecta as interrompidas e, por padrão, **AVISA +
    oferece `/retry`** (mecânica Hermes #4493). `gateway.auto_resume: true` re-executa sozinho.
  - **Guarda anti-loop (Hermes #7536 — "sessão travada resume em loop irrecuperável"):** o auto-resume
    conta `resume_attempts` e PARA após `max_attempts` (default 1) — tentou e falhou → avisa em vez de
    re-executar. `/retry` é a retomada manual.
  - Mudanças de persona/feedback valem **na hora** (o `core_block` relê os .md a cada tarefa); só
    `okami.yaml` exige restart. Sessão por agente (mora em `agents/<id>/`).
- **Grupo persistente ✅** (§10): o `GroupEndpoint` grava a conversa do grupo no MESMO transcript
  2-camadas (`.okami/groups/<label>.jsonl` + metadados) — cada fala (humano + cada agente, papel=id) é
  um nó append-only; no boot `_hydrate` faz rebuild da conversa E do turn-taking (turn + cooldowns por
  membro). Restart NÃO perde a reunião nem reabre stampede.
- A seguir: **Slack/Discord** (mesma interface Channel), botões inline, write-lock p/ concorrência
  multi-processo, nós de SUMMARY no transcript (compaction §6.4).

## 14. Segurança e sandbox
Docker por padrão; segredos fora do repo; log append-only imutável; persona/skills auto-geradas
podem exigir aprovação (§7, §8). **Go/No-Go** (`core/approval.py`, estilo Hermes): o agente PODE editar
qualquer arquivo a pedido; ações sensíveis (identidade, `.env`/segredos, `rm -rf`, `git push`, `sudo`,
publish) param e pedem aprovação. `classify()` dá **categoria + risco**. **Modos**: `manual` (pede
sempre), `smart` (auto-aprova risco baixo, pergunta o resto), `off` (sem prompts), **`yolo`** (bypass
na sessão — `--yolo`/`-y`, futuro `/yolo`). Prompt com **4 opções**: allow once · **allow session**
(lembra a categoria) · **always allow** (persiste em okami.local.yaml) · deny. **Fail-closed** sem
resposta (Telegram: botões + timeout). Integra com governança do Paperclip (§13).

---

## 15. Fluxo (exemplo: "faça um frontend com ShadCN, mas diferente do anterior")
1. Mensagem (Telegram/…) → gateway → profile+workspace (§10) → core, com **identidade** do agente
   (SOUL/VOICE/PERSONA §8) e **capability profile** do LLM ativo (§3.5).
2. Router → frontend → contrato `ui=shadcn` ativo → skill `frontend-shadcn` forçada (§4.2).
3. **Taste** (§9): "diferente" → gera candidatos longe do design atual e dos recusados, perto dos
   aprovados.
4. Harness `IN_PROGRESS`, `exitCriteria=[build, gate UI, testes]`. Ação obrigatória a cada turno
   (§3.2); watchdog (§3.3); auto-compaction promove fatos se a janela encher (§6.4).
5. `task_complete` → **gates** (§4.3) hard + crítico de **taste** soft (§9.4). Falhou? violações →
   volta ao 4.
6. COMPLETE → resposta ao canal (+ custo/auditoria ao Paperclip se veio de heartbeat).
7. **Pós-tarefa** (§7): se você aprovar/recusar, atualiza taste (§9); reflexão destila skill/regra,
   ajusta capability profile (§3.5) e propõe evolução de VOICE/PERSONA (§8).

---

## 16. Riscos a validar
- **Claude Code/Codex via sub**: auth headless + ToS. Plano B: API key.
- **Intent–Action reconciler**: calibrar p/ não punir texto explicativo legítimo.
- **Gates de UI**: checks AST por lib + limiar `minComponentReuse` sem virar burocracia.
- **Paperclip heartbeat**: ✅ contrato confirmado e implementado (§13) — validar AO VIVO numa empresa
  real (endpoints/JSON podem variar por versão; o cliente é defensivo). Falta: custo/auditoria explícitos.
- **Honcho**: self-hosted vs cloud; latência da Dialectic API → manter assíncrono/observador.
- **Holographic (HRR)**: capacidade vs ruído por vetor; **não** repetir a degradação silenciosa do
  Hermes (numpy dep declarada + warning + doctor).
- **Auto-compaction**: nunca classificar decisão/contrato como ruído; testes adversariais.
- **Evolução de persona**: evitar drift; SOUL.md protegido + changelog + rollback + aprovação.
- **Taste model**: evitar overfitting a 1–2 feedbacks; cold-start com variedade; pesos `w1..w3`
  calibráveis; separar gosto (soft) de contrato (hard).
- **Capability-adaptive**: probe de calibração barato e confiável; defaults sãos por tier.
```
