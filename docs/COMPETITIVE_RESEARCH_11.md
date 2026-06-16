# Pesquisa Competitiva #11 — varredura AGRESSIVA Hermes × Okami

**Data:** 2026-06-16
**Alvo:** `NousResearch/hermes-agent` @ `5bfed0fe0` (2026-06-15, 2312 arquivos .py)
**Método:** 8 finders paralelos por fatia funcional (runtime-loop, prompt-context, skills-memory,
security-creds, tools, gateway/TUI, cli/ops, provider/multimodal). Cada finder **grepou o código real
do Okami** p/ provar ausência antes de reportar; depois **1 verificador adversarial por achado** re-grepou
o Okami p/ rejeitar o que já existe ou viola as constraints (assinatura-only, dono-único, sem key pool,
segredo nunca ecoado). **51 agentes, ~3.3M tokens.**

> Resultado bruto: **35 lacunas confirmadas, 8 rejeitadas**. O verificador rejeitou corretamente coisas
> que o Okami JÁ tem (`ClassifiedError` 17-tipos, preprocess de skill, curator 418-linhas, paridade de
> `read_extract` .docx/.xlsx/.ipynb, `doctor --fix`) e o fora-de-escopo multi-usuário (cross-profile write
> guard, pre-update-backup). A camada adversarial funcionou.

---

## Veredito

Décima-primeira rodada, mesma conclusão das anteriores: **paridade profunda**. Não há buraco estrutural.
As 35 lacunas confirmadas se agrupam em **cinco temas**, e a maioria é robustez de borda (S/M), não feature
faltando:

1. **Defesa contra injeção em arquivos de contexto** — o Okami carrega `AGENTS.md`/`.cursorrules`/subdir
   hints SEM sanitizar. Um repo clonado hostil sequestra o brief. **Maior ROI de segurança.**
