# Pesquisa competitiva #10 — Hermes atual vs Okami pós-#9 (jun/2026)

Clone Hermes no HEAD atual (`5bfed0fe`). 6 agentes (ultracode workflow) varreram runtime/providers ·
tools · gateway/canais · memória/honcho · skills/learning · segurança/ops, cada um cruzando com o
inventário COMPLETO do Okami pós-#9 (2231 testes). ⭐ = recomendado. [B] = borderline. **S/M/L.**

## Veredito
O Okami está em **paridade profunda** em todos os domínios. Os gaps reais são poucos e se concentram em
**2 temas**: (1) **recuperação REATIVA de erro de provider** — re-tentar o MESMO provider in-place antes
do failover, que importa JUSTAMENTE porque o Okami é OAuth/assinatura-only e **não tem key pool p/
rotacionar** (hoje um 401/400 pula pro fallback e PERDE a assinatura naquele turno); (2) **responder por
VOZ** (o agente ouve nota de voz mas não fala de volta, apesar de toda a plumbing existir).

---

## 🥇 TIER 1 — alto valor, encaixa nas constraints do projeto

1. ⭐ **Família de RECUPERAÇÃO REATIVA de erro** (S cada, exceto onde nota) — `agent/conversation_loop.py:2227-2451`
   + `agent/error_classifier.py`. Hoje o Okami classifica o erro p/ DECIDIR retry/failover; falta o
   **conserto-e-retry no mesmo provider**. Os de maior ROI p/ assinatura-only:
   - **401 OAuth → force-refresh + retry-same-provider** (S) — token revogado/relógio-torto (não expirado)
     vira `reason=auth` → rotate_key+fallback, **perdendo a assinatura no turno**. Forçar refresh do token
     (codex/Anthropic) e re-tentar O MESMO provider 1× antes de pular. `conversation_loop.py:2310`.
   - **thinking-block signature inválida → strip reasoning + retry** (S) — a Anthropic assina os
     thinking-blocks contra o turno; a **compactação anti-thrashing do Okami MUTA o histórico** → invalida
     a assinatura → 400. Hoje vira `bad_request`→failover. Remover `reasoning_details` só da lista de envio
     e re-tentar. `conversation_loop.py:2400`.
   - **beta de contexto 1M recusado → degrada p/ 200k e segue** (S) — o Okami JÁ manda o beta 1M no
     Anthropic OAuth (opt-in); numa conta SEM 1M vira 400 puro e o turno morre. Desligar o beta só p/ a
     sessão e re-tentar. `conversation_loop.py:2289`.
   - **`max_completion_tokens` vs `max_tokens`** (S) — modelos OpenAI série-o/gpt-5 rejeitam `max_tokens`
     com 400; o transport codex-SSE do Okami (não-litellm) não traduz. Quirk declarativo + swap-on-400.
   - **imagem grande → encolher nativo e re-tentar** (M) — screenshot do Telegram estoura o teto de 5MB
     por-imagem; quando vai NATIVA ao modelo principal não há rede de segurança. `conversation_loop.py:2227`.
   - multimodal-tool-content list→texto (S, menor — o caminho preventivo `vision_tool_messages=False` já cobre).
2. ⭐ **`text_to_speech` — tool p/ o agente RESPONDER em voz** (M) — `tools/tts_tool.py:2704`. O Okami JÁ
   tem a convenção `MEDIA:<path>` (`channels/media.py`) e o Telegram já faz `sendVoice` — mas só tem
   `audio_analyze` (STT). O agente OUVE a nota de voz e **não consegue responder em áudio**. Toda a entrega
   existe; falta a tool que gera o arquivo (Edge/OpenAI/local, voz do dono). Casa direto com "confidente próximo".
3. ⭐ **`file.attach` sobre o attach por WebSocket** (M) — `tui_gateway/server.py:6653`. O cliente anexa um
   arquivo do disco local; o gateway materializa em `.okami/attachments/` e devolve um `@file:` que as tools
   leem. **Completa o `okami attach`/`serve --ws` que construí na #8** — falar com o agente remoto + mandar arquivo.
