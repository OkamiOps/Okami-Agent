# Estilo 05 — Kinetic Labs (robótica lúdica, estilo Teenage Engineering)

Estúdio de robótica criativa — fundo claro de papel quente, energia lúdica mas técnica,
deliberadamente o oposto de dark-tech. Fonte: leitura linha a linha de `index.html` +
`css/style.css` + `js/main.js`.

## Token block (`:root`)

```css
:root{
  --paper:#F2EFE9;        /* papel quente, bege */
  --paper-deep:#EAE6DD;
  --ink:#1A1918;
  --ink-soft:#55524B;
  --ink-faint:#8A867C;
  --line:#D9D3C6;
  --acid:#9BD34B;         /* verde-ácido — cor de assinatura da marca */
  --acid-deep:#557F1E;    /* usado em texto/ícone sobre paper */
  --acid-tint:#E4EDCB;    /* fundo de card/tile */
  --lilac:#DCD5EC;
  --lilac-tint:#E7E2F1;
  --fog:#E4E1EA;
  --radius:28px;          /* raio ÚNICO usado em quase tudo — cards, process, footer, tiles */
  --font-display:"Bricolage Grotesque", system-ui, sans-serif;
  --font-body:"Archivo", system-ui, sans-serif;
  --font-mono:"DM Mono", ui-monospace, monospace;
}
```

Linguagem "hardware Teenage Engineering": tons pastel neutros + UM acento saturado, cantos muito
arredondados (`--radius:28px` em cards/hero-frame/process/footer/tiles), display bold condensada
variável (300–800) que lembra rotulagem de hardware de consumo lúdico. "Stickers" com specs (ex:
"TATO · v4.2", "força do aperto: 0,8 N") reforçam a linguagem de produto físico com datasheet.

## Técnica-assinatura: spring physics letra-a-letra (GSAP)

HTML — título em `.kin-line`, decomposto pelo JS em `.kin-word`/`.kin-letter`:
```html
<h1 class="hero__title kinetic" aria-label="Máquinas de gênio próprio.">
  <span class="kin-line">Máquinas</span>
  <span class="kin-line">de gênio</span>
  <span class="kin-line">próprio<b class="tick" aria-hidden="true">*</b></span>
</h1>
```

Split JS decompõe em spans de letra individual, preservando acentos/espaços, `--i` global setado
em cada letra (consumido pelo CSS de onda de peso — ver abaixo).

**Entrada da headline** (`back.out`, "pop" — a mola de verdade é no hover):
```js
gsap.from(heroLetters, {
  yPercent: 118, rotation: function () { return gsap.utils.random(-9, 9); }, opacity: 0,
  duration: 0.9, ease: 'back.out(1.8)', stagger: { each: 0.032, from: 'start' }, delay: 0.15
});
```

**A física de mola de verdade (hover em cada letra)** — timeline de 2 passos:
```js
function springLetter(letter) {
  var word = letter.parentNode;
  var all = Array.from(word.children);
  var i = all.indexOf(letter);
  var rot = gsap.utils.random(-14, 14);
  var pop = function (el, dy, r, s) {
    gsap.killTweensOf(el);
    gsap.timeline()
      .to(el, { y: dy, rotation: r, scale: s, duration: 0.16, ease: 'power2.out' })   // impacto rápido
      .to(el, { y: 0, rotation: 0, scale: 1, duration: 1.1, ease: 'elastic.out(1.1,0.32)' }); // overshoot elástico
  };
  pop(letter, -14, rot, 1.12);                          // letra tocada
  if (all[i - 1]) pop(all[i - 1], -6, rot * -0.4, 1.04); // vizinha esquerda: mais fraco, rotação invertida
  if (all[i + 1]) pop(all[i + 1], -6, rot * -0.4, 1.04); // vizinha direita
}
heroLetters.forEach(function (l) { l.addEventListener('pointerenter', function () { springLetter(l); }); });
```
Passo 1 (`power2.out`, 0.16s): impacto — desloca pra cima, gira ±14°, escala 1.12. Passo 2
(`elastic.out(1.1,0.32)`, 1.1s): volta com overshoot — a "mola" propriamente dita. Vizinhas
recebem o mesmo padrão com deslocamento menor e rotação invertida/atenuada — simula propagação de
onda física ao longo da palavra.

**Onda de peso contínua** (CSS puro, independe do hover):
```css
@keyframes kin-weight{
  0%,100%{font-variation-settings:"wght" 800}
  50%{font-variation-settings:"wght" 665}
}
.hero__title .kin-letter{
  animation:kin-weight 4.6s ease-in-out infinite;
  animation-delay:calc(var(--i,0) * -.18s);   /* --i do JS — cria onda de peso percorrendo o texto */
}
```

### Código mínimo reproduzível

```html
<h1 id="t">HELLO</h1>
```
```js
const el = document.getElementById('t');
el.innerHTML = [...el.textContent].map(c => `<span class="letter">${c}</span>`).join('');
const letters = el.querySelectorAll('.letter');
function pop(target, dy, rot, scale) {
  gsap.killTweensOf(target);
  gsap.timeline()
    .to(target, { y: dy, rotation: rot, scale, duration: 0.16, ease: 'power2.out' })
    .to(target, { y: 0, rotation: 0, scale: 1, duration: 1.1, ease: 'elastic.out(1.1,0.32)' });
}
letters.forEach((letter, i) => {
  letter.addEventListener('pointerenter', () => {
    const rot = gsap.utils.random(-14, 14);
    pop(letter, -14, rot, 1.12);
    if (letters[i - 1]) pop(letters[i - 1], -6, rot * -0.4, 1.04);
    if (letters[i + 1]) pop(letters[i + 1], -6, rot * -0.4, 1.04);
  });
});
```
```css
.letter { display: inline-block; will-change: transform; }
```
Regra de ouro: sempre `gsap.killTweensOf(el)` antes de disparar um novo pop — evita "tremedeira"
em hovers rápidos repetidos.

