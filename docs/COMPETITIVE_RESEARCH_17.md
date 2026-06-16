# Pesquisa Competitiva #17 — Hermes × Okami, os 3 gaps do #16 FECHADOS

**Data:** 2026-06-16
**Alvo:** `NousResearch/hermes-agent` (checkout `/private/tmp/hermes-agent-main`)
**Contexto:** o #16 achou 3 gaps reais onde o Hermes liderava. Esta rodada **implementou os três** com TDD,
caçou bugs no código novo (2 subagentes adversariais → 4+ defeitos corrigidos) e refez o comparativo.
**2.525 testes passando** · ruff/bandit-HIGH/secret-scan limpos.

---

## ✅ Os 3 gaps do #16 — status

| Gap | Status | Como ficou |
|---|---|---|
| **Mixture-of-Agents** | ✅ **FECHADO** | `okami/llm/mixture.py` + tool `mixture_of_agents` + `okami moa`. Port fiel (fan-out paralelo, min-success, fallback à 1ª referência). Diferença HONESTA (design, não gap): usa os providers JÁ configurados (assinatura-only), não o pool OpenRouter. Bônus de segurança: respostas de referência vão **embrulhadas como dado não-confiável** no system do aggregator (provider comprometido não injeta instrução). |
| **Google Code Assist** | ✅ **FECHADO p/ o caso comum** | `okami/llm/code_assist.py` + transporte `gemini_cloudcode` + `okami gemini login/status/quota`. OAuth PKCE COMPLETO (callback local valida state/CSRF, troca code→token, persiste 0600, renova via refresh). Mais FINO que o Hermes em: onboarding de tier + LRO polling de provisionamento, fallback de endpoint sandbox, streaming SSE. Esses são UX de primeiro-uso, não bloqueiam o uso diário. |
| **LSP** | ✅ **FECHADO (base) + ampliado** | O Okami **já** enriquecia o write/edit com diagnostics do pyright (one-shot, pesquisa #7 item 16, `okami/core/lsp/` ligado em `files.py:semantic_delta`). O #17 **ampliou**: `okami/lsp/` com protocol JSON-RPC genérico, range_shift diff-aware, reporter, workspace git-gateado, catálogo multi-servidor (pyright/gopls/ts/rust/bash/clangd) + `okami lsp status/list/which`. Gap restante vs Hermes: o cliente async PERSISTENTE (diagnostics em streaming entre edições, multi-linguagem) + auto-install — o Okami é one-shot por arquivo. |

---

## 🔭 Gaps REAIS que ainda restam (Hermes lidera)

Depois de filtrar os falsos-positivos do scan (o Okami JÁ tem Discord, swarm, `secret_sources`/Bitwarden,
transcrição de áudio/AudioAnalyze, TTS — não são gaps):

| Gap | Arquivo no Hermes | Severidade | Nota honesta |
|---|---|---|---|
| **Computer Use (controle de desktop)** | `tools/computer_use/` | **ALTA** | O Hermes controla mouse/teclado do macOS (cua-driver) gateado por aprovação. O Okami **não** — é agente de TUI/web/gateway, não automador de desktop. Fora do escopo atual por design, mas é o maior diferenciador. |
| **Geração de VÍDEO** | `tools/video_generation_tool.py` + registry | **MÉDIA** | text→video / image→video via providers plugáveis (Veo3/Kling/Pixverse). O Okami tem image-gen, não vídeo. A arquitetura de registry já existe (image), faltaria o backend. |
| **LSP persistente/streaming + auto-install** | `agent/lsp/client.py` + `manager.py` + `install.py` | **MÉDIA** | cliente async que mantém os servidores VIVOS e faz sync de documento (didOpen/didChange) com diagnostics contínuos; `hermes lsp install`. O Okami é one-shot (sobe→coleta→morre) — funciona, mas não dá o feedback contínuo tipo-IDE. |
| **Code Assist: onboarding de tier + LRO + SSE** | `agent/google_code_assist.py` | **BAIXA-MÉDIA** | detecção de tier, `onboardUser` com polling de operação longa, VPC-SC, streaming. UX de primeiro-uso. |
| **X/Twitter (Grok) search** | `tools/x_search_tool.py` | **BAIXA** | busca no X via API do xAI. Nicho; o Okami tem `web_search` (genérico). |
| **Home Assistant** | `tools/homeassistant_tool.py` | **BAIXA** | IoT/casa inteligente. Nicho. |

---

## ✅ Onde o Okami está À FRENTE do Hermes

- **PluginContext trust-gated** — plugin não-confiável não troca de provider (o Hermes deixa qualquer plugin usar qualquer modelo).
- **Dashboard zero-dep + self-hosting com TLS + token forçado** — sem Node/Electron; bind público exige token (o Electron do Hermes é localhost-only).
- **`provider check --live`** — self-test de transporte com round-trip real (o Hermes não tem).
- **`okami cost` por-vendor** — telemetria que separa quem gastou, com a constraint de assinatura ("incluído", nunca inventa $).
- **Streaming token-a-token** na TUI e no Telegram.
- **Mixture-of-Agents sem lock-in** — usa os providers configurados, não exige OpenRouter.
- **`gemini_cloudcode`** — tier GRÁTIS de Gemini (o Hermes usa o SDK pago padrão p/ Gemini nativo).

---

## 📌 Veredito #17

- Os **3 gaps do #16 estão fechados** (MoA e Code Assist plenos no caso comum; LSP com a base já em produção + camadas ampliadas — falta o cliente persistente).
- Paridade global subiu para **~90%**: os gaps restantes se concentram em **automação de desktop (computer-use)**, **vídeo-gen** e **LSP streaming** — nenhum quebra o loop do agente; o Okami é focado e à frente em segurança de plugin, distribuição zero-dep e observabilidade.
- **Próxima rodada (candidatos priorizados):** (1) cliente LSP persistente/streaming, (2) geração de vídeo (reusa o registry de mídia), (3) Code Assist first-run (onboarding/LRO/SSE). Computer-use fica como decisão de escopo (vale a pena o Okami virar automador de desktop?).
