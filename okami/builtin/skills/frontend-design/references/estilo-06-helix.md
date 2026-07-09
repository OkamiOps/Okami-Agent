# Estilo 06 — Hélice (diagnósticos genômicos de precisão)

Laboratório de medicina genômica/oncologia — dark científico cuja cor vem literalmente da
microscopia de fluorescência. Fonte: leitura linha a linha de `index.html` + `css/style.css` +
`js/main.js`.

## Token block (`:root`)

```css
:root {
  --bg: #06090F;
  --bg-2: #080D15;
  --bg-3: #0B1220;
  --ink: #EEF3F8;
  --ink-dim: #9BAAB9;
  --ink-faint: #566573;
  --cyan: #34D4CE;         /* ciano de microscopia — cor primária */
  --cyan-deep: #1E9B9C;
  --magenta: #C55C97;      /* magenta de fluorescência — cor secundária */
  --line: rgba(148,176,200,.10);
  --line-2: rgba(148,176,200,.18);
  --glass: rgba(18,30,44,.55);
  --font-display: 'Archivo', system-ui, sans-serif;
  --font-body: 'Instrument Sans', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', monospace;
  --ease: cubic-bezier(0.16,1,0.3,1);
}
```

Diferente de Quantum: **duas** cores de acento (ciano + magenta) — remete a dupla-hélice/dupla-fita
e canais de fluorescência reais (imunofluorescência usa múltiplos canais). Dois níveis de opacidade
de linha (`--line`/`--line-2`) usados sistematicamente para hierarquia de borda.

## Fontes

`Archivo` (300–800) todo display/headline, `Instrument Sans` (400–600) corpo, `JetBrains Mono`
(400/500) dados técnicos (eyebrows, specs, sequência genômica, contadores).

## Implementação 3D — dupla hélice

Three.js **r128** via CDN, mas com **canvas fixo pré-existente no DOM** em vez de `appendChild`:

```html
<canvas id="helix-canvas"></canvas>
<img id="helix-fallback" src="assets/helix-microscopy.jpg" alt="...">
```
```js
renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: true });
if (!renderer.getContext()) return failHelix();
scene.fog = new THREE.FogExp2(0x06090F, 0.055);
camera = new THREE.PerspectiveCamera(42, W/H, 0.1, 100);
camera.position.set(0, 0, 15);
```

Construção 100% procedural, sem `TubeGeometry`/`CatmullRom` — cada "átomo" é uma esfera individual
numa hélice matemática:

