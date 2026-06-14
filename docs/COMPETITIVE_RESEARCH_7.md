# Pesquisa competitiva #7 — Okami vs Hermes vs OpenClaw (varredura profunda, jun/2026)

Clones frescos: `NousResearch/hermes-agent` (Python, `d62979a`, 2275 .py) + `openclaw/openclaw`
(TypeScript, `0063f307`, 16k .ts). 8 agentes paralelos por domínio leram arquivo:linha nos DOIS
repos e cruzaram com o Okami pós-#6 (1711 testes). Foco em gaps NOVOS (não re-lista #1–#6).
Tamanhos S/M/L. ⭐ = recomendado. O Okami já está em PARIDADE no núcleo; o que sobra é alcance.

## Veredito por domínio (onde o Okami está)

- **Harness/loop:** paridade forte. Hermes/OpenClaw só ganham em 4 pontos finos (todo durável, tool paralela, steer, checkpoint de turno).
- **Tools de código:** atrás em **LSP semântico** (gap nº1 de código) e **checkpoint/undo de edição**; resto em paridade.
- **Web/mídia:** atrás em browser-a11y, áudio/vídeo understanding, TTS local; à frente em voice local (whisper).
- **Memória/skills:** À FRENTE (embeddings/dedup/forget que os refs não têm). Único gap de peso: **commitments inferidos** (proatividade).
- **Providers:** muito forte. Gap real só em **quirks declarativos** e clamp de effort.
- **Gateway:** paridade ampla. Falta **canal de saída do agente** (falar sozinho) + **webhook** + inbound de e-mail.
- **Segurança:** MUITO forte (igual/à frente). 3 buracos afiados e baratos: DLP de output, HMAC no audit, OSV on-demand.
- **Interfaces:** TUI/CLI fortes. Gap em **notificação desktop**, ACP raso, sem completion.

## 🔴 CORREÇÃO DE HONESTIDADE (achado da #7)

A task #32 da pesquisa #6 ("D28 — ACP profundo + edit-approval com diff inline") foi **SOBRE-DECLARADA**.
O `okami/integrations/acp.py` (135 linhas) faz initialize/session.new/prompt/cancel + streaming de
tool-calls, mas **NÃO tem** edit-approval, request_permission, loadSession/fork/list, nem
available_commands. O memory já registrava a ressalva ("edit-approval precisa cliente IDE"), mas o
commit marcou D28 como completo. **Estado real: ACP é PARCIAL.** Itens A-acp abaixo fecham de verdade.

## ONDA A — quick wins de alto ROI (S, fundação + segurança)

1. ⭐ **audio_analyze como TOOL** (S) — o motor LOCAL (faster-whisper) JÁ existe no repo, mas só como
   `okami transcribe` CLI; não há tool que o agente chame mid-conversa. Telegram já recebe voz `.ogg`
   → fecha "me manda áudio, eu transcrevo" de graça. Hermes `model_tools`→aux; OpenClaw
   `media-understanding/audio-transcription-runner.ts`. Okami: motor em `voice/stt.py:WhisperSTT`.
2. ⭐ **DLP de OUTPUT no boundary do canal** (S, SEGURANÇA AFIADA) — a `redact()` congelada cobre
   log/audit/tool-output/memória, MAS o texto da RESPOSTA do agente vai CRU pro `channel.send()`
   (`gateway/endpoint.py:321`). Injeção que faça o modelo ecoar `$OPENAI_API_KEY` é mascarada no audit
   e **enviada inteira** ao Telegram. Aplicar `redact` no ponto único de delivery. OpenClaw
   `src/logging/redact.ts`.
3. ⭐ **canal de SAÍDA do agente / notify_owner** (M, FUNDAÇÃO) — o agente responde devolvendo texto do
   turno; **não tem tool** "manda isto ao dono AGORA". Sem isso, on_error/webhook/e-mail/file-watch não
   têm como te avisar. É a alavanca que destrava metade da Onda B. Hermes entrega fora-do-turno via
   `adapter.send()`; falta no Okami um tool `notify`/`send_message`.
4. **notificação DESKTOP leve** (S) — `terminal-notifier`/`notify-send`/OSC-9, SEM GUI. Cron e jobs de
   fundo já existem; "avisa quando terminar / quando precisar de aprovação" é o elo que falta. OpenClaw
   `apps/macos/NotificationManager.swift` (nós fazemos a versão leve de terminal).
5. **HMAC-chain no `audit.jsonl`** (S) — o Okami JÁ tem a primitiva pronta (`gateway/checkpoints.py`
   `_mac`/`_verify` com re-encadeamento); o `.okami/audit.jsonl` (`loop.py:_audit`) é append puro sem
   MAC → trilha forense editável em silêncio. Quase copiar-colar.
