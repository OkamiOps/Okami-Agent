---
name: delegate-claude
description: Quando usar/escalar para o Claude (raciocínio profundo, refatoração grande, decisões de design).
triggers: [claude, raciocínio, refatorar, arquitetura, design difícil, revisar, escalar]
---
# Delegar ao Claude

No Okami, Claude é um provider (via assinatura). Use-o quando a tarefa pede **raciocínio
profundo** ou qualidade alta.

## Quando preferir o Claude
- Refatorações grandes, decisões de arquitetura, revisão crítica de código.
- Design/escrita que exige nuance e bom gosto.
- Quando um modelo mais fraco travou: escale (o harness faz cascata, ou rode com `-p claude`).

## Como
- Tarefa nova de alto valor → `okami task ... -p claude`.
- Em execução, se o modelo atual patina, deixe a **cascata** (`--escalate claude`) assumir.

## Conclusão
- [ ] A tarefa realmente exige a capacidade extra (senão use modelo mais barato).
