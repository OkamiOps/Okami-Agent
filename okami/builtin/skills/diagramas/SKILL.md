---
name: diagramas
description: Diagramas técnicos em dois formatos — Excalidraw JSON (estilo "desenhado à mão", editável em excalidraw.com) e SVG dark-theme em HTML autocontido (arquitetura/fluxo/sequência). Sem serviço externo, sem API key.
triggers: [diagrama, fluxograma, diagrama de arquitetura, diagrama de sequência, mapa mental, excalidraw, desenho técnico, diagrama de infra, arquitetura do sistema, mapa de componentes]
intent_examples:
  - "desenha um diagrama de arquitetura desse sistema"
  - "faz um fluxograma desse processo"
  - "quero um diagrama estilo excalidraw pra explicar isso no board"
  - "mapeia os componentes da infra em um diagrama"
  - "cria um diagrama de sequência dessa chamada de API"
metadata:
  hermes:
    tags: [diagrams, excalidraw, architecture, SVG, HTML, visualization]
    category: creative
    ported_from: hermes-agent/skills/creative/{excalidraw,architecture-diagram}
---

# Diagramas (Excalidraw + Arquitetura SVG)

Duas formas de gerar diagrama, sem serviço externo, sem API key, sem biblioteca de renderização —
só JSON e HTML/SVG escritos direto por você e salvos com a tool de arquivo.

| Formato | Quando usar | Saída |
|---|---|---|
| **Excalidraw JSON** | Estilo "desenhado à mão" (whiteboard), pra editar depois em excalidraw.com | arquivo `.excalidraw` |
| **SVG dark-theme (HTML)** | Arquitetura de sistema, infra cloud, topologia de microserviço — estética técnica escura | arquivo `.html` autocontido |

Se a tarefa não é claramente sobre infra/arquitetura de software, prefira o formato Excalidraw
(mais genérico: fluxograma, mapa conceitual, diagrama de sequência, anotação de reunião).

## Formato 1 — Excalidraw JSON

