---
name: sketch
description: Mockups HTML descartáveis — 2-3 variantes de direção visual pra comparar antes de comprometer com uma implementação final.
triggers: [sketch, mockup, esboço, protótipo, me mostra como ficaria, compara variante, 2 opções de design, antes de implementar, rascunho de tela]
intent_examples:
  - "me mostra 2-3 jeitos que essa tela poderia ficar antes de eu decidir"
  - "faz um esboço dessa página, quero comparar direções"
  - "compara uma versão densa com uma mais arejada desse dashboard"
  - "quero ver o layout antes de você construir de verdade"
metadata:
  hermes:
    tags: [sketch, mockup, design, ui, prototype, html, variants, exploration, wireframe, comparison]
    category: creative
---

# Sketch — mockups descartáveis pra comparar direção

Use quando o pedido é **ver uma direção de design antes de comprometer** com a implementação final
— não é sobre gerar código pra produção, é sobre gerar 2-3 variantes HTML jogáveis-fora rápido o
bastante pra comparação valer a pena.

Carregue esta skill quando ouvir algo como "esboça essa tela", "me mostra como isso poderia ficar",
"compara layout A com B", "me dá 2-3 opções antes de eu escolher", "quero ver antes de construir".

## Quando NÃO usar

- O pedido é um componente de produção → construa direto, sem sketch.
- É um artefato HTML único e já polido (landing page final, deck) → construa direto.
- É diagrama/fluxograma → não é este skill.
- A direção já está travada (o dono já decidiu o visual) → só construa.

## Método

```
levantar contexto → gerar variantes → comparar lado a lado → dono escolhe (ou pede outra rodada)
```

### 1. Levantar contexto (pule se já tiver o suficiente)

Antes de gerar variantes, precisa de três coisas — uma pergunta de cada vez, não tudo de uma vez:

1. **Sensação.** "Como isso deveria parecer? Adjetivos, emoção, vibe." — "calmo, editorial, tipo
   Linear" diz mais que "minimalista".
2. **Referências.** "Que apps/sites capturam a sensação que você imagina?" — referência real vale
   mais que descrição abstrata. Se a referência bater com algo do catálogo `design-systems`, use-o.
3. **Ação principal.** "Qual é a única coisa mais importante que o usuário faz nessa tela?" — todas
   as variantes precisam servir bem essa ação; se não servem, é só decoração.

Reflita brevemente cada resposta antes da próxima pergunta. Se o dono já deu as três de cara, pule
direto pras variantes.

### 2. Gerar variantes (2-3, nunca 1, raramente 4+)

Produza **2-3 variantes** de uma vez. Cada variante é um arquivo HTML completo e autocontido — não
descreva a variante, construa. O ponto é a comparação lado a lado.

Cada variante precisa assumir uma **postura de design diferente**, não só um valor de pixel
diferente. Eixos bons pra puxar variantes:

- **Densidade:** compacto / arejado / ultra-denso (pegue dois polos que contrastam)
- **Ênfase:** conteúdo-primeiro / ação-primeiro / ferramenta-primeiro
- **Estética:** editorial / utilitário / lúdico
- **Layout:** coluna única / sidebar / split-pane
- **Base:** cartões / conteúdo nu / estilo documento

Escolha um eixo e puxe pros dois lados. Duas variantes que só mudam a cor de acento são esforço
desperdiçado — o dono não consegue distinguir.

**Nomeie pela postura, não pelo número:**

```
sketches/
├── 001-calmo-editorial/
│   ├── index.html
│   └── README.md
├── 001-utilitario-denso/
│   ├── index.html
│   └── README.md
└── 001-ludico-split/
    ├── index.html
    └── README.md
```

Puxando de sistemas reais? Combine com a skill `design-systems` — cada variante pode ancorar num
sistema diferente do catálogo (ex.: uma variante "estilo Linear" dark-mode vs. uma "estilo Notion"
warm-minimal) em vez de inventar paleta do zero.

