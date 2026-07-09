# Estilo 08 — Agent Smith (IA corporativa, produto SaaS premium)

Landing definitiva de um produto de IA corporativo **real** (não redesign especulativo) — navy
profundo, energia elétrica azul, identidade extraída do deploy oficial e elevada a execução
estado-da-arte. Fonte: leitura linha a linha de `index.html` + todo `.css` + todo `.js`.

## Token block (`:root`)

```css
:root{
  --bg: #020817;              /* navy quase-preto */
  --bg-soft: #050d1f;
  --surface: rgba(13, 23, 45, 0.55);
  --border: #263047;
  --border-soft: rgba(38, 48, 71, 0.55);
  --text: #f2f6fc;
  --muted: #94a3b8;
  --muted-2: #64748b;
  --accent: #5286f4;          /* azul — hsl(221 88% 64%), único acento */
  --accent-soft: rgba(82, 134, 244, 0.14);
  --accent-line: rgba(82, 134, 244, 0.4);
  --font-sans: 'Plus Jakarta Sans', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, monospace;
  --radius-lg: 28px;
  --radius-md: 18px;
}
```

Diferente do FORJA: `border-radius` grande e consistente (28px/18px, "pill" em botões/badges) —
estética glass/SaaS moderna, oposto do industrial anguloso.

**Vidro (glassmorphism)** repetido em quase todo componente com fundo: `backdrop-filter:
blur(18px)` na nav, `blur(20px)` no chat, `blur(14px)` no rail — sempre com `border:1px solid
rgba(255,255,255,0.08-0.12)` e `box-shadow: inset 0 1px 0 rgba(255,255,255,.06-.12), 0 Npx Mpx
-Kpx rgba(2,8,23,.9)` (sombra externa escura + brilho interno de 1px no topo — "borda de vidro").

**Grão global**: SVG data-URI `feTurbulence`, fixo sobre tudo, `opacity:0.05, z-index:60`.

## Fontes e uso

Plus Jakarta Sans peso 300 nos títulos (visual "leve/premium"), JetBrains Mono só em labels
técnicos (eyebrow, mono, chat env, specs). H1 em duas linhas com tratamentos opostos:
`.h1-line1` mono uppercase pequeno tracking `0.28em` (kicker), `.h1-line2` grande com **gradiente
de texto**:

```css
.h1-line2{
  font-size: clamp(2.7rem, 6.4vw, 4.9rem);
  background: linear-gradient(100deg, #ffffff 30%, rgba(255,255,255,0.45) 100%);
  -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
}
```

## Implementação 3D — constelação neural (seção Segurança)

Three.js **r128** UMD + **GSAP 3.12.5** + **ScrollTrigger** via CDN. Grafo de ~120 nós com glow
aditivo, arestas translúcidas, drift orgânico, rotação orbital por mouse (lerp+inércia) e pulsos de
sinal viajando pelas arestas. DPR≤2, pausa fora da viewport, frame estático sob
`prefers-reduced-motion`, fallback silencioso sem WebGL.

```js
renderer = new THREE.WebGLRenderer({ canvas: canvas, alpha: true, antialias: true, powerPreference: 'low-power' });
var dpr = Math.min(window.devicePixelRatio || 1, 2);
renderer.setPixelRatio(dpr);
var scene = new THREE.Scene();
var camera = new THREE.PerspectiveCamera(55, 1, 0.1, 200);
camera.position.set(0, 0, 34);
var group = new THREE.Group(); scene.add(group);
```
O `<canvas id="neural-canvas">` já existe no HTML — passado direto ao construtor (`canvas: canvas`),
diferente do FORJA que usa `appendChild`.

