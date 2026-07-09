---
name: infografico
description: Gera infográfico (imagem) combinando 21 layouts × 21 estilos visuais a partir de um conteúdo — texto, arquivo, URL ou tópico. Porte do baoyu-infographic (JimLiu).
triggers: [infográfico, infografico, cria um infográfico, visual summary, informação visual, resume isso num infográfico, 信息图, 可视化, alta densidade de informação]
intent_examples:
  - "transforma esse texto num infográfico"
  - "faz um infográfico sobre esse artigo"
  - "quero um resumo visual desses dados"
  - "gera um infográfico de linha do tempo desse processo"
  - "monta um infográfico estilo caderno de campo com esses números"
metadata:
  hermes:
    tags: [infographic, visual-summary, creative, image-generation]
    homepage: https://github.com/JimLiu/baoyu-skills#baoyu-infographic
    category: creative
    ported_from: baoyu-infographic (JimLiu, MIT)
---

# Gerador de Infográfico

Porte do [baoyu-infographic](https://github.com/JimLiu/baoyu-skills) (JimLiu, MIT) para o ecossistema
de tools do Okami. Duas dimensões independentes: **layout** (estrutura da informação) × **estilo**
(estética visual). Qualquer layout combina com qualquer estilo.

## Quando usar

Quando o dono pedir um infográfico, resumo visual, "information graphic", ou usar termos como
"信息图", "可视化" ou "alta densidade de informação num infográfico". O dono fornece o conteúdo
(texto colado, caminho de arquivo, URL ou apenas um tópico) e, opcionalmente, layout/estilo/aspecto/
idioma.

## Opções

| Opção | Valores |
|---|---|
| Layout | 21 opções (ver Galeria de Layouts), default: `bento-grid` |
| Estilo | 21 opções (ver Galeria de Estilos), default: `craft-handmade` |
| Aspecto | Nomeado: `landscape` (16:9), `portrait` (9:16), `square` (1:1). Custom: qualquer W:H (ex.: 3:4, 4:3, 2.35:1) |
| Idioma | pt-BR, en, zh, ja etc. |

## Galeria de Layouts

| Layout | Melhor para |
|---|---|
| `linear-progression` | Linhas do tempo, processos, tutoriais |
| `binary-comparison` | A vs B, antes-depois, prós-contras |
| `comparison-matrix` | Comparações multifator |
| `hierarchical-layers` | Pirâmides, níveis de prioridade |
| `tree-branching` | Categorias, taxonomias |
| `hub-spoke` | Conceito central com itens relacionados |
| `structural-breakdown` | Vistas explodidas, cortes transversais |
| `bento-grid` | Múltiplos tópicos, visão geral (default) |
| `iceberg` | Superfície vs. aspectos ocultos |
| `bridge` | Problema-solução |
| `funnel` | Conversão, funil de filtragem |
| `isometric-map` | Relações espaciais |
| `dashboard` | Métricas, KPIs |
| `periodic-table` | Coleções categorizadas |
| `comic-strip` | Narrativas, sequências |
| `story-mountain` | Estrutura de enredo, arco de tensão |
| `jigsaw` | Partes interconectadas |
| `venn-diagram` | Conceitos sobrepostos |
| `winding-roadmap` | Jornada, marcos |
| `circular-flow` | Ciclos, processos recorrentes |
| `dense-modules` | Módulos de alta densidade, guias ricos em dado |

Definições completas: `${OKAMI_SKILL_DIR}/references/layouts/<layout>.md`

## Galeria de Estilos

| Estilo | Descrição |
|---|---|
| `craft-handmade` | Desenhado à mão, papel artesanal (default) |
| `claymation` | Figuras de argila 3D, stop-motion |
| `kawaii` | Fofo estilo japonês, pastel |
| `storybook-watercolor` | Aquarela suave, onírico |
| `chalkboard` | Giz em quadro-negro |
| `cyberpunk-neon` | Neon, futurista |
| `bold-graphic` | Estilo quadrinho, meio-tom |
| `aged-academia` | Ciência vintage, sépia |
| `corporate-memphis` | Vetor flat, vibrante |
| `technical-schematic` | Blueprint, engenharia |
| `origami` | Papel dobrado, geométrico |
| `pixel-art` | 8-bit retrô |
| `ui-wireframe` | Mockup de interface em escala de cinza |
| `subway-map` | Diagrama de metrô/transporte |
| `ikea-manual` | Linha minimalista |
| `knolling` | Flat-lay organizado |
| `lego-brick` | Construção de blocos de brinquedo |
| `pop-laboratory` | Grid blueprint, marcadores de coordenada, precisão de laboratório |
| `morandi-journal` | Doodle à mão, tons Morandi quentes |
| `retro-pop-grid` | Pop art anos 70, grid suíço, contornos grossos |
| `hand-drawn-edu` | Pastel macaron, traço à mão, bonecos-palito |

Definições completas: `${OKAMI_SKILL_DIR}/references/styles/<style>.md`

## Combinações recomendadas

| Tipo de conteúdo | Layout + Estilo |
|---|---|
| Linha do tempo/histórico | `linear-progression` + `craft-handmade` |
| Passo a passo | `linear-progression` + `ikea-manual` |
| A vs B | `binary-comparison` + `corporate-memphis` |
| Hierarquia | `hierarchical-layers` + `craft-handmade` |
| Sobreposição | `venn-diagram` + `craft-handmade` |
| Conversão | `funnel` + `corporate-memphis` |
| Ciclos | `circular-flow` + `craft-handmade` |
| Técnico | `structural-breakdown` + `technical-schematic` |
| Métricas | `dashboard` + `corporate-memphis` |
| Educacional | `bento-grid` + `chalkboard` |
| Jornada | `winding-roadmap` + `storybook-watercolor` |
| Categorias | `periodic-table` + `bold-graphic` |
| Guia de produto | `dense-modules` + `morandi-journal` |
| Guia técnico | `dense-modules` + `pop-laboratory` |
| Guia trendy | `dense-modules` + `retro-pop-grid` |
| Diagrama educacional | `hub-spoke` + `hand-drawn-edu` |
| Tutorial de processo | `linear-progression` + `hand-drawn-edu` |

Default: `bento-grid` + `craft-handmade`

## Atalhos por palavra-chave

Se a mensagem do dono contiver estas palavras, **auto-selecione** o layout associado e ofereça os
estilos associados como top recomendação no Passo 3. Pule a inferência de layout por conteúdo para
esses casos.

| Palavra-chave | Layout | Estilos recomendados | Aspecto default | Notas de prompt |
|---|---|---|---|---|
| alta densidade de informação / 高密度信息大图 / high-density-info | `dense-modules` | `morandi-journal`, `pop-laboratory`, `retro-pop-grid` | portrait | — |
| infográfico / infographic / 信息图 | `bento-grid` | `craft-handmade` | landscape | Minimalista: canvas limpo, bastante espaço em branco, sem textura de fundo complexa. Só elementos cartoon e ícones simples. |

## Estrutura de saída

```
infografico/{slug-do-topico}/
├── source-{slug}.{ext}
├── analysis.md
├── structured-content.md
├── prompts/infographic.md
└── infografico.png
```

Slug: 2-4 palavras em kebab-case a partir do tópico. Conflito: acrescenta `-YYYYMMDD-HHMMSS`.

## Princípios centrais

- Preserva o dado-fonte com fidelidade — sem resumir ou reparafrasear (mas **remova qualquer
  credencial, chave de API ou segredo** antes de incluir em qualquer arquivo de saída).
- Defina os objetivos de aprendizado antes de estruturar o conteúdo.
- Estruture para comunicação visual (títulos, rótulos, elementos visuais).

## Fluxo de trabalho

### Passo 1: Analisar o conteúdo

**Carregue a referência**: leia `${OKAMI_SKILL_DIR}/references/analysis-framework.md`.

1. Salve o conteúdo-fonte (caminho de arquivo ou colado → `source.md` usando `write_file`).
   - **Regra de backup**: se `source.md` já existe, renomeie para `source-backup-YYYYMMDD-HHMMSS.md`.
2. Analise: tópico, tipo de dado, complexidade, tom, público.
3. Detecte o idioma da fonte e o idioma do dono.
4. Extraia instruções de design da mensagem do dono.
5. Salve a análise em `analysis.md`.
   - **Regra de backup**: se `analysis.md` já existe, renomeie para `analysis-backup-YYYYMMDD-HHMMSS.md`.

Formato detalhado em `${OKAMI_SKILL_DIR}/references/analysis-framework.md`.

### Passo 2: Gerar conteúdo estruturado → `structured-content.md`

Transforma o conteúdo na estrutura do infográfico:
1. Título e objetivos de aprendizado.
2. Seções com: conceito-chave, conteúdo (literal), elemento visual, rótulos de texto.
3. Dados (todas as estatísticas/citações copiadas exatamente).
4. Instruções de design vindas do dono.

**Regras**: só markdown. Nenhuma informação nova. Preserva o dado com fidelidade. Remove segredos
do output.

Formato detalhado em `${OKAMI_SKILL_DIR}/references/structured-content-template.md`.

### Passo 3: Recomendar combinações

**3.1 Verifique os atalhos de palavra-chave primeiro**: se a mensagem do dono bater com uma palavra
da tabela de Atalhos, auto-selecione o layout associado e priorize os estilos associados. Pule a
inferência por conteúdo.

**3.2 Senão**, recomende 3-5 combinações layout×estilo baseado em:
- Estrutura do dado → layout correspondente
- Tom do conteúdo → estilo correspondente
- Expectativa do público
- Instruções de design do dono

### Passo 4: Confirmar opções

Use a tool `clarify` para confirmar opções com o dono, uma pergunta por vez:

**P1 — Combinação**: apresente 3+ combos layout×estilo com justificativa. Peça para o dono escolher.

**P2 — Aspecto**: pergunte a preferência de proporção (landscape/portrait/square ou W:H custom).

**P3 — Idioma** (só se fonte ≠ idioma do dono): pergunte em que idioma o texto deve sair.

### Passo 5: Gerar prompt → `prompts/infographic.md`

**Regra de backup**: se `prompts/infographic.md` já existe, renomeie para
`prompts/infographic-backup-YYYYMMDD-HHMMSS.md`.

**Carregue as referências**: leia o layout escolhido em `${OKAMI_SKILL_DIR}/references/layouts/<layout>.md`
e o estilo em `${OKAMI_SKILL_DIR}/references/styles/<style>.md`.

Combine:
1. Definição do layout.
2. Definição do estilo.
3. Template base: `${OKAMI_SKILL_DIR}/references/base-prompt.md`.
4. Conteúdo estruturado do Passo 2.
5. Todo texto no idioma confirmado.

**Resolução do aspecto** para `{{ASPECT_RATIO}}`:
- Presets nomeados → string de proporção: landscape→`16:9`, portrait→`9:16`, square→`1:1`.
- Proporções custom W:H → usa como está (ex.: `3:4`, `4:3`, `2.35:1`).

Salve o prompt montado em `prompts/infographic.md` usando `write_file`.

### Passo 6: Gerar a imagem

Use a tool `generate_image` com o prompt montado no Passo 5.

- Mapeie a proporção pro formato aceito pela tool: `16:9` → `landscape`, `9:16` → `portrait`,
  `1:1` → `square`.
- Para proporções custom, escolha o aspecto nomeado mais próximo.
- Em caso de falha, tente de novo automaticamente uma vez.
- Salve o caminho/URL da imagem resultante no diretório de saída.

### Passo 7: Resumo final

Reporte: tópico, layout, estilo, aspecto, idioma, caminho de saída, arquivos criados.

## Referências

- `${OKAMI_SKILL_DIR}/references/analysis-framework.md` — metodologia de análise
- `${OKAMI_SKILL_DIR}/references/structured-content-template.md` — formato de conteúdo
- `${OKAMI_SKILL_DIR}/references/base-prompt.md` — template de prompt
- `${OKAMI_SKILL_DIR}/references/layouts/<layout>.md` — 21 definições de layout
- `${OKAMI_SKILL_DIR}/references/styles/<style>.md` — 21 definições de estilo

## Armadilhas

1. **Fidelidade do dado é inegociável** — nunca resuma, parafraseie ou altere estatísticas da fonte.
   "aumento de 73%" continua "aumento de 73%", não "aumento expressivo".
2. **Remova segredos** — sempre escaneie o conteúdo-fonte por chaves de API, tokens ou credenciais
   antes de incluir em qualquer arquivo de saída.
3. **Uma mensagem por seção** — cada seção do infográfico deve carregar um conceito claro.
   Sobrecarregar seções reduz a legibilidade.
4. **Consistência de estilo** — a definição do estilo escolhido deve valer para o infográfico
   inteiro. Não misture estilos.
5. **Proporções de `generate_image`** — a tool normalmente só aceita `landscape`, `portrait` e
   `square`. Proporções custom como `3:4` mapeiam pro mais próximo (portrait, nesse caso).