6. **vision NATIVE fast-path** (M) — `vision_analyze` SEMPRE roteia pro modelo aux, mesmo quando o
   principal (Claude/Gemini de assinatura) já é multimodal → perde fidelidade + gasta call. Quando o
   principal vê, anexar os pixels direto (resize defensivo 5MB/8000px). Hermes
   `vision_tools.py:603 _should_use_native_vision_fast_path`.
7. **staleness guard (read-then-write por mtime)** (S/M) — grounding garante "leu antes", mas não
   detecta que o arquivo mudou DEPOIS da leitura (build/outra sessão/o dono) → sobrescreve calado.
   Hermes `tools/file_state.py:142 check_stale`.
8. **OSC-8 hyperlinks no TUI** (S) + **edit_file devolve diff unified + linha** (S) — DX barato: paths
   clicáveis e o modelo/UI veem o que mudou. OpenClaw `tui/osc8-hyperlinks.ts`, `tools/edit.ts:424`.

## ONDA B — capacidades (M, alinhadas à identidade)

9. ⭐ **todo durável que SOBREVIVE à compactação** (M) — gap convergente (2 agentes). Lista
   `{id,content,status}` que o modelo escreve/atualiza e é RE-INJETADA após cada compactação (só
   pending/in_progress). Ataca direto a fraqueza do modelo fraco em trabalho longo (perde o fio).
   Difere do `/goal` (que é objetivo de chat): é checklist OPERACIONAL do modelo. Hermes
   `tools/todo_tool.py` + re-injeção em `conversation_compression.py:493`.
10. ⭐ **commitments INFERIDOS + entrega endurecida** (L, casa com a VOZ "confidente próximo") — o
    Okami tem o esqueleto INVERTIDO: `scheduler.infer_commitment` é regex single-turn que só dispara em
    gatilho explícito ("lembr/agend"). O OpenClaw faz o oposto: extração por LLM (modelo aux) em
    background dos follow-ups IMPLÍCITOS que ninguém pediu — 4 kinds (event_check_in/deadline_check/
    care_check_in/open_loop), confidence (~0.72; care ~0.86), dedupe key, lifecycle (pending→sent/
    dismissed/snoozed/expired), cap por dia (~3), expiry ~72h. **Desde o 1º commit:** NÃO replayar texto
    do turno na mensagem de entrega (vetor de injeção persistida — guard `stripLegacySourceText`).
    OpenClaw `src/commitments/{extraction,store,types,config}.ts`. É o item que mais reforça a voz do projeto.
11. **link understanding** (M) — usuário cola link no Telegram → resumo automático SEM o modelo decidir
    chamar web_extract. Reusa `web_extract`+aux que já existem. OpenClaw `link-understanding/runner.ts`.
12. **quirks declarativos de provider** (M) — `ProviderConfig.params` é dict estático; cada provider
    tem manha condicional (reasoning XOR thinking, `supports_vision_tool_messages`, omit temperature)
    que vira 400/tentativa-e-erro. 2-3 campos opt-in (`reasoning_style`, `vision_tool_messages`,
    `omit_temperature`) consumidos em `_kwargs`. Hermes `providers/base.py` + 29 profiles de plugin.
13. **ACP edit-approval + permissions + available_commands** (M) — fecha de verdade o que a #32
    sobre-declarou: a IDE (Zed) mostra old→new e o humano aprova ANTES de escrever; comando perigoso
    vira pedido de permissão; slash-commands no autocomplete. Sem isso, usar o Okami no Zed escreve/roda
    sem o gate que o REPL tem. Hermes `acp_adapter/edit_approval.py`, `permissions.py`.
