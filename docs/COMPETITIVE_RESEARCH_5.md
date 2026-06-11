# Pesquisa competitiva #5 — Hermes vs Okami, PROJETO INTEIRO (jun/2026)

4 varreduras profundas no `NousResearch/hermes-agent` (commit 9102d4a): núcleo do agente,
tools/integrações, memória/skills/aprendizado, providers/segurança. Confrontado com o estado
atual do Okami. Tamanhos S/M/L. ⭐ = recomendado próximo.

## Onde o Okami está NA FRENTE (confirmado pelos relatórios)

- Fallback de tool-call por texto (`tool_mode: json_text/json_constrained`) — Hermes é native-only
- Sandbox read-only — Hermes não tem modo read-only de filesystem
- Retrieval de skill por INTENÇÃO (rankeado) — Hermes usa índice plano nome+descrição
- Destilação de skill com gate de qualidade determinístico — Hermes não tem gate (difere pro curator)
- Taste model e evolução de persona com aprovação — sem equivalente no Hermes (design deles: estilo
  vive na skill da tarefa, não na identidade — ideia a avaliar)

## 1. NÚCLEO DO AGENTE (loop/contexto/prompting)

### ⭐ S — quase de graça
1. Prefixo ANTI-SEQUESTRO no resumo de compactação: "[CONTEXT COMPACTION — REFERENCE ONLY]…
   a última mensagem do usuário VENCE; 'para/desfaz' encerra qualquer trabalho do resumo",
   títulos "Snapshot histórico" (não lê como TODO ativo), marcador de fim. (context_compressor.py:44)
2. Anti-thrashing de compactação: 2 compactações seguidas com <10% de ganho → para e sugere /new
3. Prompts de CONTINUAÇÃO distintos: truncou por tamanho ("continue de onde parou, não recomece"),
   morreu a rede no meio, tool-call grande demais ("NÃO repita igual; quebre em pedaços <8K tokens")
4. Sanitização de surrogates UTF-16 soltos (modelos locais via LMStudio emitem e crasham json.dumps)
5. Higiene de saída do loop: exceção não tratada → fecha tool_calls órfãos com resultado sintético
6. env_probe: 1 linha no prompt sobre venv/PEP-668 ("descobrir por prompt, não por falha")

### M
7. Escada de recuperação de RESPOSTA VAZIA (5 níveis: stream parcial → conteúdo do turno anterior →
   nudge pós-tool → prefill de thinking → retry/fallback), scaffolding sintético removido do
   histórico durável (conversation_loop.py:3838)
8. Reparo de tool-call malformado: rename fuzzy de tool alucinada, JSON inválido → erro sintético
   ensinando, detecção de TRUNCAMENTO de args (não termina em }/]) → não executa
9. Poda de tool-results SEM LLM na compactação: resultado antigo vira 1 linha informativa
   ("[terminal] npm test -> exit 0, 47 linhas"), dedup MD5 de outputs idênticos, strip de base64
10. /steer — mensagem do usuário no MEIO do turno, anexada ao fim do último tool-result com
    marcador confiável pré-autorizado no system prompt
11. System prompt BYTE-ESTÁVEL por sessão (persistido, replay idêntico; data só com precisão de
    dia; JSON canônico) → reaproveita KV-cache no LMStudio/llama.cpp — latência real
12. Budget de iteração com REEMBOLSO (tool barata devolve orçamento) + 1 chamada de graça
    sem tools pedindo resumo do progresso (em vez de morrer calado)
13. Execução PARALELA de tools com classificação de segurança (allowlist read-only;
    path-scoped só quando os paths não colidem)
14. Hints de subdiretório: AGENTS.md/CLAUDE.md descobertos ao tocar pastas novas entram no
    TOOL RESULT (não quebra o cache do system prompt)

## 2. TOOLS E INTEGRAÇÕES

### ⭐ S
15. Spill-to-file de saída grande: output acima do teto vai pra arquivo e o contexto recebe
    preview+caminho (lê depois com read_file) + teto agregado por turno (200K chars)
16. read_file sugere nomes parecidos quando erra o caminho
17. Tool `clarify`: pergunta estruturada (múltipla escolha/aberta) como tool de primeira classe
18. Descrições de tool como coaching ("NÃO use cat/head/tail — use read_file")
19. Lazy deps: lib de provider faltando → oferece pip install na primeira tentativa de uso

### M
20. Modo PATCH multi-arquivo (V4A: Update/Add/Delete/Move File) com fuzzy context matching
21. Lint-on-write com DELTA: só erros NOVOS introduzidos pela escrita (py/json/yaml/toml baratos)
22. PTY mode no run_shell + process write/submit (digitar no stdin de processo rodando)
23. notify_on_complete: processo background terminou → re-invoca o agente proativamente
24. search_files unificado (ripgrep): content/files_only/count, glob, paginação, sort por mtime
25. web_search/web_extract plugáveis com fallback GRÁTIS zero-key (DDGS) — hoje browse é 1 caminho
26. Snapshot de browser por árvore de ACESSIBILIDADE com refs @e1… (+ resumo LLM mantendo refs)
27. Toolsets por canal/perfil + check_fn de disponibilidade + tool_search (schemas sob demanda)
28. cronjob como TOOL action-multiplexada (create/list/pause/…) — agente agenda sozinho
29. vision_analyze roteado por modelo auxiliar (modelo texto ganha visão)

### L
30. execute_code (programmatic tool calling): script chama tools via RPC, resultados intermediários
    NÃO entram no contexto — colapsa N idas-e-voltas em 1. Maior economia de tokens da lista
