# Estilo 04 — FORJA Compute (GPU cloud, cockpit industrial)

GPU cloud brasileira como cockpit industrial de telemetria tática — densidade altíssima, tom de
engenheiro, zero adjetivo de marketing. Fonte: leitura linha a linha de `index.html` + todo `.css`
+ todo `.js`.

## Token block (`:root`)

```css
:root{
  --bg:        #141210;   /* carvão — fundo base */
  --bg-1:      #191613;   /* status bar, painéis */
  --bg-2:      #1e1a16;   /* reserva, pouco usado */
  --line:      #2c2620;   /* toda borda 1px do site */
  --line-soft: #241f1a;   /* bordas internas mais fracas */
  --fg:        #e6ded2;   /* texto principal, quase-branco quente */
  --fg-dim:    #97897a;   /* texto secundário */
  --fg-faint:  #5e544a;   /* labels, legendas, terciário */
  --accent:    #d97706;   /* âmbar — ÚNICO acento de cor do site inteiro */
  --accent-dim:#8a5410;   /* âmbar escurecido — traços técnicos, SVGs */
  --ok:        #a3b18a;   /* verde oliva apagado — só status "operacional" */
  --mono: "JetBrains Mono", ui-monospace, "SF Mono", monospace;
  --disp: "Archivo", "Archivo Black", sans-serif;
  --pad: clamp(16px, 3.4vw, 48px);
}
```

Regra de ouro: **um único acento** (âmbar). Verde é exclusivo de indicadores "operacional" — não
existe segunda cor de destaque. Reset agressivo: `*{ border-radius:0 !important; }` — zero cantos
arredondados no site inteiro.

## Fontes e uso

`--mono` (JetBrains Mono) é a fonte de **corpo inteiro** (`body{font-family:var(--mono);
font-size:13px}`) — o site inteiro roda em monospace, incluindo parágrafos. `--disp` (Archivo
variável `wdth,wght`) só em títulos grandes, sempre com `font-stretch` reduzido
(62–72%, ex.: `font-stretch:66%` no h1). `.num` força `font-variant-numeric:tabular-nums` em todo
número — nunca "dança" ao trocar dígito.

Textura de tela — scanline CRT fixa e global, sem custo de repaint:
```css
body::after{
  content:""; position:fixed; inset:0; z-index:9; pointer-events:none;
  background:repeating-linear-gradient(0deg, transparent 0 3px, rgba(0,0,0,.14) 3px 4px);
  opacity:.5;
}
```

## Implementação 3D — inspeção do die GH100 (`js/die3d.js`)

Three.js **r128** UMD via CDN, IIFE que testa `if (!window.THREE) { noWebgl(); return; }`.

```js
renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "low-power" });
var DPR = Math.min(window.devicePixelRatio || 1, 2);
renderer.setPixelRatio(DPR);
wrap.appendChild(renderer.domElement);          // canvas criado via appendChild
wrap.classList.add("webgl-on");                 // esconde o fallback SVG via CSS
var scene = new THREE.Scene();
var camera = new THREE.PerspectiveCamera(34, 1, 0.1, 60);  // FOV estreito → lente "macro/tele"
camera.position.set(0, 2.35, 4.6);
camera.lookAt(0, 0.02, 0);
```
Sem `scene.background` — fundo transparente, o CSS por trás (`#0c0a08`) dá o preto.

**Tudo wireframe via `EdgesGeometry`+`LineSegments`, nunca mesh sólido**:
```js
function edgeBox(w, h, d, color, opacity) {
  var geo = new THREE.EdgesGeometry(new THREE.BoxGeometry(w, h, d));
  var mat = new THREE.LineBasicMaterial({ color: color, transparent: true, opacity: opacity });
  return new THREE.LineSegments(geo, mat);
}
function lineSet(arr, color, opacity) {   // linhas soltas a partir de array de pares de pontos
  var geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.Float32BufferAttribute(arr, 3));
  var mat = new THREE.LineBasicMaterial({ color: color, transparent: true, opacity: opacity });
  return new THREE.LineSegments(geo, mat);
}
```
Paleta 3D: `AMBER = 0xd97706`, `AMBER_DIM = 0x8a5410` — mesma do CSS.

Peças (todas filhas de um único `THREE.Group`, permite orbitar tudo junto): substrato (`edgeBox
3.4×0.1×2.9`), interposer (`2.5×0.08×2.1`), die (`1.35×0.12×1.15`, accent), grade de 48 SMs (8×6,
6 materiais cíclicos que pulsam), 6 stacks HBM3 flanqueando o die, traces do interposer + 18 lanes
NVLink (array bruto de pontos via `lineSet()`), matriz BGA (17×14 = 238 pares de pontos, opacity
.22), e um `PolarGridHelper(2.9,12,5,64,...)` como "prato de holograma" sob o pacote. Sem
`AdditiveBlending` aqui — tudo `transparent:true` com opacidade fixa por peça.

### Loop de animação

- Rotação automática: `AUTO=0.0032` somado a `rotY`, com inércia: `vel += (AUTO-vel)*0.03; rotY += vel`.
- Drag do mouse: `pointerdown/move/up`, `rotY += dx*0.0055`, `vel = clamp(dx*0.0055,-0.09,0.09)`.
- Hover sem clique: X do mouse produz `hoverYT` (parallax), Y produz `tiltT` (inclinação de
  câmera), lerp 0.06/frame.
