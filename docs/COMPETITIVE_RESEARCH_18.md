# Pesquisa Competitiva #18 — Hermes × Okami, os 3 gaps do #17 endereçados

**Data:** 2026-06-16
**Alvo:** `NousResearch/hermes-agent` (checkout `/private/tmp/hermes-agent-main`)
**Contexto:** o #17 deixou 3 gaps reais. Esta rodada endereçou os três (2 fechados, 1 decisão de escopo
soberana), caçou bugs no código novo (subagente adversarial → **SSRF real corrigido** + 1 dedup), e refez
o comparativo. **2.539 testes passando** · ruff/bandit-HIGH/secret-scan limpos.

---

## ✅ Os 3 gaps do #17 — status HONESTO

| Gap | Status | Detalhe |
|---|---|---|
| **Cliente LSP persistente/streaming** | ✅ **fechado (núcleo)** — ⚠️ thinner que o Hermes | `okami/lsp/client.py` (PersistentLspClient mantém o server vivo, didOpen→didChange, thread leitora) + `okami/lsp/pool.py` (1 server por (binário, raiz), reuso) + `okami lsp probe`. Fecha o cold-start (~8s/edição). **Ainda mais fino**: é síncrono/sob-demanda (não um loop async de fundo contínuo); não auto-instala binário; e ainda NÃO é o default no caminho do write (o `semantic_delta` segue usando o one-shot do pyright, já testado). Próximo passo deliberado (precisa de lifecycle de sessão). |
| **Geração de vídeo** | ✅ **fechado (funcional)** | `okami/llm/videogen.py` (provider-driven via `media.video`, síncrono + poll assíncrono, **download SSRF-guarded** pelo net_guard) + tool `generate_video` + `okami video`. **Mais fino**: 1 endpoint genérico configurável vs o registry de backends nomeados do Hermes (Veo3/Kling/Pixverse) com reflexão de capabilities + áudio. Troca discoverability por soberania (traga seu endpoint). |
| **Computer-use** | ✅ **decisão de escopo soberana** (não embutido) | `docs/COMPUTER_USE.md`: o Okami NÃO embute um automador de desktop (conflita com fail-closed). A capacidade é **alcançável via servidor MCP de computer-use trust-gated** (untrusted → go/no-go por ação). O núcleo fica mínimo; quem precisa, conecta o MCP. É uma fronteira honesta, não um buraco. |

---

## 🔭 Gaps que REALMENTE restam (filtrados os falsos)

O scan listou vários "gaps" que o Okami JÁ tem — verificados e descartados: **Blueprints**
(`okami/automation/blueprints.py` + `okami blueprint`), **browser supervisor CDP**
(`okami/integrations/browser_supervisor.py`), Discord, swarm/kanban, secret_sources/Bitwarden,
transcrição de áudio, TTS, MCP, image-gen, mixture-of-agents, Code Assist, cost telemetry. O que sobra:

| Gap | Arquivo no Hermes | Severidade | Nota honesta |
|---|---|---|---|
| **LSP async de fundo + wired no write + auto-install** | `agent/lsp/manager.py` + `install.py` | **MÉDIA** | o Hermes roda o LSP num loop async de fundo e injeta diagnostics em TODO write; auto-instala o binário. O Okami tem o cliente persistente (reuso) mas síncrono e ainda não é o default do write. É o único forward item in-scope de peso. |
| **Vídeo: registry de backends nomeados + áudio** | `tools/video_generation_tool.py` + `plugins/video_gen/*` | **BAIXA-MÉDIA** | Veo3/Kling/Pixverse com schema dinâmico por backend (durações/aspect/áudio). O Okami é 1 endpoint genérico. |
| **Home Assistant** | `tools/homeassistant_tool.py` | **BAIXA** | IoT/casa inteligente. Nicho. |
| **Feishu/Lark** | `tools/feishu_doc_tool.py` | **BAIXA** | plataforma enterprise chinesa. Regional. |
| **X/Twitter (Grok) search** | `tools/x_search_tool.py` | **BAIXA** | nicho; o `web_search` (DDGS) cobre o caso geral. |

Nenhum desses quebra o loop do agente; os de baixa severidade são nicho/regional (decisão de produto, não dívida técnica).

---

## ✅ Onde o Okami LIDERA o Hermes

- **Trust model**: PluginContext trust-gated + MCP trust store (untrusted→reviewed→trusted, go/no-go por capability).
- **Distribuição**: dashboard zero-dep + self-hosting com TLS + token forçado (o Electron do Hermes é localhost-only).
- **Observabilidade**: `okami cost` por-vendor (assinatura = incluído, nunca inventa $) + `provider check --live`.
- **UX**: streaming token-a-token na TUI e no Telegram.
- **Multi-agente**: roteamento por binding (provider/model por agente) + swarm (plan→workers→verifier→synthesizer) + kanban.
- **Multi-vendor sem lock-in**: Mixture-of-Agents nos providers configurados; `gemini_cloudcode` (tier grátis).

---

## 🐛 Caça de bugs (#18, código novo)

- **SSRF no download de vídeo** (real): a URL de download vem do PROVIDER (não-confiável) e ia direto pro
  `urlopen` (suporta `file://`). Agora passa pelo `net_guard.validate_public_url` — recusa `file://` e IP
  interno (169.254.169.254 etc.) ANTES de baixar. + teto de 25MB na imagem base (anti-OOM).
- **LspPool**: `find_git_worktree` chamado 1x (era 2 — até 128 ops de FS por checagem).
- Descartado após ler: o "lost wakeup" do LSP não é real (o server só publica DEPOIS do nosso
  didOpen/didChange, enviado DEPOIS de registrar o Event); `_alive` é atômico no CPython (GIL).

---

## 📌 Veredito #18

- **Paridade honesta: ~88–91%** (88% se computer-use TEM que ser embutido; ~91% contando o acesso via MCP).
- Os 3 gaps do #17: **vídeo fechado** (mais fino), **LSP persistente fechado no núcleo** (falta async+wired-no-write),
  **computer-use** = fronteira soberana (alcançável via MCP, não embutido).
- O que resta é **MÉDIO** (LSP async de fundo + wired no write) ou **nicho/regional** (Home Assistant, Feishu,
  X-search). O Okami está à frente em trust model, distribuição, observabilidade, streaming e multi-agente.
- **Próxima rodada (1 candidato in-scope de peso):** integrar o pool LSP persistente no caminho do write
  (substituir o one-shot do `semantic_delta`) com lifecycle de sessão + opção de auto-install do binário.
