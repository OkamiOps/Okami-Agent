---
name: claude-design
description: Criar artefatos HTML com design profissional (landing, protótipo, mockup, deck) sem UI hospedada.
triggers: [design, landing, protótipo, mockup, deck, slide, visual, hero, dashboard, html]
---
# Claude Design — design de verdade

Use para artefatos HTML one-off: landing pages, protótipos, mockups, boards de opções, decks.
(Para app com ShadCN/HeroUI sob contrato, siga a skill de frontend — aqui é HTML autônomo.)

## Processo (parta do contexto, não do "gosto")
- Leia primeiro: brand docs, repo, design tokens, screenshots. Só então desenhe.

## Princípios
- **Tipografia**: escolha com propósito; reuse o sistema existente; fuja dos defaults batidos.
- **Cor**: paleta da marca primeiro; sistema novo = pequeno e com contraste verificado no texto importante.
- **Layout**: ritmo via escala, espaço em branco, densidade e alinhamento. Compreensão > decoração.
  Não repita a mesma grade de cards em tudo.
- **Movimento**: animação para clarear mudança de estado, não como espetáculo. Respeite `prefers-reduced-motion`.

## Anti-padrões (recuse)
- Gradientes agressivos, glassmorphism gratuito, emoji sem propósito, dashboards falsos, hero de stock.
- Minimalista e denso, ambos exigem escolha intencional — não caia no genérico.

## Conclusão (verificável)
- [ ] Os arquivos existem e a sintaxe está ok (rode/abra no browser).
- [ ] Sem os anti-padrões acima; contraste ok no texto importante.
