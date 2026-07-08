# Okami Agent — `v0.10.0-beta` "A Release da Auditoria" 🐺

**Primeiro beta.** 193 commits · 403 arquivos · +23.841/−1.021 linhas · suíte **2.408 → 3.364 testes**
desde o `v0.9.0-alpha` (2026-06-16).

> ⚠️ **Beta.** A superfície de comandos e config ainda pode mudar até a GA. Recomendado para uso real
> (inclusive em VPS 24/7) — mas rode `okami policy check --strict` antes de expor publicamente. Feedback
> é muito bem-vindo. Ver o [CHANGELOG](CHANGELOG.md) completo.

🌐 Site: **https://okamiagent.com** · 📚 Docs: **https://okamiagent.com/docs**

---

## A história desta release

O dono reportou algo simples e desconfortável: em uso real, com minimax, **o agente parecia burro e
lento**. Tarefa simples travava, resposta demorava, formatação chegava quebrada no Telegram. Não dava pra
consertar isso com um patch qualquer — dava pra confundir sintoma com causa fácil demais.

Então rodamos uma **auditoria E2E completa vs Hermes, com 8 agentes**, reproduzindo o uso real ponta a
ponta em vez de confiar só na suíte de testes. O achado central: um **probe de tool-calling nativo
quebrado** (`TypeError` silencioso) degradava **todo provider não-hardcoded** — incluindo minimax — para o
rail JSON-em-texto, sem avisar ninguém. Daí em diante era efeito dominó: thinking vazando no texto,
contexto inchando, retry zero porque só havia 1 credencial, tool-results cortados num teto fixo de 8K
(1.5K pro modelo fraco) mesmo quando a janela do modelo era grande, Telegram dividindo a resposta ANTES de
formatar (perdendo tag HTML no meio do corte), STT e resumo de link bloqueando o poll loop de **todos os
chats** — não só do chat que pediu.

Corrigimos em **3 ondas por impacto** — P0 (`7939d6e`, 6 bugs críticos de uso real), P1 (`c030281`,
memória poluída + o conflito streaming×rail-nativo que a própria correção do P0 expôs) e P2 (`29d648e`,
quick-wins de qualidade em harness/gateway/run/TUI) — mais uma **revisão adversarial pós-campanha** que
achou e fechou 4 regressões que a própria campanha introduziu.

**Resultado, no mesmo cenário E2E real (minimax):** antes, `BLOCKED` / alucinando tool-call / vazamento de
`<think>` no texto. Depois, **`COMPLETE`** com verificação mecânica (sha256), formatação íntegra no
Telegram, e `tokens_in` caindo de 6.4-7K para **2.7K** por turno — o agente ficou mais rápido porque parou
de carregar lixo em cada turno, não porque ficou "menos cauteloso".

Esse é o argumento do beta: não é uma feature nova que justifica a promoção — é a **maturidade** de ter
caçado a causa-raiz num cenário real, em vez de empilhar mais capacidade em cima de uma degradação
silenciosa.

## ✨ Highlights

- **Probe de tool-calling nativo corrigido** — o `TypeError` que derrubava silenciosamente TODO provider
  não-hardcoded para o rail JSON-em-texto está morto; o veredito agora persiste em disco
  (`native_verdict.json`) e hints do catálogo pulam o probe quando já sabem a resposta.
- **Orçamento de tool-result escala com a janela do modelo** — 15%/30% do contexto (floor 8K/16K, cap
  100K/200K) em vez do corte fixo de 8K/1.5K flat; modelo com janela grande não perde a saída de uma
  ferramenta por um teto pensado pro modelo pequeno.
- **Retry desacoplado do tamanho do key-pool** — com 1 credencial só, você tinha zero retry; agora o
  default é 3, com timeout por tier (local 1800s / cloud 600s, antes 150s flat matava geração longa local).
- **Telegram renderiza antes de dividir** — resposta acima de 4096 chars não perde mais a formatação no
  meio do corte; divide por unidades UTF-16 com tags HTML balanceadas entre as partes.