```js
var turns = 5, per = 12, total = turns * per;   // 60 posições por fita
var radius = 2.5, pitch = 1.55;
function yAt(i) { return (i / per) * pitch - span / 2; }
for (var i = 0; i < total; i++) {
  var ang = (i / per) * Math.PI * 2;
  var y = yAt(i);
  var xA = Math.cos(ang) * radius, zA = Math.sin(ang) * radius;         // fita A
  var xB = Math.cos(ang + Math.PI) * radius, zB = Math.sin(ang + Math.PI) * radius; // fita B (180° defasada)
  var sA = new THREE.Mesh(sphereGeo, i % 5 === 0 ? magMat : cyanMat);
  var sB = new THREE.Mesh(sphereGeo, i % 7 === 0 ? magMat : cyanMat);
  var rung = new THREE.Mesh(rungGeo, rungMat);   // bastão = par de bases
  rung.position.copy(mid);
  rung.scale.y = dist;
  rung.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0), dir.clone().normalize());
}
```
`SphereGeometry(0.34,20,20)` para os átomos, `CylinderGeometry(0.055,0.055,1,8)` para os rungs —
escalados em Y pela distância real e orientados via quaternion (técnica canônica de "esticar
cilindro entre dois pontos").

**Materiais PBR com luzes reais** (diferente de Quantum, que usa só `MeshBasicMaterial`):

```js
var cyanMat = new THREE.MeshStandardMaterial({ color: 0x34D4CE, roughness:.35, metalness:.2, emissive:0x0a3b3a, emissiveIntensity:.6 });
var magMat  = new THREE.MeshStandardMaterial({ color: 0xC55C97, roughness:.4, metalness:.2, emissive:0x3a1130, emissiveIntensity:.5 });
var rungMat = new THREE.MeshStandardMaterial({ color: 0x8aa8bd, roughness:.6, metalness:.1, emissive:0x0a1620, emissiveIntensity:.3, transparent:true, opacity:.85 });
```

3-point lighting clássico com as duas cores de marca como key/rim:
```js
scene.add(new THREE.AmbientLight(0x223244, 0.9));
var keyLight = new THREE.DirectionalLight(0x34D4CE, 1.5); keyLight.position.set(6,8,6);
var rimLight = new THREE.DirectionalLight(0xC55C97, 1.2); rimLight.position.set(-7,-3,-4);
var fill = new THREE.PointLight(0x4fd8d2, 1.0, 40); fill.position.set(0,0,10);
```
`helix.rotation.z = 0.14` — leve inclinação estática desde o início, reforça leitura orgânica.
Camada de partículas de profundidade atrás (`count = mobile?70:150`, `AdditiveBlending`).

## Animação scroll-linked (diferença estrutural chave vs Quantum)

A hélice é dirigida principalmente por **progresso de scroll**, não tempo livre:

```js
function updateScroll() {
  var max = document.body.scrollHeight - window.innerHeight;
  targetScroll = max > 0 ? window.scrollY / max : 0;
  if (cellsEl) {
    var top = cellsEl.getBoundingClientRect().top;
    var op = Math.max(0, Math.min(1, (top - vh*0.15) / (vh*0.6)));
    canvas.style.opacity = op * (window.innerWidth<=768 ? 0.22 : 1);
  }
}
// no loop:
scrollProg += (targetScroll - scrollProg) * 0.06;    // lerp do progresso
autoRot += dt * 0.12;                                 // rotação autônoma contínua
helix.rotation.y = autoRot + scrollProg * Math.PI * 3.2 + mLX * 0.5;  // scroll gira ATÉ 3.2π
helix.position.y = scrollProg * span * 0.62;           // hélice "sobe" a cena com o scroll
helix.rotation.x = -0.08 + scrollProg * 0.5 + mLY * 0.28;
camera.position.z = 15 - scrollProg * 3.2 - hover * 1.6;  // dolly-in conforme rola
```
Rolar literalmente gira a hélice (~1.6 voltas ao longo do scroll total), translada verticalmente e
aproxima a câmera — scrollytelling 3D genuíno, não fade/parallax simples.

Interação: parallax leve de mouse + hover-zoom sobre `.hero` — **sem drag/orbit manual**, controle
100% passivo (scroll + mouse ambiental). Opacidade: canvas nasce `opacity:0`, ganha `.ready` (CSS
0.25s) só quando a cena está pronta e um frame renderizado.

**Fallback**: `failHelix()` esconde canvas, mostra `#helix-fallback` (foto com `mask-image`).
**Pause em aba oculta**: `visibilitychange` seta `running`, mas descarta `clock.getDelta()`
acumulado antes de religar (evita "salto"). **Reduced motion**: a hélice continua girando via
scroll (só perde parallax de mouse) — diferente de Quantum, que congela em frame estático.

## Hero POSTURA — cenário fixo, não elemento de layout

```css
#helix-canvas{ position:fixed; top:0; right:0; width:58vw; height:100vh; z-index:2; pointer-events:none; opacity:0; transition:opacity .25s linear; }
```
Literalmente um "cenário fixo" atrás do scroll — a hélice permanece visível (fade controlado por
JS) da seção hero até `.cells` (vídeo de microscopia), quando desaparece.

`.hero-grid{grid-template-columns:1.05fr .95fr}`: copy à esquerda, lado direito é label rotacionado
(`writing-mode:vertical-rl`, sequência genômica) — decorativo/textual; a hélice 3D ocupa o espaço
visual real por trás de tudo, não dentro da grid.

Headline: `clamp(48px,6.6vw,92px)`, weight 800, line-height .94, misturando pesos na mesma frase
(`<span class="thin">` weight 300 + `<span class="accent">` cyan). Em ≤1024px: canvas full-width,
opacity .4, coluna direita some. Em ≤768px: `position:absolute` confinado, máscara vertical, scrim
radial garante legibilidade.

## Motion 2D

`IntersectionObserver` + CSS, com `filter:blur()` extra no reveal:
```css
.reveal{ opacity:0; transform:translateY(24px); filter:blur(6px);
  transition:opacity .9s var(--ease), transform .9s var(--ease), filter .9s var(--ease); }
.reveal.in{ opacity:1; transform:none; filter:none; }
.reveal[data-d="1"]{ transition-delay:.08s; } /* até data-d="4" = .32s */
```
Fallback de robustez: `setTimeout(revealAll, 1200)`. **Marquee genômico**: sequências ACGT geradas
em runtime + 7 variantes clínicas reais, `translateX(-50%)` com conteúdo duplicado. **Cards com
spotlight de cursor**: `pointermove` seta `--mx/--my` num `radial-gradient` do `::before`.

## Layout

`.wrap{max-width:1360px}`. Bento-grid deliberadamente assimétrico:
`grid-template-columns:1.4fr 1fr 1fr`, `.card-feature{grid-row:span 2}`. Seção `.cells` (vídeo
autoplay) usa duplo gradiente de overlay para contraste de texto.

## Assets

Fotos reais + vídeo `cells.mp4` (único vídeo do conjunto). Logo SVG inline (2 curvas Bezier
cyan/magenta simulando fitas de DNA). Hélice 3D: 100% geometria procedural.

## O movimento distintivo

Hélice 3D como cenário fixo scroll-driven, não decoração de hero isolada: `position:fixed` atrás
de múltiplas seções, rotação/posição/zoom de câmera são funções diretas do progresso de scroll da
página — "voo pela dupla-hélice" conforme o usuário lê, até desaparecer perto da seção de vídeo.