Escreva um array de elementos Excalidraw e salve como `.excalidraw` (JSON puro). O arquivo pode
ser arrastado direto em [excalidraw.com](https://excalidraw.com) para visualizar/editar — sem
conta, sem chave de API.

### Envelope do arquivo

```json
{
  "type": "excalidraw",
  "version": 2,
  "source": "okami-agent",
  "elements": [ ...array de elementos... ],
  "appState": { "viewBackgroundColor": "#ffffff" }
}
```

Salve em qualquer caminho, ex.: `~/diagramas/meu_diagrama.excalidraw`.

### Campos obrigatórios (todo elemento)

`type`, `id` (string única), `x`, `y`, `width`, `height`.

### Defaults (não precisa repetir)

- `strokeColor`: `"#1e1e1e"`
- `backgroundColor`: `"transparent"`
- `fillStyle`: `"solid"`
- `strokeWidth`: `2`
- `roughness`: `1` (o efeito "à mão")
- `opacity`: `100`

Fundo do canvas é branco por padrão.

### Tipos de elemento

**Retângulo**:
```json
{ "type": "rectangle", "id": "r1", "x": 100, "y": 100, "width": 200, "height": 100 }
```
- `roundness: { "type": 3 }` para cantos arredondados
- `backgroundColor: "#a5d8ff"`, `fillStyle: "solid"` para preenchido

**Elipse**:
```json
{ "type": "ellipse", "id": "e1", "x": 100, "y": 100, "width": 150, "height": 150 }
```

**Losango**:
```json
{ "type": "diamond", "id": "d1", "x": 100, "y": 100, "width": 150, "height": 150 }
```

**Forma com texto (container binding)** — cria um elemento de texto vinculado à forma.

> **ATENÇÃO:** NÃO use `"label": { "text": "..." }` na forma — essa propriedade NÃO existe no
> Excalidraw e é silenciosamente ignorada, gerando forma vazia. Use SEMPRE o binding abaixo.

A forma precisa de `boundElements` listando o texto, e o texto precisa de `containerId` apontando
de volta pra forma:
```json
{ "type": "rectangle", "id": "r1", "x": 100, "y": 100, "width": 200, "height": 80,
  "roundness": { "type": 3 }, "backgroundColor": "#a5d8ff", "fillStyle": "solid",
  "boundElements": [{ "id": "t_r1", "type": "text" }] },
{ "type": "text", "id": "t_r1", "x": 105, "y": 110, "width": 190, "height": 25,
  "text": "Olá", "fontSize": 20, "fontFamily": 1, "strokeColor": "#1e1e1e",
  "textAlign": "center", "verticalAlign": "middle",
  "containerId": "r1", "originalText": "Olá", "autoResize": true }
```
- Funciona em retângulo, elipse, losango
- Excalidraw centraliza o texto automaticamente quando `containerId` está definido
- `x`/`y`/`width`/`height` do texto são aproximados — o Excalidraw recalcula ao abrir
- `originalText` deve ser igual a `text`
- Sempre inclua `fontFamily: 1` (fonte Virgil, estilo à mão)

**Seta com texto** — mesmo esquema de binding:
```json
{ "type": "arrow", "id": "a1", "x": 300, "y": 150, "width": 200, "height": 0,
  "points": [[0,0],[200,0]], "endArrowhead": "arrow",
  "boundElements": [{ "id": "t_a1", "type": "text" }] },
{ "type": "text", "id": "t_a1", "x": 370, "y": 130, "width": 60, "height": 20,
  "text": "conecta", "fontSize": 16, "fontFamily": 1, "strokeColor": "#1e1e1e",
  "textAlign": "center", "verticalAlign": "middle",
  "containerId": "a1", "originalText": "conecta", "autoResize": true }
```

**Texto solto** (só títulos e anotações — sem container):
```json
{ "type": "text", "id": "t1", "x": 150, "y": 138, "text": "Olá", "fontSize": 20,
  "fontFamily": 1, "strokeColor": "#1e1e1e", "originalText": "Olá", "autoResize": true }
```
- `x` é a borda ESQUERDA. Para centralizar em `cx`: `x = cx - (tamanho_texto * fontSize * 0.5) / 2`
- Não confie em `textAlign`/`width` para posicionamento de texto solto

**Seta**:
```json
{ "type": "arrow", "id": "a1", "x": 300, "y": 150, "width": 200, "height": 0,
  "points": [[0,0],[200,0]], "endArrowhead": "arrow" }
```
- `points`: offsets `[dx, dy]` a partir de `x`, `y` do elemento
- `endArrowhead`: `null` | `"arrow"` | `"bar"` | `"dot"` | `"triangle"`
- `strokeStyle`: `"solid"` (padrão) | `"dashed"` | `"dotted"`

### Bindings de seta (conectar seta a formas)

```json
{
  "type": "arrow", "id": "a1", "x": 300, "y": 150, "width": 150, "height": 0,
  "points": [[0,0],[150,0]], "endArrowhead": "arrow",
  "startBinding": { "elementId": "r1", "fixedPoint": [1, 0.5] },
  "endBinding": { "elementId": "r2", "fixedPoint": [0, 0.5] }
}
```
Coordenadas de `fixedPoint`: `topo=[0.5,0]`, `base=[0.5,1]`, `esquerda=[0,0.5]`, `direita=[1,0.5]`

### Ordem de desenho (z-order)

- Ordem do array = ordem de empilhamento (primeiro = fundo, último = frente)
- Emita progressivamente: zona de fundo → forma → texto da forma → setas → próxima forma
- RUIM: todos os retângulos, depois todos os textos, depois todas as setas
- BOM: zona_fundo → forma1 → texto_forma1 → seta1 → texto_da_seta → forma2 → texto_forma2 → ...
- Sempre coloque o texto vinculado logo depois da forma que o contém

### Tamanhos

**Fonte:**
- Mínimo `fontSize` **16** para corpo de texto, rótulos, descrições
- Mínimo `fontSize` **20** para títulos
- Mínimo `fontSize` **14** só para anotações secundárias (com moderação)
- NUNCA use `fontSize` abaixo de 14

**Formas:**
- Tamanho mínimo 120x60 para retângulos/elipses com texto
- Deixe 20-30px de espaço mínimo entre elementos
- Prefira poucos elementos grandes a muitos elementos minúsculos

### Paleta de cores

Ver `references/excalidraw-colors.md` para tabelas completas. Referência rápida:

| Uso | Cor de preenchimento | Hex |
|-----|-----------|-----|
| Primário / Entrada | Azul claro | `#a5d8ff` |
| Sucesso / Saída | Verde claro | `#b2f2bb` |
| Aviso / Externo | Laranja claro | `#ffd8a8` |
| Processamento / Especial | Roxo claro | `#d0bfff` |
| Erro / Crítico | Vermelho claro | `#ffc9c9` |
| Notas / Decisões | Amarelo claro | `#fff3bf` |
| Armazenamento / Dados | Teal claro | `#c3fae8` |

### Dicas

- Use a paleta de cores de forma consistente no diagrama inteiro
- **Contraste de texto é CRÍTICO** — nunca cinza claro em fundo branco. Mínimo: `#757575`
- NÃO use emoji no texto — não renderizam na fonte do Excalidraw
- Para diagrama em modo escuro, ver `references/excalidraw-dark-mode.md`
- Para exemplos maiores prontos, ver `references/excalidraw-examples.md`

### Compartilhar (opcional, manual)

Não há script de upload nesta skill (o script original do Hermes dependia do pacote pip
`cryptography`, uma dependência pesada só para gerar um link compartilhável — fora do escopo
"stdlib puro" desta skill). Para compartilhar, o dono pode simplesmente arrastar o arquivo
`.excalidraw` para [excalidraw.com](https://excalidraw.com) e usar o botão nativo "Share" do
próprio site — não precisa de script nenhum.

---

## Formato 2 — Diagrama de arquitetura SVG (dark theme, HTML)

Gera diagramas técnicos de arquitetura de sistema, infra cloud, topologia de microserviço, como um
arquivo HTML autocontido com SVG inline. Sem ferramenta externa, sem chave de API — só escrever o
HTML e abrir no navegador.

Baseado no [architecture-diagram-generator da Cocoon AI](https://github.com/Cocoon-AI/architecture-diagram-generator) (MIT), portado do Hermes Agent.

### Quando usar

**Bom encaixe:**
- Arquitetura de sistema de software (camadas frontend / backend / banco de dados)
- Infra cloud (VPC, regiões, subnets, serviços gerenciados)
- Topologia de microserviço / service mesh
- Mapa de API + banco de dados, diagrama de deploy
- Qualquer assunto de infra técnica que combine com estética dark + grid

**Prefira outra abordagem para:**
- Física, química, matemática, biologia — assuntos científicos genéricos
- Objetos físicos (veículos, hardware, anatomia)
- Plantas baixas, jornadas narrativas, visual didático/livro-texto
- Rascunho estilo quadro branco à mão (use o formato Excalidraw acima)

Se nenhum se encaixa, este formato ainda serve como fallback genérico de diagrama SVG — só que
com a estética dark-tech abaixo.

### Fluxo

1. O dono descreve o sistema (componentes, conexões, tecnologias)
2. Gere o HTML seguindo o design system abaixo
3. Salve com a tool de arquivo em um `.html` (ex.: `~/arquitetura-projeto.html`)
4. O dono abre no navegador — funciona offline, sem dependências

Salve em um caminho indicado pelo dono, ou no diretório atual como `./[nome-projeto]-arquitetura.html`.

### Paleta de cores (mapeamento semântico)

Use `rgba` no preenchimento e hex na borda pra categorizar cada componente:

| Tipo de componente | Preenchimento (rgba) | Borda (hex) |
| :--- | :--- | :--- |
| **Frontend** | `rgba(8, 51, 68, 0.4)` | `#22d3ee` (cyan-400) |
| **Backend** | `rgba(6, 78, 59, 0.4)` | `#34d399` (emerald-400) |
| **Banco de dados** | `rgba(76, 29, 149, 0.4)` | `#a78bfa` (violet-400) |
| **AWS/Cloud** | `rgba(120, 53, 15, 0.3)` | `#fbbf24` (amber-400) |
| **Segurança** | `rgba(136, 19, 55, 0.4)` | `#fb7185` (rose-400) |
| **Message bus** | `rgba(251, 146, 60, 0.3)` | `#fb923c` (orange-400) |
| **Externo** | `rgba(30, 41, 59, 0.5)` | `#94a3b8` (slate-400) |

### Tipografia e fundo

- **Fonte:** JetBrains Mono (monospace), via Google Fonts
- **Tamanhos:** 12px (nomes), 9px (sublabels), 8px (anotações), 7px (labels minúsculos)
- **Fundo:** Slate-950 (`#020617`) com grid sutil de 40px

```svg
<pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
  <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#1e293b" stroke-width="0.5"/>
</pattern>
```

### Detalhes técnicos

**Componentes:** retângulos arredondados (`rx="6"`), borda de 1.5px. Pra setas não aparecerem
através do preenchimento semi-transparente, use a técnica de **duplo retângulo**: primeiro um
retângulo opaco de fundo (`#0f172a`), depois o retângulo estilizado semi-transparente por cima.

**Conexões:**
- Desenhe as setas CEDO no SVG (logo após o grid), pra ficarem atrás das caixas de componente
- Setas de segurança: linha tracejada em rose (`#fb7185`)
- Boundaries: security group tracejado fino (`4,4`, rose); região tracejado grosso (`8,4`, amber, `rx="12"`)

**Espaçamento:**
- Altura padrão: 60px (serviços), 80-120px (componentes grandes)
- Gap vertical mínimo: 40px entre componentes
- Message bus: deve ficar NO GAP entre serviços, sem sobrepor
- Legenda: **CRÍTICO** — sempre fora de qualquer boundary box, pelo menos 20px abaixo do Y mais baixo de todas as boundaries

### Estrutura do documento

O HTML segue quatro partes:
1. **Header:** título com indicador pulsante + subtítulo
2. **SVG principal:** o diagrama dentro de um card com borda arredondada
3. **Cards de resumo:** grade de três cards abaixo do diagrama com detalhes
4. **Footer:** metadata mínima

### Requisitos de saída

- Um único arquivo `.html` autocontido
- Sem dependência externa (exceto Google Fonts) — CSS e SVG tudo inline
- Sem JavaScript — animações (como o dot pulsante) só com CSS puro
- Deve renderizar em qualquer navegador moderno

### Template de referência

Carregue `templates/architecture.html` para a estrutura completa (CSS, exemplos de todo tipo de
componente, estilos de seta, security groups, boundaries de região, legenda) — use como base
estrutural ao gerar diagramas novos.
