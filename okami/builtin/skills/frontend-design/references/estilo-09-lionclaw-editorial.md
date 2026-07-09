# Estilo 09 — Lionclaw, Edição Nº 001 (editorial de revista)

Conceito A para uma IDE de agentic coding — capa de revista de luxo em movimento, leão em vídeo
como protagonista absoluto, laranja usado com precisão cirúrgica. Fonte: leitura linha a linha de
`09-lionclaw-editorial/index.html` + `css/style.css` + `js/main.js`.

Ver também `estilo-10-lionclaw-grid.md` — mesma marca, execução oposta (spec-sheet suíça). Os dois
compartilham hex de laranja (`#E17200`), família display (`Hanken Grotesk`) e bezier de easing
(`cubic-bezier(.16,1,.3,1)`) — só a fonte mono, o uso de itálico e a estrutura de layout mudam.

## Token block (`:root`)

```css
:root{
  --paper:#FDFCFA;
  --ink:#16130F;
  --ink-soft:#5C544B;
  --ink-faint:#9A9187;
  --accent:#E17200;
  --hairline:rgba(22,19,15,.16);
  --hairline-soft:rgba(22,19,15,.09);
  --ease-out:cubic-bezier(.16,1,.3,1);
  --ease-cine:cubic-bezier(.32,.72,0,1);   /* ease "cinematográfico", mais lento no fim */
  --font-display:"Hanken Grotesk",sans-serif;
  --font-mono:"IBM Plex Mono",monospace;
  --pad:clamp(20px,4vw,64px);
}
```

`--ink` não é preto puro, `--paper` não é branco puro — off-white de papel físico. Pesos itálicos
200/300/400 de Hanken Grotesk carregados de propósito: itálico fino (`font-weight:200;
font-style:italic`) em toda palavra de transição editorial (`hero__eyebrow`, `spread__sub`,
`quote__text`) — assinatura tipográfica de revista de luxo: título bold 800 quebrado por linha fina
itálica. Textura de grain: SVG `feTurbulence` data-URI, `opacity:.05, z-index:90`.

## Técnica-assinatura: leão atravessando o headline (texto na frente E atrás)

A palavra é escrita **duas vezes no DOM**, sobreposta em posição absoluta idêntica, com o vídeo do
leão entre as duas cópias — 100% CSS (z-index + clip-path), não recorte de imagem:

```html
<h1 class="hero__title">
  <span class="hero__eyebrow" data-hero-fade>O código tem</span>
  <span class="hero__word-wrap">
    <span class="hero__word hero__word--back" aria-hidden="true">INSTINTO.</span>
    <span class="hero__video-shell">
      <video class="hero__video" autoplay muted loop playsinline preload="auto"
             poster="assets/lion-walk-white.jpg" src="assets/hf-lion-walk-toward.mp4"></video>
    </span>
    <span class="hero__word hero__word--front">INSTINTO.</span>
  </span>
</h1>
```

```css
.hero__word-wrap{ position:relative; display:block; height:clamp(300px,62vh,640px); }
.hero__word{
  position:absolute; left:50%; top:54%; transform:translate(-50%,-50%);
  font-size:clamp(64px,12.6vw,196px); font-weight:800; letter-spacing:-.015em; line-height:1;
  white-space:nowrap; user-select:none;
}
.hero__word--back{ z-index:1; }                 /* cópia 1: atrás do leão, inteira */
.hero__word--front{
  z-index:3;
  clip-path:inset(58% 0 0 0);                    /* cópia 2: só a metade DE BAIXO é visível */
}
.hero__video-shell{
  position:absolute; left:50%; bottom:0; z-index:2;   /* leão fica ENTRE as duas cópias */
  transform:translateX(-50%); width:min(58vw,880px); aspect-ratio:1284/716;
  pointer-events:none;
}
.hero__video{
  width:100%; height:100%; object-fit:cover;
  mix-blend-mode:multiply;                              /* funde o vídeo no fundo #FDFCFA */
  filter:brightness(1.2) contrast(1.02) saturate(1.06);
  mask-image:radial-gradient(ellipse 72% 78% at 50% 55%,#000 55%,transparent 92%);
  /* bordas do vídeo dissolvem em transparência — leão parece emergir do papel */
}
```

**Como funciona em 3 camadas de z-index**: (1) `z-index:1` `--back`: palavra inteira atrás de
tudo, o leão pisa "por cima" cobrindo a metade de cima. (2) `z-index:2` vídeo do leão, `multiply`
funde no papel sem retângulo visível, `mask-image` radial dissolve as bordas. (3) `z-index:3`
`--front`: a MESMA palavra de novo, cortada com `clip-path:inset(58% 0 0 0)` — só os 42% de baixo
ficam visíveis, sobrepostos ao leão. Resultado: metade de cima da palavra atrás do animal, metade
de baixo na frente ("patas pisando" no texto). A palavra é duplicada e cada cópia cortada/
empilhada; o vídeo fica sanduichado no meio com blend mode.

`mix-blend-mode:multiply` no vídeo (fundo branco de estúdio) o faz desaparecer contra `--paper` —
não existe "retângulo branco" por cima do texto, só a silhueta escura do leão sobrevive ao blend.

GSAP anima a entrada com letras splitadas (`<span class="char">`); **as duas cópias recebem
exatamente o mesmo stagger, no mesmo timestamp** — são a mesma palavra, precisam animar em
sincronia perfeita ou a ilusão quebra:

