# Pesquisa Competitiva #19 — Hermes × Okami, rumo à paridade total

**Data:** 2026-06-16
**Alvo:** `NousResearch/hermes-agent` (checkout `/private/tmp/hermes-agent-main`)
**Contexto:** o #18 fechou os 3 gaps grandes do #17 e apontou que o que restava era **cauda-longa**:
integrações de nicho + breadth de canais. Esta rodada **fechou TODOS os gaps reais** (exceto um, nicho
documentado), com TDD e caça de bugs (1 path-injection + 1 perf corrigidos). **2.578 testes passando** ·
ruff/bandit-HIGH/secret-scan limpos.

> **Sobre "aparece gap novo a cada pesquisa":** não é a ferramenta mudando. São (1) **falsos-positivos** dos
> subagentes exploradores — cada um faz um scan novo e às vezes "acha" gap que o Okami já tinha (peguei
> Discord, Blueprints, browser-supervisor, secret_sources, swarm, transcrição como falsos); e (2) a
> **cauda-longa real** do Hermes (canais regionais, integrações de IoT) que só aparece varrendo tudo. Esta
> rodada fechou a cauda-longa inteira e verificou cada gap com `grep` antes de aceitar.

---

## ✅ O que esta rodada FECHOU (tudo com TDD)

| Gap (do #18) | Fechado em |
|---|---|
| **x_search** (Grok/xAI no X/Twitter) | `okami/integrations/x_search.py` + tool |
| **Home Assistant** (IoT) | `okami/integrations/homeassistant.py` + tool (domínios perigosos bloqueados) |
| **Feishu/Lark** (docs) | `okami/integrations/feishu.py` + tool (doc_token validado anti-traversal) |
| **Vídeo: registry de backends** | `VIDEO_BACKENDS` (veo3/kling/pixverse) + `okami video --list` |
| **LSP wired no write + auto-install** | `okami/lsp/session.py` (multi-linguagem) + lazy_deps `lsp.pyright` + `okami lsp install` |
| **DingTalk / WeCom / QQBot** | `okami/channels/regional.py` (outbound) |
| **WhatsApp / Signal / Matrix / SMS / BlueBubbles / Weixin** | `okami/channels/messaging.py` (outbound) |
| **Copilot como backend** | transporte `copilot_cli` (`okami/llm/transports.py`) |

### Canais: de 5 → **14 plataformas**
Telegram · Slack · Discord · Email · Mattermost · DingTalk · WeCom · QQBot · WhatsApp · Signal · Matrix ·
SMS · BlueBubbles · Weixin. (Outbound já entregue; o inbound de cada uma — webhook/sync/daemon com cripto
— é um épico próprio, documentado como follow-up.)

---

## 🐛 Caça de bugs (#19)

- **Feishu path-injection** (real): `doc_token` ia cru na URL → agora validado por `^[A-Za-z0-9_-]+$`.
- **LSP perf**: gate de git PRIMEIRO no `multi_lang_delta` (antes de `shutil.which` dos servers) — write
  fora de repo não paga scan de PATH.
- defesa: erro do vendor nas tools novas (x_search/feishu) passa pelo `redact`.
- HA url crua é por DESIGN (Home Assistant mora em localhost/LAN; SSRF-guard bloquearia o uso legítimo).

---

## 🔭 Gap que SOBRA (verificado com grep — único genuinamente ausente)

| Gap | Hermes | Severidade | Decisão |
|---|---|---|---|
| **Yuanbao** | `gateway/platforms/yuanbao*.py` | **muito baixa** | plataforma consumer-AI do DingTalk (China); proto proprietário + mídia/stickers. **Skip deliberado** — nicho regional fora do público-alvo (PMEs). |
| **computer-use embutido** | `tools/computer_use/` | — | **decisão de escopo** (#17): alcançável via MCP trust-gated, núcleo fica fail-closed. |
| **inbound dos 9 canais novos** | vários | baixa | outbound já entregue (o caso de bot mais comum); inbound = follow-up. |

Tudo o mais do Hermes (todas as tools, todos os adapters de provider, automação, segurança, memória,
aprendizado, LSP, mídia) está presente no Okami — verificado arquivo a arquivo.

---

## 📊 Paridade — metodologia honesta

- **Por PRESENÇA de capacidade** (o Okami FAZ aquilo, em alguma forma): **~98%**. A única capacidade
  totalmente ausente é a plataforma **Yuanbao** (nicho). Computer-use é decisão de escopo (alcançável via
  MCP). 14/15 plataformas de canal presentes.
- **Por completude fina** (contando o inbound de cada canal novo como sub-feature): ~94–95% — os 9 canais
  novos são outbound-only por enquanto.

**Veredito: ~98% de paridade por presença de capacidade.** O que falta é deliberadamente fora de escopo
(Yuanbao nicho; computer-use por segurança) ou follow-up incremental (inbound dos canais novos).

---

## ✅ Onde o Okami LIDERA

- **Trust model**: PluginContext trust-gated + MCP trust store (go/no-go por capability).
- **Distribuição**: dashboard zero-dep + self-hosting com TLS + token forçado.
- **Observabilidade**: `okami cost` por-vendor + `provider check --live`.
- **UX**: streaming token-a-token (TUI + Telegram).
- **Multi-agente**: roteamento por binding + swarm + kanban.
- **Multi-vendor sem lock-in**: MoA nos providers configurados; `gemini_cloudcode` (tier grátis); Copilot via CLI.
- **LSP**: cliente persistente + multi-linguagem wired no write + auto-install (pyright via PyPI).
- **Vídeo**: registry de backends nomeados com capabilities refletidas.

---

## 📌 Próximos passos honestos (incrementais, não-bloqueantes)

1. **Inbound dos canais novos** (Signal/Matrix são pollable; WhatsApp/SMS/WeCom precisam de callback+cripto).
2. **Yuanbao** — só se o público-alvo pedir (nicho China).
3. **LSP async de fundo** — hoje é síncrono-por-edição; um loop de fundo daria feedback contínuo tipo-IDE.