- **STT e resumo de link não travam mais o gateway inteiro** — rodam fora do poll loop compartilhado
  (spawn por chat); antes, um áudio demorado num chat travava a resposta de todos os outros.
- **Memória para de virar depósito de lixo mecânico** — só `remember`/`remember_user`/`reflect` escrevem
  no `MEMORY.md` agora; dedup near-duplicate por Jaccard e gate de durabilidade (≥2 passos com efeito) pra
  memória ranqueada.
- **`streaming` respeita o rail nativo** — a checagem de streaming agora consulta se o provider suporta
  tools nativas ANTES de decidir por tier; ligar streaming não quebra mais o payload de tools do rail nativo.
- **`okami run` para de alucinar tool-call** — aviso explícito no system prompt quando não há tools
  disponíveis, mais strip de `<think>` no output exibido.
- **loop-guard avisa antes de bloquear** — warn no repeat #2, bloqueia só no #5 (paridade Hermes
  warn-then-block), em vez de travar na primeira repetição suspeita.
- **verify-on-stop** — `task_complete` com efeito não verificado ganha 1 nudge antes de ser aceito, sem
  risco de loop infinito.
- **`spawn` virou tool core** — modelo fraco agora decompõe tarefa em subagentes por padrão, em vez de
  tentar (e falhar) fazer tudo num turno só.
- **`okami prompt-size`** — breakdown de chars/tokens por seção do prompt, pra diagnosticar inchaço sem
  adivinhar.
- **~190 commits de paridade multi-vendor/Telegram/gateway/plugins** desde o alpha — ver seções abaixo.

## 🧠 Harness / Loop