### 3. Fazer o HTML de verdade

Cada variante é um **arquivo HTML único e autocontido**:

- `<style>` inline — sem build step, sem CSS externo.
- Fonte de sistema, ou uma Google Font via `<link>` (veja `design-systems` pra referências reais).
- Tailwind via CDN (`<script src="https://cdn.tailwindcss.com"></script>`) é aceitável.
- Conteúdo falso realista — frases de verdade, nomes de verdade, não "lorem ipsum".
- **Interativo**: links clicáveis, hover de verdade, pelo menos uma transição de estado
  (abrir/fechar, filtrar, alternar). Uma imagem estática congelada é pior sketch que algo tosco
  mas animado.

Abra no navegador e confira antes de mostrar ao dono. Se estiver quebrado, conserte antes.

**Reset CSS + stack de fonte de sistema pra começar rápido:**

```html
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                 "Helvetica Neue", Arial, sans-serif;
    -webkit-font-smoothing: antialiased;
    color: #1a1a1a;
    background: #fafafa;
    line-height: 1.5;
  }
</style>
```

Um esqueleto HTML completo pronto pra copiar está em
`${OKAMI_SKILL_DIR}/references/esqueleto.html`.

### 4. README de cada variante

O `README.md` de cada variante responde:

```markdown
## Variante: {nome da postura}

### Postura de design
Uma frase sobre o princípio que guia esta variante.

### Escolhas-chave
- Layout: ...
- Tipografia: ...
- Cor: ...
- Interação: ...

### Trade-offs
- Forte em: ...
- Fraco em: ...

### Melhor para
- Que tipo de usuário/caso de uso esta variante realmente serve
```

### 5. Comparação lado a lado

Depois de construir todas as variantes, apresente como comparação. Não liste só — **opine**:

```markdown
## Três direções pra tela inicial

| Dimensão | Calmo editorial | Utilitário denso | Lúdico split |
|---|---|---|---|
| Densidade | Baixa | Alta | Média |
| Visibilidade da ação principal | Baixa | Alta | Média |
| Facilidade de escanear | Alta | Média | Baixa |
| Sensação | Calma, confiável | Afiada, ferramenta | Convidativa, energética |

**Minha opinião:** utilitário denso pra usuário avançado, calmo editorial pra público voltado a
conteúdo. Lúdico split é o mais fraco — tenta fazer as duas coisas e não se compromete com nenhuma.
```

Deixe o dono escolher um vencedor, combinar duas num híbrido, ou pedir mais uma rodada.

## Barra de interatividade

Um sketch está interativo o bastante quando o dono consegue:

1. **Clicar numa ação principal** e algo visível acontece (mudança de estado, modal, toast, feint
   de navegação).
2. **Ver uma transição de estado significativa** (filtrar lista, alternar modo, abrir/fechar painel).
3. **Passar o mouse por affordances reconhecíveis** (botões, linhas, abas).

Mais que isso é engenharia demais pra um descartável. Menos que isso é só um screenshot.

## Saída

- Crie `sketches/` na raiz do repo (ou `.planning/sketches/` se o projeto já usa essa convenção).
- Uma subpasta por variante: `NNN-nome-da-postura/index.html` + `README.md`.
- Diga ao dono como abrir: `open sketches/001-calmo-editorial/index.html` no macOS, `xdg-open` no
  Linux, `start` no Windows.
- Mantenha as variantes descartáveis — um sketch que você sentiu vontade de preservar deveria virar
  código real do projeto, não ficar curado como artefato permanente.

## Cuidados

- Não copie marca/logo de terceiros de forma enganosa — pegue emprestado o *vocabulário* visual
  (peso de fonte, paleta, ritmo), não a identidade exata de um concorrente do dono.
- Verifique visualmente antes de apresentar — HTML que "parece certo" na leitura da fonte pode
  quebrar no navegador (import de fonte falhou, flex colapsou). Abra e confira.
