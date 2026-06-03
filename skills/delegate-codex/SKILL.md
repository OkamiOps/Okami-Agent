---
name: delegate-codex
description: Quando usar/escalar para o Codex/GPT (geração de código, fluxos longos de codificação).
triggers: [codex, gpt, gerar código, implementar, scaffold, código longo, escalar]
---
# Delegar ao Codex / GPT

No Okami, Codex/GPT é um provider (via assinatura). Use-o para **codificação** e fluxos longos.

## Quando preferir o Codex
- Geração/implementação de código, scaffolding, fluxos multi-passo de codificação.
- Tarefas de código onde velocidade/volume importam.

## Como
- `okami task ... -p codex` para a tarefa.
- Se um modelo local/fraco emperrar num passo de código, deixe a cascata (`--escalate codex`) assumir.

## Lembre
- Mesmo com Codex, valem as invariantes: ação por turno, gates de design, testes (`shell_ok`).

## Conclusão
- [ ] Usado para o que ele é bom (código); resto pode ir em modelo mais barato.