- **Pulsação dos SMs** (senoides defasadas): `smMats[i].opacity = 0.28 + 0.44 * (0.5 +
  0.5*Math.sin(tm*(1.1+i*0.23) + i*1.7))`.
- **Temperatura simulada**: a cada ~1700ms, passeio aleatório clampado 89.8–92.4°C.
- **HUD ancorado a pontos 3D**: 5 âncoras `Vector3` projetadas via `v.project(camera)`
  (`placeHUD()`), gerando `<div class="hud-tag">` com `translate3d`, de-overlap manual, estado
  `.far` quando a âncora está longe.

**Pausa**: `IntersectionObserver(0.08)` + `visibilitychange`; `prefers-reduced-motion` renderiza um
frame estático (`renderStatic()`), sem loop. **Fallback sem WebGL**: `<svg class="die3d-fallback">`
já embutido no HTML, escondido via `.die3d-wrap.webgl-on .die3d-fallback{display:none}` quando o
WebGL sobe.

**Posicionamento**: `#die3d` usa grid `1.55fr / 1fr` — canvas na coluna maior, texto explicativo na
menor, moldura com `.corner` decorativos, cabeçalho estilo instrumento ("WGL_01 // INSPEÇÃO 3D",
"ARRASTE PARA ORBITAR"). `min-height:clamp(360px,34vw,520px)`.

## Postura do herói — sem 3D, vídeo em "câmera de vigilância"

```css
.hero{ grid-template-columns: minmax(0,7fr) minmax(0,5fr); }
.cam-frame video{ width:100%; aspect-ratio:16/9; object-fit:cover; }
```
Overlay de scanlines + vinheta via `::after`:
```css
background:
  radial-gradient(115% 90% at 50% 48%, transparent 58%, rgba(6,4,2,.5)),
  repeating-linear-gradient(0deg, rgba(0,0,0,.13) 0 1px, transparent 1px 3px);
```
Cantos `.corner` (4 spans, borda L 14×14px âmbar, reaproveitados no `die3d`), cruz central
`.cam-cross{content:"+"}` simulando mira. Headline: `font-stretch:66%`,
`clamp(3rem,7.4vw,7.2rem)`, `line-height:.88`, uppercase, trecho final `.h1-accent{color:var(--accent)}`.
4 specs numéricos em grid com separadores `gap:1px; background:var(--line)`.

## Motion (vanilla JS, sem GSAP)

**Reveal**: `.rv{opacity:0; translateY(14px)}`, delay via `transition-delay:calc(var(--i,0)*90ms)`
setado inline (`style="--i:1"`), sem JS calculando delays.
```js
var io = new IntersectionObserver(function(entries){
  entries.forEach(function(entry){
    if (!entry.isIntersecting) return;
    entry.target.classList.add("in");
    drawInside(entry.target);
    io.unobserve(entry.target);
  });
}, { threshold: 0.1, rootMargin: "0px 0px 12% 0px" });
```
Fallback: após 3s tudo é forçado visível. **Linhas SVG desenhando-se**: `.draw` recebe
`stroke-dasharray=getTotalLength()`, anima `stroke-dashoffset→0`, delay incremental 90ms/segmento.
**Telemetria viva**: `drift=(Math.random()-0.5)*2*step` a cada 1200ms atualiza números e
sparklines de bloco (`▁▂▃▄▅▆▇`), histórico de 12 amostras. **Ticker infinito**: duplica via
`cloneNode`, `@keyframes ticker{to{transform:translateX(-50%)}}` 36s. **Relógio real**:
`setInterval` 1s.

Tudo respeita `prefers-reduced-motion:reduce`.

## Layout

Toda seção delimitada por `border-bottom:1px solid var(--line)` — nunca sombra. Cabeçalho de
seção: número âmbar + título mono uppercase + metadado à direita. Densidade: grid de telemetria
4-col (`gap:1px; background:var(--line)`), tabela de preços 9-col, SVG técnico de elevação de
rack, SVG de topologia de rede. Grid de fundo repetido: `repeating-linear-gradient(90deg,
transparent 0 119px, var(--line-soft) 119px 120px)`. `.foot-giant{font-size:clamp(8rem,24vw,24rem);
-webkit-text-stroke:1px var(--line); color:transparent}` — wordmark gigante só contornada.

## Assets

Todo SVG autoral/inline (elevação de rack, topologia, fallback do die). Vídeo real +
3 fotos únicos assets bitmap. 3D 100% procedural (nenhum `.glb`/`.obj`).

## O movimento distintivo

Cockpit de telemetria industrial real-time com um único acento de cor. O site nunca finge ser
"produto SaaS bonito" — relógio real, câmera com scanline, métricas oscilando a cada 1.2s, ticker
de status infinito, SVGs técnicos com escala/legenda, e o clímax: inspeção 3D wireframe arrastável
do die de GPU com HUD ancorado a pontos 3D e "temperatura" simulada. A disciplina de paleta (1
acento âmbar, zero border-radius, mono-font em tudo) é o que faz a peça 3D parecer parte do mesmo
instrumento, não um enfeite hero separado.
