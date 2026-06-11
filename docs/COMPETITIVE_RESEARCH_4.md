# Pesquisa competitiva #4 — gaps vs Hermes (jun/2026)

Varredura do repo `NousResearch/hermes-agent` (CLI, gateway, docs) atrás de conveniências
que o Okami ainda não tem. Tamanhos: S/M/L. ✅ = já implementado no Okami.

## Implementado nesta rodada

- ✅ `okami gateway start|stop|status|restart` — lifecycle por subcomando (antes: só flags, sem restart)
- ✅ `/restart` no chat — reinicia o gateway pelo Telegram (delega ao CLI destacado; guarda contra
  gateway foreground/serviço p/ não criar 2 processos disputando o getUpdates)
- ✅ `okami send "msg" --to telegram:<id> -a <agente>` — entrega SEM LLM p/ scripts/cron/CI
  (default: chat casa do /sethome; aceita stdin com `-`)

## Já tínhamos (paridade)

`/sethome`, `/usage`, `/reload` (hot-reload config), `/background`, `/sessions`/`/resume`/`/export`,
`/yolo`, pareamento DM com código, `okami doctor --fix --json --lint`, `okami service install`
(launchd/systemd), `okami logs -f -n`, monitor de memória `[MEMORY]`, cron com `[SILENT]` +
wake-gate + multi-target, checkpoints de arquivo, `@file/@url/@gitdiff`, perfis de auth,
fallback de provider, footer ctx/tok, i18n, TUI.

## Backlog priorizado (o que falta, por alavancagem)

### S — pequenos, alto retorno
1. `okami logs --since 1h --level warn` + errors.log separado (WARNING+) e rotação de log
2. `okami dump` — resumo de setup copiável p/ bug report (chaves redigidas a 4 chars)
3. `okami status --all` redigido/compartilhável
4. Dica de retomada ao sair do chat (imprime o comando `okami chat -c ...` pronto)
5. Startup tips (1 dica aleatória por sessão, corpus ~150)
6. `okami prompt-size` — breakdown offline de bytes do system prompt (skills/memória/tools)
7. Guarda de colisão de token (2 perfis com o mesmo bot token → 2º recusa subir)
8. Forense de shutdown (quem matou o gateway: snapshot no SIGTERM)
9. `gateway status --deep` (health check além de "pid vivo")

### M — médios
10. `okami update` — git pull + validação de sintaxe + rollback automático + restart do gateway;
    banner "N commits atrás" (cache 6h); `/update` do chat
11. `okami config set|check|migrate` — set roteia segredo p/ .env; check acha opção faltando/obsoleta
12. `/approve [session|always]` / `/deny` — aprovação de comando perigoso DO CHAT com allowlist permanente
13. Rate-limit tracker — captura headers x-ratelimit-*, guarda cross-sessão (CLI/gateway/cron não
    amplificam 429); mostra no /usage  ← ataca o "overloaded" do Marcos
14. Aux-model routing — visão/compressão/título/judge em modelo barato (Hermes: -85% custo de fundo)
15. `okami sessions stats|prune --older-than` 
16. `/steer` — injeta contexto após o próximo tool-call sem quebrar o loop
17. `okami webhook` — ativação por evento com HMAC + `--deliver-only` (zero-LLM)
18. Circuit breaker por plataforma + `/platform pause|resume`
19. `okami insights --days 30` — análise de custo/uso por período e por canal

### L — grandes
20. `/goal` — loop de objetivo persistente com judge auxiliar e orçamento de turnos
21. `/handoff telegram` — migra sessão viva do CLI pro Telegram (replay do transcript)
22. Update pipeline completo (validação 8 arquivos críticos + rollback git)
23. Curator de skills em background com snapshot/rollback (parcial: temos curator CLI)
24. Quadro kanban multi-perfil (provavelmente fora de escopo)
