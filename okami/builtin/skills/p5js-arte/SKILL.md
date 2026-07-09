---
name: p5js-arte
description: Arte generativa/interativa com p5.js — sketch HTML autocontido (partículas, ruído, 3D/WebGL, tipografia cinética), sem build step, sem servidor, sem dependência além do CDN.
triggers: [arte generativa, p5.js, sketch interativo, arte procedural, flow field, partículas, shader, webgl, arte com código, visual generativo]
intent_examples:
  - "cria uma arte generativa com partículas"
  - "faz um sketch interativo com p5.js"
  - "quero um flow field animado"
  - "gera uma cena 3D com webgl no navegador"
  - "faz um efeito visual reagindo ao mouse"
metadata:
  hermes:
    tags: [p5js, generative-art, creative-coding, canvas, webgl, animation]
    category: creative
    ported_from: hermes-agent/skills/creative/p5js
---

# p5.js — arte generativa e interativa

Arte visual no navegador com [p5.js](https://p5js.org/). Saída é UM arquivo `.html` autocontido —
`<script>` de CDN, sem build, sem servidor, sem instalar nada. Abre em qualquer navegador moderno.

Não é exercício de tutorial — o objetivo é arte de verdade: sistemas generativos, física de
partículas, campos de ruído, efeitos de shader, tipografia cinética, com paleta de cor intencional
e composição em camadas.

## Modos

| Modo | Entrada | Saída |
|------|-------|--------|
| **Arte generativa** | seed / parâmetros | composição visual procedural |
| **Visualização de dados** | dataset / API | gráficos interativos, displays customizados |
| **Experiência interativa** | nenhuma (usuário controla) | sketch guiado por mouse/teclado/toque |
| **Animação / motion graphics** | timeline / storyboard | sequências cronometradas, tipografia cinética |
| **Cena 3D** | descrição do conceito | geometria WebGL, iluminação, shaders |
| **Processamento de imagem** | arquivo(s) de imagem | manipulação de pixel, filtros, pontilhismo |

## Pré-requisitos

Só um navegador moderno. Nada mais é necessário.

Esta skill **não inclui** o pipeline de export headless do Hermes original (`export-frames.js`
via Puppeteer + `ffmpeg` pra MP4) — depende de Node.js/npm/Puppeteer/ffmpeg, dependências pesadas
fora do escopo desta skill (stdlib/CDN puro). Para PNG/GIF, use os atalhos de teclado do próprio
sketch (seção abaixo) — cobre a maioria dos pedidos sem precisar de pipeline externo. Se o dono
pedir MP4/vídeo automatizado especificamente, avise que precisa instalar Node+Puppeteer+ffmpeg à
parte (fora desta skill) antes de seguir.

## Fluxo

1. **Escreva o arquivo HTML** — single file autocontido, todo o código inline
2. **Abra no navegador** — `open sketch.html` (macOS) ou `xdg-open sketch.html` (Linux)
3. **Assets locais** (fontes, imagens) precisam de servidor: `python3 -m http.server 8080` no
   diretório do projeto, depois abra `http://localhost:8080/sketch.html`
4. **Export PNG/GIF** — adicione os atalhos de teclado (seção abaixo) e diga ao dono qual tecla
   apertar
5. **Refinamento iterativo** — edite o HTML, o dono dá refresh no navegador pra ver a mudança

## Template de partida

Carregue `templates/viewer.html` como ponto de partida para sketches interativos com parâmetros
ajustáveis (sidebar com sliders, navegação de seed, botão de download PNG já prontos). Troque
apenas: o algoritmo p5.js (`setup`/`draw`/classes), o objeto `PARAMS`, os controles da sidebar e a
paleta de cor — mantenha a estrutura de layout, navegação de seed e wiring de parâmetros como está.

## Notas críticas de implementação

### Performance — desative o FES primeiro

O Friendly Error System (FES) do p5 adiciona até 10x de overhead. Desative em todo sketch de
produção:

```javascript
p5.disableFriendlyErrors = true;  // ANTES do setup()

function setup() {
  pixelDensity(1);  // evita overdraw 2x-4x em telas retina
  createCanvas(1920, 1080);
}
```

Em hot loops (partículas, operação de pixel), use `Math.*` em vez dos wrappers do p5 — mais
rápido: `Math.sin(t)` em vez de `sin(t)`, `Math.random()` em vez de `random()` quando seed não é
necessária. Nunca `console.log()` dentro de `draw()`.

### Randomness com seed — sempre

Todo sketch generativo precisa ser reproduzível. Mesma seed, mesma saída.

```javascript
function setup() {
  randomSeed(CONFIG.seed);
  noiseSeed(CONFIG.seed);
  // random() e noise() agora são determinísticos
}
```

Nunca use `Math.random()` para conteúdo visual — só para código não-visual sensível a
performance. Para elementos visuais, sempre `random()`.

### Modo de cor — use HSB

HSB (Hue, Saturation, Brightness) é muito mais fácil de manipular que RGB para arte generativa:

```javascript
colorMode(HSB, 360, 100, 100, 100);
// fill(hue, sat, bri, alpha)
// Rotacionar matiz: fill((baseHue + offset) % 360, 80, 90)
```

Nunca hardcode valores RGB crus — defina uma paleta e derive variações proceduralmente.

### Ruído — multi-oitava, não cru

`noise(x, y)` cru parece manchas suaves demais. Empilhe oitavas pra textura mais orgânica:

```javascript
function fbm(x, y, octaves = 4) {
  let val = 0, amp = 1, freq = 1, sum = 0;
  for (let i = 0; i < octaves; i++) {
    val += noise(x * freq, y * freq) * amp;
    sum += amp;
    amp *= 0.5;
    freq *= 2;
  }
  return val / sum;
}
```

### createGraphics() para camadas — não é opcional

Renderização flat em passo único fica achatada. Use buffers offscreen pra composição em camadas:

```javascript
let bgLayer, fgLayer, trailLayer;
function setup() {
  createCanvas(1920, 1080);
  bgLayer = createGraphics(width, height);
  fgLayer = createGraphics(width, height);
  trailLayer = createGraphics(width, height);
}
function draw() {
  renderBackground(bgLayer);
  renderTrails(trailLayer);   // persistente, com fade
  renderForeground(fgLayer);  // limpo a cada frame
  image(bgLayer, 0, 0);
  image(trailLayer, 0, 0);
  image(fgLayer, 0, 0);
}
```

### Vetorização — para milhares de partículas

```javascript
// LENTO: forma individual por partícula
for (let p of particles) { ellipse(p.x, p.y, p.size); }

// RÁPIDO: forma única com beginShape()
beginShape(POINTS);
for (let p of particles) { vertex(p.x, p.y); }
endShape();
```

### Modo WEBGL — pegadinhas

- `createCanvas(w, h, WEBGL)` — origem é o centro, não o canto superior esquerdo
- Eixo Y invertido (Y positivo vai pra cima no WEBGL, pra baixo no P2D)
- `translate(-width/2, -height/2)` pra ter coordenadas parecidas com P2D
- `push()`/`pop()` em volta de toda transformação — a pilha de matriz estoura silenciosamente
- `texture()` antes de `rect()`/`plane()` — nunca depois

### Export — convenção de atalhos de teclado

Todo sketch deve incluir isso em `keyPressed()`:

```javascript
function keyPressed() {
  if (key === 's' || key === 'S') saveCanvas('output', 'png');
  if (key === 'g' || key === 'G') saveGif('output', 5);
  if (key === 'r' || key === 'R') { randomSeed(millis()); noiseSeed(millis()); }
  if (key === ' ') CONFIG.paused = !CONFIG.paused;
}
```

Diga ao dono explicitamente: "aperte **s** pra salvar PNG, **g** pra salvar GIF" — sem isso ele
não sabe que o atalho existe.

## Formatos de export (sem pipeline externo)

| Formato | Método |
|--------|--------|
| **HTML** | o próprio arquivo autocontido, abre em qualquer navegador |
| **PNG** | `saveCanvas()` — tecla **s** |
| **GIF** | `saveGif()` — tecla **g** |
| **MP4/frames automatizados** | fora do escopo desta skill — precisa Node+Puppeteer+ffmpeg à parte |