**Nós** (120, distribuição elipsoidal orgânica com viés para fora):
```js
var NODES = 120, RX = 21, RY = 11.5, RZ = 8.5;
for (i = 0; i < NODES; i++) {
  var u = Math.random()*2-1, th = Math.random()*Math.PI*2, s = Math.sqrt(1-u*u);
  var r = Math.pow(Math.random(), 0.5);  // viés para fora: nuvem orgânica, não uniforme
  basePos[i*3]   = s*Math.cos(th)*r*RX;
  basePos[i*3+1] = s*Math.sin(th)*r*RY;
  basePos[i*3+2] = u*r*RZ;
}
```
Paleta 3D: `['#5286f4','#82acff','#3b6ce0','#a9c5ff']` — 4 variações do mesmo azul. **Arestas**:
conecta cada nó aos 2 ou 3 vizinhos mais próximos por distância euclidiana.

**Materiais — `ShaderMaterial` custom com `AdditiveBlending`, GLSL escrito à mão**:
```glsl
// vertex (pontos/nós)
float prox = smoothstep(8.5, 0.0, distance(wp.xyz, uMouse));
float tw = 0.72 + 0.28*sin(uTime*1.3 + aPhase);
vGlow = tw*0.68 + prox*1.5;
gl_PointSize = aSize*(1.0+prox*1.3)*tw*uPR*(52.0/-mv.z);
// fragment
float d = length(gl_PointCoord-0.5)*2.0;
float a = smoothstep(1.0,0.0,d); a*=a;
gl_FragColor = vec4(vColor*(0.7+vGlow), a*(0.45+vGlow*0.6));
```
Materiais de linha usam a mesma lógica de proximidade ao mouse. 14 partículas de "pulso" viajam
por arestas aleatórias (cor quase-branca) simulando inferência percorrendo a rede.

**Animação por frame**: drift orgânico por-nó (soma de senos/cossenos com fase/frequência únicas
por nó, gerados no setup — cada ponto "respira" em órbita própria); linhas seguem o drift; pulsos
avançam `t += dt*v`, ao chegar a 1 escolhem nova aresta/velocidade, alpha `Math.sin(t*Math.PI)`.

**Interação — rotação orbital por mouse, sem drag/clique**:
```js
window.addEventListener('mousemove', function(e){
  var nx = ((e.clientX-rect.left)/rect.width)*2-1;
  var ny = -(((e.clientY-rect.top)/rect.height)*2-1);
  ndc.set(clamp(nx,-1.35,1.35), clamp(ny,-1.35,1.35));
  targetRY = ndc.x*0.34; targetRX = -ndc.y*0.17;
});
autoYaw += dt*0.05;                          // rotação automática lenta contínua
curRY += (targetRY-curRY)*0.045;              // lerp suave até o alvo do mouse
group.rotation.y = autoYaw + curRY;
```
`THREE.Raycaster` projeta o mouse num plano Z=0 para alimentar `uMouse` nos shaders (glow de
proximidade).

**Pausa**: `IntersectionObserver(rootMargin:'120px 0px')` + `visibilitychange`;
`prefers-reduced-motion` renderiza 1 frame estático (rotação fixa, pulsos com alpha zerado).
**Fallback sem WebGL**: remove o canvas silenciosamente (`canvas.remove()`), sem SVG substituto.

## Postura — 3D ambiente, NUNCA centerpiece

```css
#neural-canvas{
  position: absolute; inset: 0; width:100%; height:100%; z-index: 0;
  pointer-events: none; opacity: 0.72;
  mask-image: radial-gradient(85% 82% at 58% 46%, #000 30%, transparent 98%);
}
```
Cobre a seção `#seguranca` inteira como camada de fundo **atrás** do diagrama SVG de arquitetura
(`z-index:0` vs `.security-grid{z-index:1}`), `pointer-events:none`, máscara radial dissolvendo as
bordas — nuvem de partículas ambiente atrás do conteúdo real, nunca um "hero 3D" dominante.

## Segundo uso de canvas — relâmpagos no hero (Canvas 2D, não Three.js)

```js
function spawnBolt() {
  var x = w*(0.2+Math.random()*0.65), y = -10;
  var pts = [[x,y]];
  var maxY = h*(0.45+Math.random()*0.35);
  while (y < maxY) { x += (Math.random()-0.5)*44; y += 14+Math.random()*24; pts.push([x,y]); }
  // ramos: 20% de chance por segmento intermediário de nascer um branch lateral
}
```
`ctx.shadowBlur=10`, `shadowColor:'rgba(82,134,244,0.85)'`. CSS: `#lightning-canvas{
mix-blend-mode:screen; pointer-events:none }` — "screen" clareia sobre o vídeo sem opacar.

