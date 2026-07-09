---
name: frontend-design
description: Design de frontend com ponto de vista — foge do visual genérico de IA (cards cinza, tudo centralizado, gradiente roxo) e escolhe direção estética, tipografia, cor e hierarquia antes de codar.
triggers: [frontend, front-end, ui, interface, componente, landing, dashboard, página, pagina, tela, app, design, layout, site, web, hero, mockup]
intent_examples:
  - "cria uma landing page para o produto"
  - "monta esse dashboard"
  - "desenha essa tela de configurações"
  - "essa interface tá com cara de IA, deixa mais interessante"
  - "faz um site bonito pra isso"
  - "melhora o visual desse componente"
metadata:
  hermes:
    tags: [frontend, design, ui, ux, css, typography, layout, motion, responsive, a11y]
    related_skills: [frontend-heroui, frontend-shadcn]
    category: creative
---

# Design de Frontend

Guia de **direção e taste**, não de biblioteca específica. Use isto sempre que for construir ou
redesenhar qualquer superfície web — landing, dashboard, componente, formulário, app shell — antes
de escrever a primeira linha de CSS.

Se o projeto já usa **HeroUI** ou **shadcn/ui**, carregue também a skill `frontend-heroui` ou
`frontend-shadcn` (instalação, provider, regras de composição daquela lib) — esta skill aqui cuida
do julgamento visual que vem ANTES de escolher componentes; aquelas cuidam da implementação com a
lib certa. Para gerar um PDF a partir do resultado (relatório, one-pager), use a tool `generate_pdf`
— não suba Chromium/Puppeteer para isso.

## O problema: "cara de IA"

Modelos convergem para o mesmo default: cards cinza com sombra leve, tudo centralizado, herói +
três cartões de feature do mesmo tamanho, gradiente azul→roxo, emoji como ícone de seção, Inter em
todo lugar. Isso não é "limpo", é **falta de decisão**. O antídoto é decidir a estética ANTES de
tocar em código — a escolha de cor/tipografia não conserta uma composição que nunca foi pensada.

## 1. Escolha uma direção antes de codar

Antes de qualquer token de cor ou fonte, diga em uma frase que tipo de superfície é essa e que
postura ela assume. Não existe "estilo padrão" — existe a escolha:

- **Editorial** — hierarquia tipográfica forte, texto como protagonista, muito respiro.
- **Brutalista** — bordas duras, contraste alto, grid exposto, pouca ou nenhuma sombra.
- **Refinado-minimal** — paleta contida, um acento só, muito espaço em branco, precisão.
- **Playful** — cor saturada, formas orgânicas, motion com personalidade.
- **Técnico/denso** — mono para dados, densidade de informação, foco em velocidade de leitura.

E o tipo de tela também muda a composição: um **dashboard** (o usuário está observando estado) não
leva herói nem cartões de feature — leva densidade e hierarquia glanceável. Um **formulário/config**
leva disclosure progressivo, não decoração. Um **console/admin** prioriza affordance de ação. Herói
+ três cards só é certo para página de conversão (landing, pricing) — usar isso em qualquer outra
tela é o tell nº1 de "gerado por IA".

## 2. Tipografia

- Escolha uma escala real (ex.: 12/14/16/20/24/32/48/64), não tamanhos aleatórios.
- Contraste de peso importa mais que quantidade de fontes: 1-2 famílias, 2-3 pesos cada, geralmente
  chega.
- Combine com intenção: serif/humanista para título + sans neutra pro corpo (editorial); uma sans
  precisa com números tabulares (produto/dado); mono só como acento técnico, nunca no texto todo.
- `line-height` generoso no corpo (1.5-1.7), mais apertado no título (1.1-1.25).
- Limite a medida de leitura: ~60-75 caracteres por linha de parágrafo (`max-width` em `ch`).
- Evite Inter/system-ui por padrão só porque é o que "sempre funciona" — escolha porque combina com
  a direção escolhida no passo 1.

## 3. Cor

- Defina uma paleta pequena com papel definido: fundo, superfície, texto principal, texto
  secundário, borda, um acento primário, e estado (sucesso/erro/alerta) só se o produto precisar.
- Um acento primário só, a não ser que o produto exija mais. Nada de arco-íris.
- Fuja do azul→roxo genérico de "tech" a não ser que a marca já use isso — escolha um matiz que
  tenha relação com o produto.
- Sempre com par claro/escuro (`prefers-color-scheme` ou classe de tema) — não é opcional em 2026.
- Confira contraste de texto e de controles interativos (mínimo AA: 4.5:1 texto normal, 3:1 texto
  grande/ícone).

## 4. Layout e hierarquia

- Comece pelo grid e pelo ponto focal, não pela lista de seções.
- Assimetria é permitida e às vezes correta — nem toda seção precisa ser um grid de cards iguais.
- Espaço em branco é hierarquia, não "sobra" — use ritmo (grande/pequeno alternando), não espaçamento
  uniforme em tudo.