14. **webhook genérico HMAC + `deliver_only`** (L+S) — par do cron (cron=tempo, webhook=evento). POST
    de GitHub/Stripe/Supabase valida assinatura → roda agente; `deliver_only` repassa sem queimar LLM
    (importa num plano de assinatura). Depende do canal de saída (#3). Hermes `gateway/platforms/webhook.py`.
15. **clamp de reasoning effort + sonda ativa no doctor + default cost-safe** (S cada) — três quick
    wins de provider: rebaixar effort que o modelo não suporta (anti-400/custo); doctor sondar
    /v1/models (distingue "LMStudio off" de "modelo errado"); provider sem `model` não cair no flagship
    mais caro. OpenClaw `model-utils.ts:59 clampThinkingLevel`; Hermes `models.py:1252,3295`.

## ONDA C — épicos (L, maior esforço/valor)

16. ⭐ **LSP semântico (diagnostics-on-write)** (L, ALTÍSSIMO p/ agente de código) — `code_lint.py` só
    faz syntax (compile/json/yaml); zero semântica/cross-file. Subir cliente LSP (começar só **pyright**,
    Python é o foco), gated em git-workspace, fallback silencioso, baseline-diff (só erro NOVO — reusa a
    lógica do lint delta). É o que mais aproxima de um agente de código sério. Hermes `agent/lsp/` (4289
    linhas); doc deles diz que é "a mesma arquitetura dos agentes top".
17. **checkpoint/undo de edições (git-shadow por turno)** (L) — snapshot antes de cada turno mutante +
    rollback a qualquer ponto. Okami só tem lixeira p/ `delete_path`; um patch errado em cascata hoje é
    irreversível. Auto-contido (git plumbing num repo-sombra fora do projeto). Hermes
    `tools/checkpoint_manager.py` (1642 linhas).
18. **browser a11y-tree + sessão persistente + screenshot annotate** (L, épico) — `browse()` clica por
    seletor CSS (frágil), abre/fecha Chromium toda chamada, nunca opera site logado. `page.aria_snapshot`
    (refs @e1) + `launch_persistent_context(user_data_dir)` + overlay [N] são TODOS locais/grátis e é o
    que separa "lê página" de "opera a web". Hermes `browser_tool.py:2499`, `browser_camofox.py:118`.
19. **inbound de E-MAIL (IMAP)** (M) — "e-mail do chefe chegou → agente age". Grátis (Gmail
    app-password), sem API paga; vira o Okami de "responde" pra "monitora". Casa com a voz de confidente.
    Hermes `gateway/platforms/email.py` (780 linhas).
20. **execução PARALELA de tools** (M) — read-only sempre paralelo; write/patch paralelos só se paths
    não colidem (subtree check). Ganho de wall-clock real (gargalo vs Hermes); o `_lead_readonly` já tem
    metade do caminho. Hermes `agent/tool_executor.py:243`.
21. **TTS local + voice-clone** (M) — Piper (44 idiomas offline), KittenTTS (25MB), NeuTTS (clona voz)
    são grátis/on-device — encaixe ideal sub-only. Hoje só EdgeTTS (cloud MS) + MiniMax (pago). Hermes
    `tools/tts_tool.py`, `neutts_synth.py`.

## Refinamentos menores (S, fazer se sobrar)

steer mid-turn (corrige rumo sem matar turno); roteamento adaptativo de compactação (estima se truncar
tool-results resolve antes de gastar LLM); threat-patterns scope-tiered (all/context/strict + classes
C2); OSV.dev on-demand (`okami doctor --supply-chain` em vez de catálogo estático); diff no prompt de
aprovação (aprovar linhas, não path); skill bundles (`/<bundle>` carrega N skills); hooks de mensagem
(after_response/on_error/on_startup); shutdown forensics (quem matou o gateway às 3h); export de
conversa HTML/PDF; shell completion; git snapshot no system prompt; abrir channel REGISTRY a plugins;
guardrail idempotente-vs-mutador; checkpoint/replay de turno após crash.

## FORA DE ESCOPO (decisão explícita — não perseguir)

- **App desktop Electron / web SPA / app nativo Swift** — Hermes (408 arq Electron) e OpenClaw (480 arq
  SPA + Swift) são produtos paralelos inteiros; a TUI já cobre o caso de uso solo.
- **Plugin SDK de terceiros** — channel_registry + skills hub já cobrem extensão pessoal; SDK só vale
  com ambição de ecossistema.
- **Geração de VÍDEO e MÚSICA** — todo provider é cloud PAGO, sem opção local; contraria sub-only.
- **Speech-to-speech realtime / barge-in** — providers realtime cloud pagos + infra de áudio; o próprio
  `bridge.py` marca como "o passo além".
- **trajectory_compressor → dataset SFT** — treinar modelo próprio foge do produto subscription-only.
- **WhatsApp/Signal/SMS/Matrix** — Baileys (risco ban), signal-cli (+processo), Twilio (pago por msg);
  e-mail é o único canal novo de bom custo. **proxy-capture** do OpenClaw é gravador MITM de teste, não
  segurança.
- **netns/iptables real, multi-user roles, forum topics, MCP de ESCRITA externa** — contrariam
  dono-único / dev-macOS, ou abrem superfície de risco sem demanda.

## Ordem recomendada

ONDA A inteira primeiro (S, alto ROI, e #3 canal-de-saída destrava a B). Depois Onda B na ordem:
todo durável → commitments → quirks de provider → ACP edit-approval → link understanding → webhook.
Onda C por demanda: LSP quando for editar código a sério; checkpoint/undo junto; browser-a11y quando
precisar operar a web; e-mail quando quiser o agente monitorando.