## Postura: sem 3D real — tilt CSS via rAF + canvas 2D de física

**Parallax de hero em camadas** via `gsap.quickTo` (sem recriar tween a cada `pointermove`):
```js
var layers = [
  { sel: '.hero__blobs', fx: 36, fy: 26 },   // fundo: move mais
  { sel: '.hero__frame', fx: -18, fy: -13 }, // contramovimento (profundidade)
  { sel: '.hero__copy',  fx: 9,   fy: 6 }    // texto: quase parado
].map(function (l) {
  var el = document.querySelector(l.sel);
  return { fx: l.fx, fy: l.fy,
    x: gsap.quickTo(el, 'x', { duration: 0.9, ease: 'power3.out' }),
    y: gsap.quickTo(el, 'y', { duration: 0.9, ease: 'power3.out' }) };
});
hero.addEventListener('pointermove', function (e) {
  var nx = e.clientX / window.innerWidth - 0.5, ny = e.clientY / window.innerHeight - 0.5;
  layers.forEach(function (l) { l.x(nx * l.fx); l.y(ny * l.fy); });
});
```

**Botões magnéticos**: `gsap.quickTo` seguindo o cursor dentro do botão, volta com
`elastic.out(1,0.35)` ao sair. **Marquee bidirecional com velocidade reativa ao scroll**
(`ScrollTrigger.getVelocity`): quanto mais rápido rola, mais rápido o marquee (até 4.5x).

**Sticky stack de cards com tilt 3D** — CSS transform via rAF + lerp manual, GSAP só seta o
transform final:
```js
var MAX = 6; // graus máximos
cards.forEach(function (card) {
  gsap.set(card, { transformPerspective: 1100 });
  var tx=0, ty=0, cx=0, cy=0;
  function frame() {
    cx += (tx - cx) * 0.12;   // lerp manual, não elastic
    cy += (ty - cy) * 0.12;
    gsap.set(card, { rotationX: cx, rotationY: cy });
    card.style.setProperty('--tsx', (-cy * 2.2).toFixed(2) + 'px');   // sombra desloca oposto ao tilt
    card.style.setProperty('--tsy', (24 + cx * 2.2).toFixed(2) + 'px');
    requestAnimationFrame(frame);
  }
  card.addEventListener('pointermove', function (e) {
    var r = card.getBoundingClientRect();
    var nx = (e.clientX - r.left) / r.width - 0.5, ny = (e.clientY - r.top) / r.height - 0.5;
    ty = nx * 2 * MAX; tx = -ny * 2 * MAX;
    card.style.setProperty('--mx', ((nx + 0.5) * 100).toFixed(1) + '%');  // posição do "sheen"
    card.style.setProperty('--my', ((ny + 0.5) * 100).toFixed(1) + '%');
  });
});
```
CSS consumindo as custom properties:
```css
.stack-card{ box-shadow:var(--tsx,0px) var(--tsy,24px) 50px -28px rgba(70,64,52,.45), inset 0 1px 0 rgba(255,255,255,.55); }
.stack-card::after{ background:radial-gradient(56rem circle at var(--mx,50%) var(--my,30%),
  rgba(255,255,255,.34), rgba(255,255,255,.06) 38%, transparent 60%); opacity:0; transition:opacity .45s ease; }
```
Em touch, degrada para `ScrollTrigger` com `scrub`, `rotationX` 4.5°→-4.5°. Cards "encolhem" ao
empilhar via `scale`/`opacity` amarrado ao próximo card entrando (`scrollTrigger` scrub 0.4).

**Física de canvas 2D** (bancada de gravidade) — integrador manual de Euler com colisão elástica:
```js
var G = 1500, REST = 0.72;
function integrate(dt) {
  // b.vy += G*dt; b.x += b.vx*dt; b.y += b.vy*dt;
  // colisão com paredes: inverte velocidade * restituição
  // colisão par-a-par: resolve overlap + impulso baseado em massa (r²)
}
```
Controlado por `IntersectionObserver` (só roda visível) + `visibilitychange` +
`prefers-reduced-motion` (faz "settle" instantâneo simulando 260 frames de uma vez).

## Layout

`--radius:28px` consistente em `.hero__frame`, `.stack-card`, `.process` (seção inteira
arredondada), `.tile`, `.footer` — "hardware com cantos macios". `.process`/`.footer` com
`background:var(--ink)` e `border-radius` nos 4 lados, `margin` lateral pequena — literalmente
"flutuam" como painel dentro da página clara. Grid do playground assimétrico:
`grid-template-columns:1.15fr .85fr 1fr` com `tile--counter{grid-row:span 2}`,
`tile--quote{grid-column:span 2}`.

## Assets

3 fotos JPEG reais sem filtro CSS (cores mantidas). Ícones SVG inline. Física de canvas 100%
gerada em runtime (`PALETTE` reaproveita as cores do tema). "Olho" de robô é HTML/CSS puro.

## O movimento distintivo

Tipografia decomposta letra-a-letra que reage a hover com física de mola de duas fases —
impacto rápido (`power2.out`) seguido de retorno elástico com overshoot (`elastic.out(1.1,0.32)`)
— propagando o efeito, atenuado e invertido, para as letras vizinhas, simulando uma "corrente"
mecânica conectando os caracteres.