- Loop-guard warn-then-block (repeat #2 avisa, #5 bloqueia); contador unificado fecha loophole
  nome-ruim↔arg-faltando.
- Verify-on-stop: nudge de verificação antes de aceitar `task_complete` com efeito não verificado.
- Orçamento de tool-result escalando com a janela (15%/30%, floor 8K/16K, cap 100K/200K).
- `run_shell` preserva output parcial no timeout; `run_parallel` com teto de batch 420s.
- `spawn` promovido a tool core; `okami prompt-size` (novo comando de diagnóstico).
- Reasoning replay do Codex (`encrypted_content`) no mesmo turno, `store=false` (paridade Hermes).

## 🌐 Providers / Multi-vendor

- Probe de tool-calling nativo corrigido (era o bug raiz da campanha) + veredito persistido em disco.
- Retry desacoplado do key-pool (default 3) + timeout por tier (local 1800s / cloud 600s).
- `streaming_enabled` consulta suporte nativo antes do tier — sem mais conflito streaming×rail-nativo.
- Reasoning-echo (DeepSeek-reasoner/Kimi/MiMo) sem 400 em multi-turn tool-call.
- Recalibração de contexto via erro reportado pelo provider (429 de tier long-context compacta e retenta).
- OpenRouter routing hints (`extra_body.provider`); `num_ctx` do Ollama validado via `/api/show`.

## 💬 Telegram

- HTML renderizado por completo ANTES de dividir (≤4096 unidades UTF-16, tags balanceadas entre cortes).
- Task lists GFM (`- [ ]`/`- [x]`) viram caixinhas ☐/☑.
- Entity flattening inbound — mensagem recebida formatada vira markdown pro modelo.
- Clarify com botões inline; batch-delay adaptativo no streaming-by-edit; `typed_command_prefix` por canal.

## 🛰️ Gateway / VPS

- STT/link-summary fora do poll loop compartilhado (spawn por chat); cap de fila 32 + demotion guard.
- LRU de sessões vivas, dedup de reenvio, auto-resume só de interrupção recente (<1h).
- Multi-agente supervisor: `okami agent up|down|status|supervise` (watchdog + auto-restart por processo).
- Provisão remota VPS-first: o agente bootstrappa o PRÓPRIO acesso SSH/GitHub, sem depender da máquina do
  usuário. `system_monitor`, `restart_gateway`, `env_check`.
- Portabilidade Windows/Mac/Linux: 14 breaks reais corrigidos (auditoria adversarial de 7 finders).

## 🧠 Memória

- `_extract_on_complete` para de despejar "goal → result" cru no `MEMORY.md`.
- Dedup near-duplicate por Jaccard; gate de durabilidade (≥2 passos com efeito) pra memória ranqueada.
- `LayeredMemory.inject` com preâmbulo único + dedup 120-chars (antes: volume 2x e preâmbulos duplicados).

## 🖥️ TUI / CLI

- Bracketed-paste defensivo, focus-report ignorado (iTerm2/Ghostty), repaint em SIGWINCH.
- `okami sessions delete`, version-drift no `doctor`, verbos pt-BR nos tool-calls + `[exit N]` em falhas.
- Mensagens proativas do cron espelhadas no transcript (PII mascarado na cópia da sessão).

## 🛡️ Segurança / Plugins

- Bit `+x` restaurado nos hooks builtin (`security-guidance`/`disk-cleanup`) — estavam vetando TODA tool
  com exit 126 silencioso.
- Plugins com lifecycle completo: `register_context`, `register_command`, `ctx.llm.complete` trust-gated.
- Edit fuzzy normaliza unicode→ASCII (aspas curvas/travessão/nbsp não derrubam mais a edição).

## ✅ Release verification

- **3.364 testes** passando (`uv run pytest -q`).
- **Lint**: `ruff check okami tests` limpo. **Segurança**: `bandit -c pyproject.toml -r okami` limpo.
- **Conformance estrita**: `okami policy check --strict` conforme na postura versionada.
- Reprodução local:
  ```bash
  uv sync --frozen
  uv run pytest -q
  uv run ruff check okami tests
  uv run bandit -c pyproject.toml -r okami -q
  uv run okami policy check --strict
  ```

## ⚠️ Beta — o que ainda pode mudar

- Comandos e chaves de config ainda podem mudar até a GA (sem promessa de estabilidade de superfície).
- Recomendado pra uso real (VPS 24/7 inclusive), mas rode `okami policy check --strict` antes de expor
  publicamente e acompanhe o [CHANGELOG](CHANGELOG.md) a cada atualização.
- O restante do roadmap de auditoria vs Hermes (env auto-repair mais profundo, cauda-longa de canais de
  nicho) segue em ondas — nenhum gap crítico de uso real conhecido nesta release.

## 🚀 Instalação / upgrade

```bash
# instalação nova (macOS / Linux)
curl -fsSL https://raw.githubusercontent.com/OkamiOps/Okami-Agent/main/scripts/install.sh | bash
# Windows (PowerShell)
irm https://raw.githubusercontent.com/OkamiOps/Okami-Agent/main/scripts/install.ps1 | iex

# upgrade de instalação existente
uv tool upgrade okami-agent   # ou: pip install -U okami-agent

okami setup     # configura em 2-3 cliques
okami doctor    # confirma que a versão instalada bate com o pyproject (sem version-drift)
okami chat      # conversa no terminal
```

Nenhuma migração manual de config é necessária — `okami.yaml`/`okami.local.yaml` existentes continuam
válidos.

## 📄 License

**MIT** ([LICENSE](https://github.com/OkamiOps/Okami-Agent/blob/main/LICENSE)) © 2026 OkamiOps — use it,
fork it, ship it commercially, no strings attached and no warranty.

## 🔗 Links

- 🌐 Landing: https://okamiagent.com
- 📚 Documentação: https://okamiagent.com/docs
- 💻 Agente (este repo): https://github.com/OkamiOps/Okami-Agent
- 🎨 Landing page (fonte): https://github.com/OkamiOps/Okami-Agent-LP
- 📋 Changelog completo: [CHANGELOG.md](CHANGELOG.md)