31. Backends de execução plugáveis (local/docker/ssh/modal) sob a mesma interface de tools
32. LSP de verdade (diagnostics delta na escrita) — flagship deles
33. send_message cross-platform (20+ plataformas) — temos telegram/slack/discord/mattermost

## 3. MEMÓRIA / SKILLS / APRENDIZADO

### ⭐ S
34. Do-not-capture COMPLETO + doutrina "frustração do usuário é sinal de SKILL de primeira classe
    ('para de fazer X' → patch na skill que governa a tarefa)" + "memória é fato declarativo,
    não instrução a si mesmo" — já temos parte; completar os prompts
35. Guard de drift externo: arquivo de memória editado por fora não round-tripa → .bak + recusa
36. Telemetria de skill (.usage.json): views/uses/patches, estados active/stale/archived, pinned
    — substrato pra qualquer curadoria
37. Snapshot CONGELADO da memória por sessão (escreve no disco, prompt fica byte-estável → cache)

### M
38. Scan de injeção na memória nas DUAS pontas (write E load): entrada envenenada vira
    "[BLOCKED: …]" no snapshot, usuário ainda vê e pode remover
39. Fila de APROVAÇÃO de escrita de memória/skill: /memory pending|approve|reject (gateway e
    background sempre staged) — casa com o produto approval-centric do Okami
40. session_search como TOOL: FTS5 sobre TODOS os transcripts ("memória é preferência;
    histórico de tarefa é busca de sessão")
41. /goal + /subgoal: objetivo persistente com juiz auxiliar fail-open, orçamento de turnos,
    juiz de subgoal exige EVIDÊNCIA concreta
42. Fork do background review herdando o system prompt cacheado byte-exato (−26% custo medido)
43. Skill bundles (/backend-feature carrega N skills) + binding automático skill→/comando

### L
44. CURATOR: tier de consolidação SEMANAL acima do review por turno — pass de lifecycle puro sem
    LLM (30d→stale, 90d→archive), merge de guarda-chuva por LLM com contrato YAML, dry-run,
    snapshot+rollback. "Centenas de skills estreitas = FALHA da biblioteca" (temos curator CLI
    embrionário; falta o tier completo)
45. Skills hub multi-fonte (taps GitHub, ClawHub, well-known endpoints) com tiers de confiança,
    quarentena, hash de conteúdo — scanner reutilizável standalone

## 4. PROVIDERS / SEGURANÇA

### ⭐ S — ataca a dor de "overloaded" do Marcos
46. Guarda de rate-limit CROSS-SESSÃO: 429 grava reset em ~/.okami/rate_limits/<provider>.json;
    TODA sessão (CLI/gateway/cron) checa antes de chamar — mata a amplificação de retry
47. Backoff exponencial com JITTER decorrelacionado (anti-thundering-herd)
48. Tracking de headers x-ratelimit-* (12 headers, 4 janelas) exibido no /usage
49. Hardline ANTES do yolo (verificar ordem no Okami) + YOLO congelado no import (env lido 1x —
    skill injetada não consegue export HERMES_YOLO_MODE=1)
50. Redaction congelada no import (mesmo truque)
51. Delimitador de tool-result NÃO-CONFIÁVEL: <untrusted_tool_result source=…> em web/browser/MCP
52. Guard de modelo caro: preço conhecido >$20/M input → confirmação antes de selecionar
53. Catálogo de advisories de segurança embutido (pacotes comprometidos conhecidos, checado no boot)

### M
54. Classificador de ERROS com dicas de recuperação (~22 razões): billing→rotaciona JÁ,
    rate_limit→backoff+rotaciona, overloaded 503/529→backoff, context_overflow→COMPACTA (não
    failover), content_policy→NUNCA repete igual. O retry consulta as dicas (errors.py atual é
    status-code based)
55. Smart approvals: LLM auxiliar julga comando flagrado (APPROVE/DENY/ESCALATE, fail-closed,
    16 max tokens) — só escalação chega no humano
56. Janelas de uso de ASSINATURA (api.anthropic.com/api/oauth/usage, codex/usage) — "quanto sobrou
    do meu plano de 5h" — direto relevante pro Okami subscription-only
57. Roteamento de modelo AUXILIAR (vision/compressão/título/juiz/aprovação em modelo barato,
    −85% custo de fundo)
58. Prompt caching Anthropic explícito (system + últimas 3 msgs, ~75% economia de input)
59. Aprovação em TIERS (once/session/always com allowlist persistida POR PADRÃO de comando)
60. Pool de credenciais persistente (ok/exhausted/dead com TTL por classe de erro)
61. Biblioteca compartilhada de threat-patterns com 3 escopos (context/strict) consumida por
    memória+skills+tool-results+arquivos de contexto
62. Bitwarden Secrets Manager como fonte de segredos (só BWS_ACCESS_TOKEN no .env)

## Ordem de implementação recomendada

ONDA A (S, dor imediata): 46+47 (rate guard cross-sessão + jitter) → 1+2+3 (compactação
anti-sequestro/anti-thrash/continuação) → 49+50 (ordem hardline/yolo + freeze no import) →
51 (untrusted delimiter) → 34 (prompts do review) → 4 (surrogates LMStudio)

ONDA B (M, qualidade do loop): 54 (classificador de erros) → 7+8 (escadas de recuperação) →
9 (poda de tool-results) → 15 (spill-to-file) → 39 (fila de aprovação de memória/skill) →
57 (modelo auxiliar) → 58 (prompt caching)

ONDA C (M/L, produto): 30 (execute_code) → 41 (/goal) → 44 (curator completo) → 22 (PTY) →
20 (patch multi-arquivo) → 27 (toolsets por canal)