4. ⭐ **Review herda o prompt-cache do pai (prefix-cache hit)** (M) — `agent/background_review.py:434`. O
   fork de review copia o system prompt cacheado + tools[] byte-idêntico → bate no cache que o turno
   principal aqueceu (~26% de economia medida). Já apontado em #8/#9, ainda não feito; dono paga o review
   da própria cota.
5. ⭐ **Reparo de SQLite malformado + rebuild de FTS no `doctor --fix`** (M) — `hermes_state.py:410`. Recupera
   `state.db`/memória corrompida (de-dup do sqlite_master preservando FTS; senão drop+VACUUM+rebuild),
   com `.malformed-backup` antes. O `okami doctor --fix` não recupera DB corrompido hoje.

---

## ✅ BOM (S, baixo custo)
- **`env_probe`** — sonda barata (~50ms, cacheada) que injeta UMA linha no system prompt SÓ quando o ambiente
  Python está torto (pip↔python3, PEP-668 externally-managed, python ausente). Diferente do `doctor`
  (que é p/ o humano); este é p/ o MODELO em runtime. `tools/env_probe.py:139`.
- **Silêncio intencional (token NO_REPLY)** — o agente pode emitir um token exato p/ DELIBERADAMENTE não
  responder (≠ resposta-vazia-por-erro) + guard que dropa "narração de silêncio" alucinada. `gateway/response_filters.py:13`.
- **Breaker de sessão em crash-loop** — conta sessões ativas-no-shutdown entre restarts; após 3
  (load→hang→restart→repeat) auto-suspende; marcador `.clean_shutdown` pula a suspensão após parada limpa. `gateway/run.py:4361`.
- **Heartbeat de turno longo** — "ainda trabalhando, N min" durante um turno lento (tool/geração demorada)
  p/ não parecer "typing…" por 30min. `gateway/display_config.py:85`.
- **Preflight de CA bundle SSL no boot** (`ssl_guard`) — valida certifi antes do 1º HTTPS, erro acionável
  ("pip install --force-reinstall certifi"). `agent/ssl_guard.py:61`.
- **Scan estático de exfil em comando stdio de MCP** — marca MCP cujo `command` é shell-interpreter com
  egress nos args (curl/wget/nc + .env/-X POST). `hermes_cli/mcp_security.py:64`.
- **Skill declara variáveis de CONFIG no frontmatter** (`metadata.hermes.config`) — como o requires_tools,
  mas p/ chaves de config que a skill precisa (persiste em `skills.config.<key>`). `agent/skill_utils.py:498`.
- **Gating de skill por ambiente de runtime** (`environments:[docker|s6|…]`) — esconde do índice/autocomplete
  quando o ambiente não está ativo; load explícito sempre passa. `agent/skill_utils.py:233`.
- **Curator poda built-ins com lista de supressão anti-reseed** — arquiva built-in estale sem re-semear. `agent/curator.py:173`.

---

## ⛔ Borderline / fora do escopo dono-único
- **Identity tree do honcho** (runtime-ID→peer resolver, pinUserPeer, userPeerAliases, runtimePeerPrefix,
  dual-identity) — `plugins/memory/honcho/session.py`. **Resolve multi-USUÁRIO**: cada sender vira um peer
  distinto. Pro Okami **dono-único** isso é mostly N/A — o `pinUserPeer` (forçar todos ao dono) é o que um
  bot pessoal quer, e o Okami já é efetivamente single-peer. Só vale **`userPeerAliases`** (eu + outras
  pessoas) SE o bot passar a servir mais gente. [B]
- **`video_analyze`** (M) — Claude não ingere vídeo nativo → exigiria Gemini = multi-vendor (contra assinatura-only). [B]
- **Home Assistant tools** (M) — controle de casa inteligente via REST do HA; só se o dono usa Home Assistant. [B]

## Ordem recomendada
**Tier 1 primeiro**, por aderência às constraints: a família de recuperação reativa (1) — sobretudo
401-refresh, thinking-strip e 1M-degrade — é a de maior ROI porque o Okami é assinatura-only sem key pool,
e a compactação+thinking é o gatilho exato do thinking-signature. Depois **TTS (2)** e **file.attach (3)**
(completam features de voz e de attach-remoto que já têm metade pronta), **review-cache (4)** (economia
recorrente) e **repair de SQLite (5)** (resiliência). Os BONS (S) são quick wins de robustez.
