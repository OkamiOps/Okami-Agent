# Pesquisa Competitiva #16 — Hermes × Okami, pós-implementação das 6 ideias-forward

**Data:** 2026-06-16
**Alvo:** `NousResearch/hermes-agent` (checkout `/private/tmp/hermes-agent-main`)
**Contexto:** o #15 declarou 100/100 de paridade FUNCIONAL e listou 6 "ideias-forward" honestas (coisas que
o Okami AINDA não fazia, fora das 13 áreas). Esta rodada **implementou as 6**, caçou bugs no código novo
com 3 subagentes adversariais (4 defeitos reais corrigidos com TDD) e refez o comparativo p/ ver o que mais
o Hermes tem. **2.468 testes passando · ruff/bandit/secret-scan limpos.**

---

## ✅ As 6 ideias-forward do #15 — TODAS entregues nesta rodada

| # | Ideia-forward | Entregue | Onde |
|---|---|---|---|
| 1 | **Streaming token-a-token** (TUI + Telegram) | ✅ | `okami/llm/streaming.py`, atrás de `harness.streaming` (default OFF) |
| 2 | **Chrome/janela nativa** sem Electron | ✅ | `okami desktop --native` → pywebview (lazy `desktop.webview`), fallback chrome `--app` → browser |
| 3 | **PluginContext trust-gated** | ✅ | `okami/plugins.py` — `resolve_provider` recusa override de provider p/ plugin não-confiável; confiável só dentro da `allowed_providers` |
| 4 | **Validação ao vivo dos providers nativos** | ✅ | `okami provider check --live` → chamada REAL ao vendor se há credencial, senão pula com graça (`live_check_transport`) |
| 5 | **Telemetria de custo por-vendor** | ✅ | `okami cost [--json]` — `summarize_by_vendor` + `vendor_cost_rows`; assinatura = "incluído" (nunca inventa $) |
| 6 | **Self-hosting do dashboard** | ✅ | `okami gui --host 0.0.0.0 --tls-cert --tls-key` — bind público EXIGE token (`public_bind_needs_token`); TLS via SSLContext |

### Caça de bugs (3 subagentes adversariais sobre o código novo) → 4 fixes com TDD
1. **streaming**: `on_token` (display) virou best-effort — um erro na TUI/edição NÃO trunca a saída do
   modelo nem mascara como falha de provider (era: exceção do display devolvia texto PARCIAL como completo).
2. **provider check --live**: erro do vendor passa pelo `redact` antes de reportar (erro de auth pode
   embutir a credencial — hard constraint "nunca ecoar segredo").
3. **summarize_by_vendor**: `served_by` malformado ("/modelo") não cria mais bucket `""` (vazio) → "—".
4. **serve_dashboard**: meia-config de TLS (só cert OU só key) agora ERRA em vez de servir HTTP em
   silêncio (footgun de achar que está sob TLS e não estar).

*(Falsos-positivos descartados após ler o código: `SSLContext.wrap_socket` NÃO é deprecado — o deprecado
era o `ssl.wrap_socket` de módulo; o bucket "—" de uso não-atribuído é por design; validar a string de
trust com `__post_init__` quebraria o fail-safe atual.)*

---

## 🏆 Paridade FUNCIONAL por área — segue 13/13 em 100

As 13 áreas do #15 continuam em paridade. As 6 entregas acima eram EXTRAS (acima da paridade), e ainda
puxam o Okami **à frente** do Hermes em vários pontos (tabela na seção "Onde o Okami está à frente").

---

## 🔭 O que o comparativo #16 ACHOU de NOVO (gaps reais ainda não capturados)

A varredura do `hermes_cli` inteiro (93 módulos de agent + 88 tools + 31 de gateway) achou **3 capacidades
reais** que o Okami ainda não tem — confirmadas lendo o código do Hermes:

| Gap | Arquivo no Hermes | O que é | Severidade | Recomendação |
|---|---|---|---|---|
| **Mixture of Agents (MoA)** | `tools/mixture_of_agents_tool.py` | roda N modelos de referência em paralelo e sintetiza a melhor resposta com o modelo mais forte | **ALTA** | implementar como tool — é amplificação de raciocínio real; cabe usar SÓ os providers que o dono já tem (sem OpenRouter obrigatório), respeitando a constraint de assinatura |
| **Google Code Assist** | `agent/google_code_assist.py` | acesso ao tier GRÁTIS de Gemini via cloudcode-pa (detecção de tier, onboarding, quota, VPC-SC) — não é o SDK comum | **MÉDIA** | implementar como transporte opcional; dá Gemini grátis a quem tem conta Google. Vale quando precisarmos de um vendor "free fallback" |
| **LSP server subsystem** | `agent/lsp/` (10 módulos) | o agente VIRA um language server (diagnostics, símbolos de workspace, sync de documento) p/ IDE | **MÉDIA** | maior esforço; o Paperclip/ACP do Okami é client-only. Nice-to-have, prioridade menor |

Gaps menores/de nicho descartados como não-prioritários: vídeo-gen (temos image-gen), HomeAssistant,
canais geográficos (WeChat/DingTalk/Signal/SMS — o Okami cobre os mainstream), schema-repair explícito de
Moonshot/Gemini (o litellm já absorve 99% dos casos), computer-use de desktop (fora do escopo TUI/web).

---

## ✅ Onde o Okami está À FRENTE do Hermes (depois desta rodada)

- **PluginContext trust-gated** — o Hermes deixa qualquer plugin chamar qualquer modelo; o Okami trava
  override de provider por confiança + allowlist. (segurança de distribuição de plugin de terceiro)
- **Dashboard zero-dep + janela nativa pywebview** — mesmo job do React/Electron do Hermes, sem
  Node/Electron; roda em VM enxuta/air-gapped. + **self-hosting com TLS + token forçado** (o Electron do
  Hermes é localhost-only).
- **`provider check --live`** — self-test de transporte (capacidade + tráfego real opcional); o Hermes não
  tem round-trip de prova.
- **`okami cost` por-vendor** — telemetria de custo que separa quem gastou, com a constraint de assinatura
  ("incluído", nunca inventa $).
- **Streaming token-a-token** na TUI e no Telegram (o Hermes mostra por-edição no fim do turno).

---

## 📌 Veredito #16

- As 6 ideias-forward do #15 estão **todas implementadas, testadas e em produção** (commit/push feitos).
- Paridade funcional segue **100/100** nas 13 áreas; as entregas desta rodada colocam o Okami à frente em
  segurança de plugin, distribuição zero-dep, observabilidade de custo e UX de streaming.
- O comparativo revelou **3 gaps reais novos** (MoA, Google Code Assist, LSP). Nenhum estava no escopo
  deste goal — ficam como **candidatos priorizados p/ a próxima rodada**, sendo o **MoA** o de maior valor.
