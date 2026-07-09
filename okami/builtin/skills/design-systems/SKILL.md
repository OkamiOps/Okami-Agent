---
name: design-systems
description: Catálogo de ~50 sistemas de design reais (Stripe, Linear, Vercel, Notion...) — cor, tipografia, spacing, sombra — pra ancorar UI numa estética coerente e real, em vez de genérica.
triggers: [design system, estilo de site, parece com, faz igual a, landing page, dashboard, criar ui, design de página, paleta de cores, tipografia, referência visual]
intent_examples:
  - "faz essa página parecer com a Stripe"
  - "quero um dashboard no estilo Linear"
  - "cria uma landing page bonita, com boa tipografia"
  - "que paleta de cor combina com um app fintech?"
  - "dá uma cara mais premium nesse site"
metadata:
  hermes:
    tags: [design, css, html, ui, web-development, design-systems, templates]
    category: creative
---

# Design Systems — catálogo de referências reais

Sempre que for gerar HTML/CSS de uma UI do zero, a tentação padrão é cair num visual genérico
("Bootstrap default", roxo-com-gradiente sem propósito, cards com `border-radius: 8px` em tudo).
Esta skill existe pra cortar esse caminho: um catálogo de **sistemas de design reais**, de
empresas que investiram pesado em identidade visual, com o suficiente de cada um (paleta,
tipografia, spacing, sombra, tom) pra você ancorar a UI numa estética coerente de verdade — não
inventada, não genérica.

Não é sobre copiar pixel a pixel (evite reproduzir logo/marca de terceiros de forma enganosa) —
é sobre **pegar emprestado o vocabulário visual** (peso de fonte, paleta, ritmo de espaçamento,
como as sombras se comportam) pra construir algo com a mesma qualidade de acabamento.

## Como usar

1. Identifique o tom que o pedido pede (dashboard técnico? landing de marketing? app fintech?
   documentação?) — veja "Escolhendo um sistema" abaixo.
2. Carregue o catálogo completo com `use_skill(name="design-systems", path="references/sistemas.md")`
   — lá tem paleta, tipografia e traços de cada sistema em 2-4 linhas.
3. Aplique os tokens (cor, fonte, spacing, sombra) na hora de gerar o HTML/CSS — trate como
   variáveis CSS (`:root { --color-accent: ... }`), não como decoração solta.
4. Se a fonte original for proprietária (a maioria é), use o substituto do Google Fonts indicado
   na referência — mantém o caráter sem depender de licença que você não tem.

Combine com a skill `sketch` quando o pedido for "me mostra 2-3 direções antes de eu decidir" —
cada variante do sketch pode puxar de um sistema diferente deste catálogo.

## Escolhendo um sistema (atalho rápido)

- **Ferramenta de dev / dashboard técnico:** Linear, Vercel, Supabase, Sentry, Raycast
- **Documentação / conteúdo:** Notion, Mintlify, Sanity, MongoDB
- **Marketing / landing page:** Stripe, Apple, Framer, SpaceX
- **Modo escuro:** Linear, Cursor, ElevenLabs, Warp, Superhuman
- **Modo claro / limpo:** Vercel, Stripe, Notion, Cal.com
- **Divertido / amigável:** PostHog, Figma, Zapier, Miro, Airbnb
- **Premium / luxo:** Apple, BMW, Stripe, Revolut
- **Denso em dado / dashboards:** Sentry, Kraken, Cohere, ClickHouse
- **Monospace / terminal:** Ollama, OpenCode, x.ai, Warp

O catálogo completo (todas as categorias, todos os sistemas) está em
`${OKAMI_SKILL_DIR}/references/sistemas.md`.
