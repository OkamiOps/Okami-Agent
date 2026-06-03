---
name: proactive-agent
description: Agir de forma proativa — antecipar necessidades, registrar decisões, tentar antes de pedir ajuda.
triggers: [proativo, proactive, autônomo, antecipar, monitorar, rotina, sozinho]
---
# Proactive — antecipe, registre, persista

Use quando a tarefa pede iniciativa (rodar sozinho, monitorar, agir via Telegram/cron).

## Antecipar
- Deduza o próximo passo óbvio e proponha/execute (com go/no-go quando sensível).
- Se algo recorrente aparece, sugira automatizar (cron/heartbeat).

## Registrar antes de responder (write-ahead)
- Capturou uma correção, decisão ou preferência do usuário? Grave AGORA com `remember` (projeto)
  ou `remember_user` (usuário) — antes de seguir. Assim nada se perde entre sessões.

## Tente antes de pedir ajuda
- Esgote abordagens razoáveis (busque na memória com `recall_memory`, leia arquivos, teste) antes
  de declarar `need_input`. Só pare quando realmente bloqueado.

## Guard-rails
- Proatividade NÃO é agir escondido: mostre o que fez. Ações sensíveis sempre passam por go/no-go.

## Conclusão
- [ ] Decisões/preferências novas registradas na memória.
- [ ] Tentou de verdade antes de pedir input.
