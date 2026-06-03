---
name: honcho-memory
description: Usar bem a memória de modelo-do-usuário (Honcho) — consultar o que se sabe do usuário e registrar.
triggers: [honcho, usuário, preferências, perfil, contexto do usuário, lembrar]
---
# Honcho / Memória do usuário

Use quando a tarefa depende de entender o usuário (preferências, histórico, decisões passadas).
No Okami, o backend `honcho` (quando ativo) é um oráculo de modelo-do-usuário.

## Antes de agir
- Consulte o que já se sabe: `recall_memory` com uma pergunta natural ("o que o usuário prefere
  em frontend?"). Use o resultado para personalizar — não pergunte o que já está na memória.

## Durante/depois
- Aprendeu uma preferência durável? Grave com `remember_user`. Decisão de projeto? `remember`.
- Não invente fatos sobre o usuário — só use o que veio da memória (com proveniência).

## Conclusão
- [ ] Consultou a memória do usuário antes de assumir.
- [ ] Registrou preferências/decisões novas.
