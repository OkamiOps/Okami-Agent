---
name: powerpoint
description: Cria, lê e edita apresentações .pptx — do zero (pptxgenjs) ou a partir de um template existente (unpack/edit XML/pack). Cobre paleta, tipografia, layout e checklist de QA visual.
triggers: [pptx, powerpoint, apresentação, apresentacao, slide, slides, deck, pitch deck, cria uma apresentação, monta os slides]
intent_examples:
  - "monta uma apresentação sobre esse relatório"
  - "cria um deck de 10 slides pra esse pitch"
  - "edita esse template de powerpoint com os dados novos"
  - "extrai o texto dessa apresentação"
  - "revisa se os slides ficaram bonitos"
metadata:
  hermes:
    tags: [powerpoint, pptx, slides, presentation, office]
    category: productivity
    ported_from: anthropic powerpoint skill
---

# PowerPoint

## Quando usar

Sempre que um arquivo `.pptx` estiver envolvido de qualquer forma — como entrada, saída ou os dois:
criar deck/apresentação/pitch; ler, extrair texto ou analisar um `.pptx` (mesmo que o conteúdo vá
virar resumo/email depois); editar apresentação existente; combinar/dividir slides; trabalhar com
template, layout, notas do apresentador ou comentários. Dispara sempre que o dono mencionar "deck",
"slides", "apresentação" ou citar um arquivo `.pptx`.

## Referência rápida

| Tarefa | Guia |
|---|---|
| Ler/analisar conteúdo | `python -m markitdown apresentacao.pptx` |
| Editar ou criar a partir de template | leia `${OKAMI_SKILL_DIR}/editing.md` |
| Criar do zero | leia `${OKAMI_SKILL_DIR}/pptxgenjs.md` |

## Ler conteúdo

```bash
# Extração de texto
python -m markitdown apresentacao.pptx
```

Para inspecionar o XML bruto de um `.pptx` sem um script de unpack dedicado, trate o arquivo como
um zip: `python -m zipfile -e apresentacao.pptx unpacked/`.

## Fluxo de edição (template existente)

**Leia `${OKAMI_SKILL_DIR}/editing.md` para os detalhes completos.**

1. Analise o template — abra em algum visualizador ou extraia texto com `markitdown` para ver
   placeholders.
2. Descompacte → manipule slides → edite conteúdo → limpe → recompacte.

Scripts embutidos nesta skill:

| Script | Propósito |
|---|---|
| `${OKAMI_SKILL_DIR}/scripts/add_slide.py` | duplica um slide existente ou cria a partir de um layout |
| `${OKAMI_SKILL_DIR}/scripts/clean.py` | remove arquivos órfãos (slide/mídia/rels não referenciados) após editar `<p:sldIdLst>` |

```bash
python3 ${OKAMI_SKILL_DIR}/scripts/add_slide.py unpacked/ slide2.xml       # duplica slide
python3 ${OKAMI_SKILL_DIR}/scripts/add_slide.py unpacked/ slideLayout2.xml # cria a partir de layout
python3 ${OKAMI_SKILL_DIR}/scripts/clean.py unpacked/                     # limpa órfãos
```

Ordem dos slides está em `ppt/presentation.xml` → `<p:sldIdLst>`. Reordenar = rearranjar
`<p:sldId>`. Deletar = remover `<p:sldId>` e rodar `clean.py`. Adicionar = usar `add_slide.py`
(nunca copie arquivo de slide manualmente — o script cuida das referências de notas,
`Content_Types.xml` e IDs de relacionamento que cópia manual não pega).

Para recompactar o diretório editado num `.pptx` válido, use `python -m zipfile -c saida.pptx
unpacked/.` a partir de dentro do diretório descompactado (mantendo a estrutura
`[Content_Types].xml`, `_rels/`, `ppt/` etc. intacta).

## Criar do zero

**Leia `${OKAMI_SKILL_DIR}/pptxgenjs.md` para os detalhes completos.**

Use quando não há template ou apresentação de referência. Requer `npm install -g pptxgenjs`.

## Ideias de design

**Não crie slides genéricos.** Bullet simples em fundo branco não impressiona ninguém.

### Antes de começar

- **Escolha uma paleta ousada e ligada ao conteúdo**: a paleta deve parecer desenhada PRA esse
  tópico. Se trocar suas cores por outra apresentação qualquer e "ainda funcionar", as escolhas não
  foram específicas o bastante.
- **Dominância, não igualdade**: uma cor domina (60-70% do peso visual), com 1-2 tons de apoio e um
  acento nítido. Nunca dê peso igual a todas as cores.
- **Contraste claro/escuro**: fundo escuro pra título + conclusão, claro pro conteúdo (estrutura
  "sanduíche"). Ou compromisso total com escuro pra sensação premium.
- **Um motivo visual só**: escolha UM elemento distinto e repita — molduras de imagem arredondadas,
  ícones em círculos coloridos, borda grossa de um lado só. Carregue isso por todos os slides.

### Paletas de cor

Escolha cores que combinem com o tópico — não use azul genérico por padrão.