- Evite decoração que finge ser organização: barra colorida na lateral do card, blur decorativo sem
  sistema de elevação por trás, número gigante sem história por trás.
- Para dashboards: só mostre dado que ajuda a decidir ou agir — "data slop" é pior que pouco dado.

## 5. Motion e micro-interações

- Motion existe para comunicar estado (carregando, transição, confirmação), não para decorar.
- Hover/focus devem ter feedback real — nunca deixe um elemento clicável sem estado visual.
- Transições curtas (150-250ms) para UI; algo maior (300-500ms) só para mudança de contexto grande.
- Respeite `prefers-reduced-motion` sempre que a animação for não-trivial.
- Evite loop infinito sem propósito e qualquer coisa que atrase a ação do usuário.

## 6. Responsivo

- Mobile-first: defina o layout mais estreito primeiro, depois expanda.
- Breakpoints reais (ex.: 480/768/1024/1280), não "quebra quando quebrar".
- Alvo de toque mínimo 44px em mobile.
- Teste o que acontece com conteúdo real longo (nome grande, lista vazia, texto traduzido maior).

## 7. Checklist de polimento antes de dar como pronto

Estados:
- [ ] hover, focus (anel visível, nunca `outline: none` sem substituto), active
- [ ] vazio (empty state com ação, não só "nada aqui")
- [ ] erro (mensagem específica, não genérica)
- [ ] carregando (skeleton ou spinner coerente com o resto do design)

Acessibilidade:
- [ ] contraste AA nos textos e controles
- [ ] HTML semântico (`button`, `nav`, `main`, `label` associado a input — não `div` com `onClick`
  em tudo)
- [ ] navegação por teclado funciona (tab order, foco visível)

Performance:
- [ ] imagens com dimensão declarada (evita layout shift)
- [ ] fontes carregadas sem bloquear render (poucos pesos, `font-display: swap`)
- [ ] sem dependência pesada só para um efeito pequeno

## Diagnóstico rápido de "cara de IA" (rode antes de entregar)

Pontue 1 para cada item presente — quanto maior, mais genérico:

1. Gradiente azul/roxo brilhante em tudo.
2. Grid de 3 cards do mesmo tamanho com ícone + título + frase, sem prioridade entre eles.
3. Tudo centralizado, nenhuma composição assimétrica.
4. Barra colorida na lateral do card fingindo ser organização.
5. Número gigante sem contexto real por trás.
6. Ícone redondo centralizado acima de todo título de seção.
7. Fonte padrão (Inter/system-ui) sem ter sido escolhida por motivo nenhum.
8. Herói + três cards numa tela que não é de conversão (ex.: num dashboard).

Se pontuou 3+, o problema provavelmente é de **composição** (itens 2, 3, 8) — resolva mudando o
grid/hierarquia, não trocando cor. Itens 1 e 7 se resolvem trocando paleta/tipografia. Itens 4, 5, 6
se resolvem removendo a decoração e substituindo por hierarquia real (escala, peso, espaço).

## Exemplo: antes / depois de um hero

**Antes (genérico)**: título centralizado em Inter bold, gradiente azul→roxo de fundo, subtítulo
cinza claro, botão arredondado com sombra, três ícones abaixo em círculos idênticos, tudo com o
mesmo peso visual.

**Depois (com ponto de vista, direção "editorial")**:
- Título alinhado à esquerda, serif de exibição em tamanho grande (ex.: 64px), não centralizado.
- Fundo sólido (não gradiente) na cor de marca, com UM elemento de imagem/textura assimétrico do
  lado direito, não atrás do texto.
- Subtítulo em sans neutra, medida de leitura curta (~50ch), contraste alto de texto (não cinza
  claro sobre branco).
- Um único CTA com peso tipográfico forte, sem sombra decorativa — o contraste de cor já resolve.
- Nada de trio de ícones circulares embaixo; se precisar de prova social, um número real com
  contexto (não "10k+ usuários" solto) ou nada.

O que mudou: a **composição** (assimetria em vez de centro), a **tipografia** (serif com intenção em
vez de Inter default) e a **cor** (sólida com propósito em vez de gradiente genérico) — nessa ordem
de prioridade, porque composição é o que mais denuncia "gerado por IA".

## Os 10 estilos do Marcos

Se o pedido pedir explicitamente um dos mundos visuais do dono (arquitetura brutalista/serena,
dark tech científico, robótica lúdica, saúde/longevidade, marca real Agent Smith/Lionclaw) ou só
"faz um site no meu estilo", carregue o catálogo completo com paleta, tipografia, layout, motion e
o movimento distintivo de cada um dos 10 sites de demonstração dele, mais a seção "como reproduzir"
com as técnicas comuns aos 10:
`${OKAMI_SKILL_DIR}/references/estilos-do-marcos.md`.