```js
document.querySelectorAll(".hero__word").forEach(function (word) {
  var text = word.textContent;
  word.textContent = "";
  text.split("").forEach(function (ch) {
    var s = document.createElement("span");
    s.className = "char"; s.textContent = ch;
    word.appendChild(s);
  });
});
var intro = gsap.timeline({ defaults: { ease: "power4.out" } });
intro
  .fromTo(".hero__video-shell", { opacity: 0, scale: 1.05 }, { opacity: 1, scale: 1, duration: 1.6, ease: "power2.out" }, 0.15)
  .fromTo(".hero__word--back .char", { yPercent: 60, opacity: 0 }, { yPercent: 0, opacity: 1, duration: 1.1, stagger: 0.045 }, 0.35)
  .fromTo(".hero__word--front .char", { yPercent: 60, opacity: 0 }, { yPercent: 0, opacity: 1, duration: 1.1, stagger: 0.045 }, 0.35);
```

No scroll, parallax sutil desloca as duas cópias juntas (seletor único pegando ambas as classes,
mantendo o registro):
```js
gsap.to(".hero__word--back, .hero__word--front", {
  yPercent: -14, ease: "none",
  scrollTrigger: { trigger: ".hero", start: "top top", end: "bottom top", scrub: true }
});
```

### Código mínimo reproduzível

```html
<span class="word-wrap">
  <span class="word word--back">TEXTO</span>
  <span class="video-shell"><video class="vid" src="leao.mp4" autoplay muted loop></video></span>
  <span class="word word--front">TEXTO</span>
</span>
```
```css
.word-wrap{ position:relative; }
.word{ position:absolute; inset:0; display:flex; align-items:center; justify-content:center; }
.word--back{ z-index:1; }
.word--front{ z-index:3; clip-path:inset(58% 0 0 0); }
.video-shell{ position:absolute; z-index:2; }
.vid{ mix-blend-mode:multiply; mask-image:radial-gradient(ellipse 72% 78% at 50% 55%,#000 55%,transparent 92%); }
```

## Segunda aplicação do princípio: `mask-moment` (wipe + texto vazado)

Seção "TEXT-MASK" repete texto+vídeo sobrepostos, mas com blend `screen` e sem duplicar o texto:
```css
.mask-moment__stage{ position:relative; height:clamp(160px,30vw,430px); isolation:isolate; }
.mask-moment__video{ position:absolute;inset:0;z-index:1; object-fit:cover; }
.mask-moment__overlay{
  position:absolute;inset:0;z-index:2; background:#FDFCFA;
  mix-blend-mode:screen;                 /* screen sobre paper claro "queima" o texto preto no vídeo */
  display:flex;align-items:center;justify-content:center;
}
.mask-moment__word{ font-weight:800; font-size:clamp(58px,16.4vw,248px); color:#000; }
```
`isolation:isolate` no `.stage` cria novo contexto de blend, evitando vazamento do `screen` para
fora da seção.

Wipe laranja de transição (usado aqui e no CTA final):
```js
function wipe(sectionSel, wipeSel, contentSel) {
  var tl = gsap.timeline({ scrollTrigger: { trigger: sectionSel, start: "top 72%", once: true } });
  tl.set(contentSel, { opacity: 0 })
    .to(wipeSel, { scaleX: 1, duration: 0.55, ease: "power3.in", transformOrigin: "left center" })
    .set(contentSel, { opacity: 1 })
    .to(wipeSel, { scaleX: 0, duration: 0.75, ease: "power3.out", transformOrigin: "right center" });
}
```
`<div>`s vazios `background:var(--accent)`, `scaleX(0)→1` (varre em laranja, escondendo a troca de
conteúdo) → `1→0` saindo pela direita (`transform-origin` trocado = "cortina" assimétrica).

## Postura: vídeo real, não 3D — protagonista emocional

Nenhum Three.js/WebGL neste site — a peça central é sempre vídeo real com composição CSS
(blend/clip-path/mask), não geometria 3D.

## Motion geral

Reveal padrão staggered, estado inicial via CSS puro (evita flash-of-unstyled):
```js
gsap.utils.toArray("[data-reveal]").forEach(function (el) {
  gsap.fromTo(el, { opacity: 0, y: 34 }, { opacity: 1, y: 0, duration: 1.1, ease: "power3.out",
    scrollTrigger: { trigger: el, start: "top 88%", once: true } });
});
```
```css
.js [data-reveal]{opacity:0;transform:translateY(34px)}
.js [data-hero-fade]{opacity:0}
```
(a classe `.js` só é adicionada pelo próprio script — se JS falhar/`prefers-reduced-motion`, o
`<html>` nunca ganha `.js` e tudo já nasce visível).

Numerais grandes com contorno fazem parallax vertical:
```css
.spread__num{ color:transparent; -webkit-text-stroke:1px var(--accent); font-size:clamp(64px,8vw,128px); }
```
Vídeos pausam fora do viewport via `ScrollTrigger` por `<video>` + listener global de
`visibilitychange`.

## Layout editorial

Grid assimétrico 7fr/4fr para manifesto e CTA. "Spreads" (páginas duplas) alternando lado da
imagem via `spread--a/b/c`. Hairlines finas como únicas divisórias — nunca sombra de card, sempre
linha de régua de revista. Marquee infinito de créditos (`translateX(-50%)`, conteúdo duplicado
2×).

## Assets

6 vídeos `.mp4` (footage real, Pexels/HF, citado no rodapé), `poster` `.jpg` como primeiro-frame
estático. `liondesign-paw.svg` (bullet). `logo-lionclaw.png` (raster). Nenhum SVG desenhado inline
neste site (diferente do 10) — tudo é tipografia + vídeo + CSS.

## O movimento distintivo

Palavra duplicada, cortada em duas camadas (`clip-path:inset()`), com o vídeo do leão
"sanduichado" entre as camadas via z-index + `mix-blend-mode:multiply` + `mask-image` radial — o
leão "anda para dentro da página", atravessando o headline sem nunca parecer um `<video>`
retangular colado.