| Tema | Primária | Secundária | Acento |
|---|---|---|---|
| **Executivo meia-noite** | `1E2761` (navy) | `CADCFC` (azul gelo) | `FFFFFF` (branco) |
| **Floresta & musgo** | `2C5F2D` (floresta) | `97BC62` (musgo) | `F5F5F5` (creme) |
| **Energia coral** | `F96167` (coral) | `F9E795` (dourado) | `2F3C7E` (navy) |
| **Terracota quente** | `B85042` (terracota) | `E7E8D1` (areia) | `A7BEAE` (sage) |
| **Gradiente oceano** | `065A82` (azul profundo) | `1C7293` (teal) | `21295C` (meia-noite) |
| **Carvão minimal** | `36454F` (carvão) | `F2F2F2` (quase-branco) | `212121` (preto) |
| **Confiança teal** | `028090` (teal) | `00A896` (verde-mar) | `02C39A` (menta) |
| **Berry & creme** | `6D2E46` (berry) | `A26769` (rosa empoeirado) | `ECE2D0` (creme) |
| **Calma sage** | `84B59F` (sage) | `69A297` (eucalipto) | `50808E` (ardósia) |
| **Cereja ousada** | `990011` (cereja) | `FCF6F5` (quase-branco) | `2F3C7E` (navy) |

### Para cada slide

**Todo slide precisa de um elemento visual** — imagem, gráfico, ícone ou forma. Slide só-texto é
esquecível.

**Opções de layout**: duas colunas (texto esq., ilustração dir.); ícone + texto em linhas; grid
2x2/2x3; imagem full-bleed com conteúdo sobreposto.

**Exibição de dado**: números grandes em destaque (60-72pt) com legenda pequena embaixo; colunas
de comparação (antes/depois, prós/contras); linha do tempo/fluxo de processo (passos numerados,
setas).

### Tipografia

Escolha um par de fontes com personalidade — não use Arial por padrão. Fonte de título com caráter
+ fonte de corpo limpa.

| Fonte de título | Fonte de corpo |
|---|---|
| Georgia | Calibri |
| Arial Black | Arial |
| Calibri | Calibri Light |
| Cambria | Calibri |
| Trebuchet MS | Calibri |
| Impact | Arial |
| Palatino | Garamond |
| Consolas | Calibri |

| Elemento | Tamanho |
|---|---|
| Título do slide | 36-44pt negrito |
| Cabeçalho de seção | 20-24pt negrito |
| Texto de corpo | 14-16pt |
| Legendas | 10-12pt tom apagado |

### Espaçamento

- Margem mínima de 0.5"
- 0.3-0.5" entre blocos de conteúdo
- Deixe respiro — não preencha cada polegada

### Evite (erros comuns)

- Não repita o mesmo layout em todo slide — varie colunas, cards, callouts
- Não centralize texto de corpo — alinhe parágrafos/listas à esquerda; centralize só títulos
- Não economize no contraste de tamanho — título precisa de 36pt+ pra se destacar do corpo de 14-16pt
- Não use azul genérico por padrão — escolha cores específicas do tópico
- Não misture espaçamento aleatoriamente — escolha 0.3" ou 0.5" e use consistente
- Não estilize um slide e deixe o resto plano — comprometa-se ou mantenha simples em tudo
- Não crie slide só-texto — adicione imagem/ícone/gráfico
- Não esqueça o padding do textbox — ao alinhar linha/forma com borda de texto, zere a margem do
  textbox ou compense na forma
- Não use baixo contraste — ícone e texto precisam de contraste forte contra o fundo
- **NUNCA use linha de acento sob o título** — é marca registrada de slide gerado por IA; use
  espaço em branco ou cor de fundo em vez disso

## QA (obrigatório)

**Assuma que tem problema.** Sua primeira renderização quase nunca está certa. Trate QA como caça
a bug, não confirmação. Se não achou nada na primeira olhada, você não olhou direito.

### QA de conteúdo

```bash
python -m markitdown saida.pptx
```

Confira conteúdo faltando, erro de digitação, ordem errada. Ao usar template, procure texto de
placeholder esquecido:

```bash
python -m markitdown saida.pptx | grep -iE "xxxx|lorem|ipsum|este.*(slide|página).*layout"
```

Se o grep achar algo, conserte antes de dar por concluído.

### QA visual

**Use subagentes** mesmo pra 2-3 slides — você já olhou o código e vai enxergar o que espera, não
o que está lá. Subagente tem olho fresco.

Converta os slides pra imagem (ver seção abaixo) e peça inspeção visual explícita: sobreposição de
elementos, texto cortado nas bordas, linha decorativa mal posicionada quando o título quebrou em
duas linhas, rodapé colidindo com conteúdo, elementos muito próximos (< 0.3"), espaçamento desigual,
margem insuficiente (< 0.5"), colunas desalinhadas, texto de baixo contraste, ícone de baixo
contraste, textbox estreito demais causando quebra excessiva, conteúdo de placeholder esquecido.

### Loop de verificação

1. Gera slides → converte pra imagem → inspeciona
2. Lista os problemas achados (se não achou nada, olhe de novo mais crítico)
3. Conserta
4. Reverifica os slides afetados — um fix costuma criar outro problema
5. Repete até uma passada completa não achar nada novo

**Não declare sucesso sem completar pelo menos um ciclo de fix-e-reverificação.**

## Convertendo pra imagem

```bash
soffice --headless --convert-to pdf saida.pptx
pdftoppm -jpeg -r 150 saida.pdf slide
```

Gera `slide-01.jpg`, `slide-02.jpg` etc. Pra re-renderizar um slide específico após fix:

```bash
pdftoppm -jpeg -r 150 -f N -l N saida.pdf slide-fixed
```

## Dependências

- `pip install "markitdown[pptx]"` — extração de texto
- `npm install -g pptxgenjs` — criar do zero
- LibreOffice (`soffice`) — conversão pra PDF
- Poppler (`pdftoppm`) — PDF pra imagens

Nenhuma dessas dependências é instalada automaticamente pelo Okami — se faltar alguma, avise o dono
em vez de tentar contornar.