2. **Supply-chain / exfil de MCP** — scanner de exfil em `command/args`, OSV malware-check pré-spawn,
   OAuth-PKCE p/ MCPs protegidos. (Os dois primeiros já eram BOM do #10, não implementados.)
3. **Robustez multimodal** — sniff de magic-byte p/ MIME, auto-extração de imagem do texto, router
   native-vs-text. Evita 400 do provider por imagem mal-rotulada.
4. **UX adaptativa por plataforma** — display-config em tiers, heartbeat de turno longo, merge de
   álbum-de-fotos, detecção de silêncio multi-marcador. (Heartbeat/display-config já eram BOM do #10.)
5. **Resiliência de modelo local (LMStudio/llama.cpp)** — sanitização de schema JSON-Schema→GBNF, reparo
   multi-passe de tool-call JSON malformado, stall-vs-truncation no stream. Relevante porque **LMStudio é
   constraint dura** do projeto.

**Nada aqui muda a tese.** São endurecimentos. Abaixo, curados por valor real p/ um agente de código
dono-único assinatura-only — não pela contagem.

---

## TIER 1 — segurança & supply-chain (fazer primeiro; quase tudo S)

| # | Lacuna | Hermes | Okami hoje | Esforço |
|---|--------|--------|-----------|---------|
| 1 | **Scan de injeção em arquivo de contexto** | `prompt_builder.py:42-61` `_scan_context_content` varre `AGENTS.md/CLAUDE.md/.cursorrules` por injeção/C2 ANTES de injetar no system prompt; bloqueia com `[BLOCKED:…]` | `subdir_hints.py:49-62` lê convenção **sem sanitizar**; `sanitize_for_prompt` existe mas NÃO é chamado nesse caminho | **S** |
| 2 | **Scanner de exfil em MCP stdio** *(BOM #10)* | `mcp_security.py:64-96` `validate_mcp_server_entry` marca MCP cujo `command` é shell-interpreter + `args` com egress (curl/wget/nc//dev/tcp) + hint de exfil (`-X POST`,`--data-binary`) | `mcp.py:306-310` carrega `command` sem validar; `lint.py` não checa command/args | **S** |
| 3 | **OSV malware-check pré-spawn de MCP** | `osv_check.py:1-72` consulta OSV API por advisory `MAL-*` antes de rodar pacote npx/uvx; cache por pkg+versão; fail-open na rede; bloqueia SÓ malware confirmado | `advisories.py:64-76` checa pacotes Python PÓS-install via importlib; **zero** chamada OSV; `mcp.py:281-333` spawna sem checar | **S** |
| 4 | **CA-bundle SSL preflight** *(BOM #10, ssl_guard)* | `ssl_guard.py:45-84` valida `SSL_CERT_FILE/REQUESTS_CA_BUNDLE/…` (existe + >1KB + `ssl.create_default_context` carrega) antes do 1º HTTPS; erro acionável | `errors.py:72` só casa o padrão REATIVO; nenhuma validação no boot | **S** |
| 5 | **Biblioteca de threat-patterns ampliada (C2/anti-forense/unicode)** | `threat_patterns.py:1-184` 60+ regex por classe (injection/C2/exfil/persistence/obfuscation), scope-aware (all/context/strict), pega Trojan-Source (unicode invisível), "register node/heartbeat/pull tasks" | `skill_security.py:35-83` ~40 regras, SÓ pré-install, sem C2/anti-forense/unicode, sem `scope` | **M** |

> **Por que primeiro:** #1 é o único buraco de segurança que muda postura (repo hostil → brief sequestrado).
> #2-#4 são os BOM do #10 que ficaram p/ trás; baratos e fail-open. #5 unifica o vocabulário de ameaça e o
> reaproveita em memória/skill/contexto (hoje o scan é só pré-install).

---

## TIER 2 — UX de plataforma & gateway (ROI alto p/ uso real no Telegram)

| # | Lacuna | Hermes | Okami hoje | Esforço |
|---|--------|--------|-----------|---------|
| 6 | **Merge de álbum/burst de fotos + dedup de legenda** | `platforms/base.py:210-240` `merge_pending_message_event` + `_merge_caption` (975-989) une PHOTO+PHOTO numa só virada, dedup linha-a-linha | `channels/base.py:18` campo `image` único; `telegram.py:356` pega só `photo[-1]` → **burst truncado p/ a última foto** | **M** |
| 7 | **Display-config em tiers por plataforma** *(BOM #10)* | `display_config.py:33-144` defaults globais + por-plataforma (TIER_HIGH/MED/LOW/MINIMAL), `resolve_display_setting` precedência 4-níveis (Slack sem tool_progress, SMS só resposta-final) | mesma verbosidade p/ todo canal | **M** |
| 8 | **Heartbeat de turno longo** *(BOM #10)* | `display_config.py:40-47` + `_send_loading_heartbeat` manda "rodando, N min" a cada N s num turno lento | `endpoint.py:1327-1336` só step/loop/compact/escalate disparam status; pensamento silencioso nunca avisa | **S** |
| 9 | **Detecção de silêncio multi-marcador** *(parcial: já tem [SILENT])* | `response_filters.py:13-54` frozenset {NO_REPLY,SILENT,[SILENT],NO REPLY}, normaliza whitespace, limite ≤64 chars, type-guard `failed` | `scheduler.py:206-214` regex-only, inflexível | **S** |
| 10 | **Panic-hook → log de crash do gateway/TUI** | `tui_gateway/server.py:44-105` `sys.excepthook`+`threading.excepthook` logam traceback em `*_crash.log` + 1-linha no stderr | nada; `shutdown_forensics.py` captura contexto mas NÃO exceções | **S** |
| 11 | **Auto-extração de imagem do texto (paths+URLs)** | `image_routing.py:78-144` `extract_image_refs` pega `~/shot.png` / `https://x/a.png` inline, pula code-block | `link_understanding.py:16` só p/ sumarização web; imagem exige param explícito | **M** |

---

## TIER 3 — resiliência de provider & modelo local (LMStudio é constraint dura)

| # | Lacuna | Hermes | Okami hoje | Esforço |
|---|--------|--------|-----------|---------|
| 12 | **Sanitização de schema p/ llama.cpp (GBNF)** | `schema_sanitizer.py:46-230` conserta JSON-Schema que o grammar-converter do llama.cpp rejeita (anyOf/oneOf nullable, pattern/format, ref-siblings) — proativo + reativo no 400 | `base.py:184-195` `to_openai_schema` sem sanitização → **400 grammar-parse** em modelo local | **M** |
| 13 | **Reparo multi-passe de tool-call JSON malformado** | `message_sanitization.py:185-279` `_repair_tool_call_arguments` 5 passes (strict=False, trailing-comma, fecha estrutura, tira chave-extra, escapa control-char) | `providers.py:31-40` só remove surrogate; **não toca** o campo `arguments` da tool-call | **M** |
| 14 | **Stall-vs-truncation no stream** | `conversation_loop.py:1646-1706` sentinela `PARTIAL_STREAM_STUB_ID` distingue socket-drop (retry c/ +max_tokens) de truncação real (rollback p/ última msg completa) | `loop.py:482-510` só checa `finish_reason=='length'`, trata tudo igual; `Completion` sem campo `id` | **M** |
| 15 | **MCP OAuth 2.1 + PKCE (browser)** | `mcp_oauth.py:1-72` authorization-code+PKCE p/ MCP, callback localhost efêmero, refresh, dynamic registration | `mcp.py:111-151` só header estático → **MCP protegido por OAuth = inacessível** | **M** |
| 16 | **Sniff de MIME por magic-byte na imagem** | `image_routing.py:364-396` `_sniff_mime_from_bytes` (PNG/JPEG/GIF/WebP/BMP/HEIC) antes de mandar ao provider | `vision.py:21-24` + `prompt.py` só `mimetypes.guess_type` por nome → 400 se rotulado errado | **S** |
| 17 | **Limites de tool-output config-driven** | `tool_output_limits.py:59-80` caps atrás de `tool_output:{max_bytes,max_lines,max_line_length}` no config, fallback defensivo | `execute_code.py:27` `_MAX_OUTPUT=100k` e `remote.py:20` `200k` **hardcoded** em 2 lugares | **S** |
| 18 | **Steering de edit-format por família de modelo** | `coding_context.py:102-156` `_EDIT_FORMAT_GUIDANCE`: GPT/Codex→patch(V4A), Claude/Gemini→replace | `style.py:103-111` `model_family_guidance` cobre concisão/paralelismo mas NÃO edit-format | **S** |

---

## TIER 4 — operações / CLI (úteis, valor médio)

| # | Lacuna | Hermes | Okami hoje | Esforço |
|---|--------|--------|-----------|---------|
| 19 | **`okami completion bash\|zsh\|fish`** | `completion.py:55-320` gera scripts de completion p/ os 3 shells | `_app.py:9` `add_completion=False`, **sem comando** (o "completion" da Wave F é o WordCompleter do REPL, outra coisa) | **S** |
| 20 | **`okami logs` com filtro multi-eixo** | `logs.py:46-78` `--level/--session/--component/--since` | `gateway.py:478-481` sem filtros | **S** |
| 21 | **Skill bundles — fiação do dispatch** | `skill_bundles.py:1-411` registry YAML + `/slug` carrega N skills de uma vez, resolve conflito | `skills/bundles.py` tem `list_bundles`/`load_bundle` mas **ZERO chamadores** em cli/gateway/tools → camada de dados morta, dispatch nunca ligado | **S** |

---

## TIER 5 — gating de skill (BOM #10, valor médio p/ dono-único)

| # | Lacuna | Hermes | Esforço |
|---|--------|--------|---------|
| 22 | **Skill declara CONFIG no frontmatter** *(BOM #10)* | `skill_utils.py:498-554` `metadata.hermes.config` (key/description/default/prompt); auto-pergunta 1x e persiste em `skills.config.<key>` | **M** |
| 23 | **Gating de skill por plataforma/ambiente** *(BOM #10)* | `skill_utils.py:128-269` `platforms:[macos,linux]` + `environments:[docker,s6]` com detecção cacheada; esconde do índice quando inativo | **M** |

---

## Borderline / cosmético / fora-de-escopo (honestidade)

- **Factoring de `TurnFinalizer` (#1 bruto) e `TurnRetryState` (#25 bruto)** — refactor de organização, não
  feature. O Okami já recupera (image-shrink + oauth-refresh via `recovery.py`) e classifica erro
  (`ClassifiedError`, 17 tipos). O `recovered:set` inline faz o trabalho do TurnRetryState. Ganho real:
  legibilidade/extensibilidade, não comportamento. **Só vale se formos adicionar muitos caminhos de
  recuperação novos.** [adiar]
- **`is_genuine_nous_rate_limit` (#3 bruto)** — distingue quota-esgotada de upstream-transiente lendo
  headers `x-ratelimit-*`. Útil, MAS a motivação ("não bloquear Kimi quando DeepSeek cai") é **multi-upstream
  multiplexado da Nous** — o Okami é Claude-assinatura-único. Ainda há um núcleo válido (não tratar um 503
  transiente como breaker-de-hora), mas é menor. [borderline → S se enxugar p/ "transient 5xx ≠ breaker"]
- **Credential pool borrowed-vs-owned (#9 bruto)** — sanitiza credencial de OAuth de terceiro antes do
  disco. Relevante só com creds **emprestadas multi-vendor**; o Okami é assinatura-única. [fora-de-escopo
  até existir secret-source de terceiro de fato em uso]
- **Active-session concurrency-limit (#20 bruto)** — gate de oversell por billing. Justificativa é
  **multi-usuário/quota-por-assinante**; dono-único não precisa. [fora-de-escopo]
- **Tabela markdown wcwidth-aware CJK (#4 bruto)** — re-alinha tabela com CJK/emoji no terminal. Real, mas
  ~300 LOC p/ um caso (saída CJK no TUI). [baixo ROI salvo workflow JP/CN]
- **Audio-input em ModelInfo (#35 bruto)** — metadado p/ STT-direto-ao-modelo futuro; só faz sentido quando
  houver tool de transcrição que escolha modelo por isso. [adiar — future-proof]
- **TTS streaming / async web-extract ABC (#23/#24 brutos)** — abstrações async; o Okami já tem
  `text_to_speech` (síncrono, basta) e `web_extract` sync. Ganho marginal sem provider streaming real. [adiar]
- **`tool_guardrails` config-driven (#11 bruto)** — tornar thresholds de loop-guard configuráveis. O
  `Budget` já expõe `max_repeat/stall_limit/max_loop_breaks`; é S transformar em bloco de config, mas o
  default atual serve. [nice-to-have S]

---

## Sobreposição com os BOM do #10 (ainda pendentes)

O #11 reconfirmou, por código, que estes BOM do #10 **seguem não-implementados** e valem: scanner-exfil-MCP
(T1#2), ssl_guard (T1#4), heartbeat (T2#8), display-config-tiers (T2#7), silêncio-NO_REPLY (T2#9, parcial),
skill-config-frontmatter (T5#22), gating-de-skill-por-ambiente (T5#23). **Curator-poda-built-in-anti-reseed**
e **breaker-de-crash-loop** do #10 NÃO reapareceram → provável que o Okami já os tenha (Wave E shutdown
forensics / Wave G curator) — não re-flagados pelo verificador.

---

## Ordem recomendada (se/quando implementar — NÃO faz parte deste goal)

**Onda 1 (segurança, ~1 sessão, quase tudo S):** T1#1 scan-de-contexto → T1#2 exfil-MCP → T1#4 ssl_guard →
T1#3 OSV → T1#5 threat-lib. *Aderência máxima às constraints; muda postura de segurança.*

**Onda 2 (modelo local + provider, LMStudio é constraint):** T3#13 JSON-repair → T3#12 schema-sanitizer →
T3#16 MIME-sniff → T3#14 stall-vs-truncation. *Tira 400s espúrios de modelo local.*

**Onda 3 (UX Telegram):** T2#8 heartbeat → T2#10 panic-hook → T2#9 silêncio → T2#6 álbum-de-fotos →
T2#7 display-config → T2#11 auto-extração-imagem.

**Onda 4 (CLI/skills):** T4#21 fiar bundles → T4#19 completion → T4#20 logs-filtro → T5#22/#23 skill
config+gating → T3#17 tool-output-config → T3#18 edit-format-steering.

> **Nota:** este documento é a entrega da fase "buscar e comparar p/ encontrar melhorias". A
> implementação não foi pedida neste goal — o próximo passo do goal é caçar e corrigir **bugs**.