## Hero — postura e vídeo

Vídeo é fundo total da seção, mascarado radialmente e velado:
```css
.hero-media video{ width:100%; height:100%; object-fit:cover; opacity:0.55;
  mask-image: radial-gradient(115% 90% at 62% 38%, #000 30%, transparent 78%); }
.hero-veil{ background:
  linear-gradient(180deg, rgba(2,8,23,.72) 0%, rgba(2,8,23,.25) 34%, rgba(2,8,23,.55) 72%, var(--bg) 100%),
  radial-gradient(70% 60% at 18% 62%, rgba(2,8,23,.82) 0%, transparent 100%); }
```
Empilhamento: `.hero-media`(z0, vídeo+canvas relâmpago) → `.hero-veil` → `.hero-inner`(z2, grid 2
colunas) → `.hero-stats`. Grid: `1.7fr / 1fr` — copy à esquerda, `.hero-rail` (glass, 4 pilares) à
direita.

## Motion — GSAP + ScrollTrigger, DECOUPLED do Three.js

```js
if (hasGsap && !reduced && typeof window.ScrollTrigger !== 'undefined') {
  gsap.registerPlugin(ScrollTrigger);
  document.querySelectorAll('[data-reveal]').forEach(function(el){
    gsap.fromTo(el, {opacity:0, y:28}, {
      opacity:1, y:0, duration:0.9, ease:'power3.out',
      scrollTrigger:{ trigger:el, start:'top 88%', once:true }
    });
  });
  // fallback: após 2.4s, força progress(1) em qualquer tween ainda invisível
}
```
**Como combina com Three.js**: GSAP/ScrollTrigger controla exclusivamente a camada DOM (headings,
cards, listas); Three.js roda **independentemente** num loop rAF próprio controlado por
`IntersectionObserver` (não `ScrollTrigger`) — as duas engines nunca compartilham timeline. GSAP
revela o texto/diagrama por cima; o Three.js já roda por baixo como atmosfera contínua, não
sincronizada a scroll.

Outros padrões: contadores do hero (`IntersectionObserver` + rAF + easing cúbico manual pt-BR);
chat demo assíncrono (máquina de estados digitando char-a-char, loop de 3 cenários); checklist
LGPD (`setInterval(1100ms)` marca item por item); marquees infinitos (conteúdo duplicado no HTML).

## Layout

Bento grid de 4 recursos assimétrico (`1.35fr 1fr 1fr`, `.card-privacy{grid-row:1/3}`,
`.card-infra{grid-column:2/4}`). Cada card bento tem microanimação CSS-only própria. Diagrama de
arquitetura: SVG inline com `linearGradient`/`radialGradient`, `stroke-dasharray` animado
simulando fluxo de dados — argumento central ("dados nunca saem da infraestrutura") vira imagem.

## Assets

Vídeo real + 2 imagens únicos bitmaps. Diagrama de segurança SVG autoral. Grão via `feTurbulence`.
Constelação 3D 100% procedural (shaders GLSL à mão). Ícones SVG inline.

## O movimento distintivo

3D como atmosfera de "confiança" por trás de um diagrama técnico, não como hero. Em vez de objeto
3D chamativo em primeiro plano, uma nuvem neural de 120 nós com shaders custom (glow aditivo,
pulsos de "inferência", drift orgânico) posicionada como camada ambiente atrás do diagrama de
arquitetura — mascarada radialmente, `pointer-events:none`, opacity .72. Combinada com
GSAP/ScrollTrigger cuidando só da entrada do texto, a peça 3D nunca compete com a leitura: sustenta
emocionalmente o argumento sem nunca ser o centro da composição — o oposto do FORJA, onde o 3D é
protagonista explícito e interativo.
