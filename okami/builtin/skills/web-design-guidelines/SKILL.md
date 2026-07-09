---
name: web-design-guidelines
description: Revisa código de UI web contra o checklist "Web Interface Guidelines" da Vercel — a11y, foco, formulários, animação, tipografia, performance, hidratação. Use para "revisa minha UI", "audita acessibilidade", "checa boas práticas de front", antes de dar uma tela como pronta.
triggers: [revisa ui, revisa interface, audita acessibilidade, checa acessibilidade, boas praticas de front, boas práticas de front, review de ui, code review frontend, web interface guidelines, aria, foco visivel, contraste]
intent_examples:
  - "revisa esse componente contra as guidelines de UI"
  - "audita a acessibilidade dessa página"
  - "checa se esse formulário segue boas práticas"
  - "essa tela tá pronta pra produção? revisa antes"
metadata:
  source: https://github.com/vercel-labs/agent-skills (skills/web-design-guidelines) + https://github.com/vercel-labs/web-interface-guidelines
  hermes:
    tags: [frontend, a11y, accessibility, code-review, ui, checklist]
    related_skills: [frontend-design, vercel-react-best-practices]
    category: creative
---

# Web Interface Guidelines

Skill portada do agent-skills da Vercel (`vercel-labs/agent-skills`). Revisa arquivos de UI contra
o checklist "Web Interface Guidelines" — rode isto **antes** de dar uma tela/componente como pronto,
não só quando o usuário pede explicitamente "acessibilidade".

## Como funciona

1. Se possível, busque a versão mais recente das guidelines em
   `https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md` (via
   `WebFetch`) — o checklist evolui. Se não houver rede, use a cópia local abaixo
   (`references/web-interface-guidelines.md`), que é fiel à fonte no momento da portagem.
2. Leia os arquivos indicados (ou pergunte qual arquivo/padrão revisar, se não foi dito).
3. Confira cada regra do checklist contra o código.
4. Produza o resultado no formato terso `arquivo:linha` — sem preâmbulo, sem explicar o óbvio.

## Fonte das regras

O checklist completo (acessibilidade, estados de foco, formulários, animação, tipografia,
tratamento de conteúdo, imagens, performance, navegação/estado, toque/interação, safe areas,
dark mode, i18n, hidratação, hover, copy, anti-patterns) está em
`${OKAMI_SKILL_DIR}/references/web-interface-guidelines.md`.

## Formato de saída

Agrupe por arquivo, use `arquivo:linha` (clicável em editores), findings tersos:

```text
## src/Button.tsx

src/Button.tsx:42 - icon button missing aria-label
src/Button.tsx:18 - input lacks label
src/Button.tsx:55 - animation missing prefers-reduced-motion
src/Button.tsx:67 - transition: all → list properties

## src/Modal.tsx

src/Modal.tsx:12 - missing overscroll-behavior: contain
src/Modal.tsx:34 - "..." → "…"

## src/Card.tsx

✓ pass
```

Estado do problema + localização. Pule a explicação a não ser que o fix não seja óbvio. Sem
preâmbulo.
