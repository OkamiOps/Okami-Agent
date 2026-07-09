# Estilo 01 — MONOLITH (estúdio de arquitetura brutalista)

Pôster suíço industrial cruzado com fotografia P&B de Tadao Ando. Voz de manifesto, frases curtas
e duras. Fonte: leitura linha a linha de `index.html` + `css/style.css` + `js/main.js`.

## Token block (`:root`)

```css
:root {
  --paper: #ECEAE5;        /* fundo — papel industrial claro, não branco puro */
  --paper-deep: #E2DFD8;   /* fundo secundário (cards, hover) */
  --ink: #141412;          /* texto principal — quase-preto, não #000 */
  --ink-soft: #45423D;     /* texto secundário */
  --line: rgba(20, 20, 18, 0.22); /* toda borda/divisor do site usa essa var */
  --oxide: #9E3B26;        /* ÚNICA cor de destaque — vermelho-ferrugem "óxido" */
  --font-display: "Anton", "Arial Narrow", sans-serif;
  --font-text: "Archivo", "Helvetica Neue", sans-serif;
  --font-mono: "JetBrains Mono", "Courier New", monospace;
  --pad: clamp(1.25rem, 4vw, 4rem);  /* padding lateral fluido — usado em TODAS seções */
}
```

Sem dark mode — o único "tema" é a inversão pontual (`.footer`, `.sec-head-inv`) usando `--ink`
como fundo.

## Fontes e uso

`Anton` (display, peso único mas ultra-condensada) sempre uppercase; `Archivo` (corpo, 400/500/600);
`JetBrains Mono` (nav/metadado/legendas, sempre uppercase + `letter-spacing: 0.1–0.16em`). Essa
tripla fixa dá o ar de "placa de obra"/"documento técnico impresso".

## Postura de hero: sem 3D — o herói é o blend mode

O vídeo é uma caixa normal em P&B (via `filter`), posicionada absoluta no canto superior direito:

```css
.hero { position: relative; min-height: 100svh; overflow: clip; }
.hero-frame {
  position: absolute; top: 9svh; right: 0; width: 58vw; height: 78svh;
  background: #1c1c1a; overflow: hidden;
  border-left: 1px solid var(--line); border-bottom: 1px solid var(--line);
}
.hero-frame video { width: 100%; height: 100%; object-fit: cover; filter: grayscale(1) contrast(1.05); }
```

Quem recebe o blend é o **título**, irmão do vídeo com `z-index` maior — não filho dele:

```css
.hero-title {
  position: absolute; left: max(-0.05em, -12px); bottom: 16svh; z-index: 2;
  font-family: var(--font-display);
  font-size: clamp(6.5rem, 20.5vw, 19rem);   /* tipografia GIGANTE — brutalismo suíço */
  line-height: 0.83;                          /* < 1 = letras quase se tocam */
  letter-spacing: -0.015em; color: #E2DFD8;
  mix-blend-mode: difference;                 /* <<< a técnica */
  margin-left: calc(var(--pad) * 0.5);
}
```

## A técnica-assinatura: `mix-blend-mode: difference`

`difference` calcula `|cor-do-elemento - cor-do-que-está-por-baixo|` pixel a pixel. Com o título em
`#E2DFD8` (quase branco) sobre `--paper` `#ECEAE5` (também quase branco), a diferença é ~0 → título
quase invisível sobre o papel. Onde o título cruza o vídeo em P&B, a diferença gera contraste
dinâmico automático: sobre pixel escuro do vídeo o texto aparece claro, sobre pixel claro aparece
escuro — **sem nenhum código de detecção de contraste**, é resultado matemático do blend mode.

Repete-se nos títulos de projeto (`.panel-title`, cruzando fotos) e na **nav inteira**:

```css
.nav {
  position: fixed; z-index: 80; mix-blend-mode: difference; color: #E6E4DE;
  pointer-events: none;   /* blend-mode não bloqueia clique — precisa disso pra não cobrir a viewport */
}
.nav > * { pointer-events: auto; }  /* devolve clique só pros filhos reais */
```

Isso faz a nav ficar sempre legível independente do fundo — nav adaptativa sem JS de scroll-color.

**Pré-requisito**: o elemento por trás precisa de `background` opaco e sólido conhecido — senão o
`difference` calcula contra o fundo do `<body>`/branco do navegador e não "lê" a mídia:

```css
.panel { background: var(--paper); /* backdrop p/ mix-blend dos títulos dentro do track transformado */ }
```

### Código mínimo reproduzível

```html
<div class="frame">
  <video autoplay muted loop playsinline style="filter:grayscale(1)"></video>
  <h1 class="title">TÍTULO</h1>
</div>
```
```css
.frame { position: relative; background: #1c1c1a; overflow: hidden; }
.title {
  position: absolute; inset: 0; display: grid; place-items: center;
  font-size: 12vw; line-height: 0.85; color: #eee;
  mix-blend-mode: difference;   /* <<< toda a mágica está aqui */
}
```

## Motion — GSAP completo

Split de palavras manual (sem plugin pago), destaque curatorial manual de palavras específicas:

```js
function splitWords(el) {
  var text = el.textContent.replace(/\s+/g, " ").trim();
  var words = text.split(" ");
  var accent = ["Construímos.", "intenção.", "luz"];
  el.textContent = "";
  words.forEach(function (w, i) {
    var span = document.createElement("span");
    span.className = "w" + (accent.indexOf(w) > -1 ? " w-oxide" : "");
    span.textContent = w;
    el.appendChild(span);
    if (i < words.length - 1) el.appendChild(document.createTextNode(" "));
  });
  return el.querySelectorAll(".w");
}
```

`gsap.matchMedia()` faz o gating de mobile/desktop e `prefers-reduced-motion`:

```js
var mm = gsap.matchMedia();
mm.add("(prefers-reduced-motion: no-preference)", function () {
  var tl = gsap.timeline({ defaults: { ease: "power4.out" } });
  tl.from(".hero-frame", { clipPath: "inset(0 0 100% 0)", duration: 1.3, ease: "power3.inOut" })
    .from(".hero-word", { yPercent: 108, duration: 1.1, stagger: 0.12 }, "-=0.55")
    .from([".hero-meta", ".hero-foot"], { autoAlpha: 0, y: 24, duration: 0.8, stagger: 0.1 }, "-=0.6");

  gsap.fromTo(manifestoWords, { autoAlpha: 0.13, y: 8 }, {
    autoAlpha: 1, y: 0, ease: "none", stagger: 0.06,
    scrollTrigger: { trigger: manifestoEl, start: "top 78%", end: "bottom 45%", scrub: 0.4 }
  });

  gsap.utils.toArray("[data-reveal]").forEach(function (el, i) {
    gsap.from(el, {
      autoAlpha: 0, y: 46, duration: 0.9, ease: "power4.out",
      delay: (i % 4) * 0.07,
      scrollTrigger: { trigger: el, start: "top 88%" }
    });
  });
  return function () {};
});
```

**Galeria horizontal pinada** (segunda técnica-assinatura, desktop ≥900px) — `containerAnimation`
permite parallax secundário *dentro* de uma seção já controlada por scroll horizontal:

```js
mm.add("(min-width: 900px) and (prefers-reduced-motion: no-preference)", function () {
  var track = document.querySelector(".projects-track");
  var section = document.querySelector(".projects");
  var getAmount = function () { return Math.max(0, track.scrollWidth - window.innerWidth); };

  var tween = gsap.to(track, {
    x: function () { return -getAmount(); }, ease: "none",
    scrollTrigger: {
      trigger: section, start: "top top",
      end: function () { return "+=" + getAmount(); },
      pin: true, scrub: 1, anticipatePin: 1, invalidateOnRefresh: true
    }
  });

  gsap.utils.toArray(".panel-fig img").forEach(function (img) {
    gsap.fromTo(img, { x: "-9%" }, {
      x: "0%", ease: "none",
      scrollTrigger: {
        trigger: img.closest(".panel"), containerAnimation: tween,   // <<< chave
        start: "left right", end: "right left", scrub: true
      }
    });
  });
  return function () {};
});
```

CSS que sustenta o pin: `.projects-viewport{overflow:clip}`, `.projects-track{display:flex;
align-items:stretch; width:max-content; min-height:100svh; will-change:transform}`.

Higiene: pausa vídeo em aba oculta, `ScrollTrigger.refresh()` no `load` (compensa fontes tardias):
```js
document.addEventListener("visibilitychange", function () {
  if (document.hidden) { video.pause(); } else { video.play().catch(function () {}); }
});
window.addEventListener("load", function () { ScrollTrigger.refresh(); });
```

## Layout e ritmo

- `--pad: clamp(1.25rem, 4vw, 4rem)` em todo padding de seção — consistência sem media queries.
- `.sec-head` (cabeçalho de seção repetido): número (oxide) / label mono / cruz `+`, `border-top`
  + `border-bottom` 1px — visual "cabeçalho de documento técnico".
- `grid-template-columns: minmax(3.5rem, 8vw) 1fr minmax(0, 38vw)` no grid de processo; corpo
  expansível on-hover via `grid-template-rows: 0fr → 1fr` (accordion sem altura fixa, só CSS).
- Marquee duplo, direções opostas, um preenchido + um `-webkit-text-stroke` outline.
- Grão de ruído industrial global: SVG turbulence inline em `body::after`, `mix-blend-mode:
  multiply`, `opacity:0.05`, `background-size:260px 260px`.
- Zero `border-radius` no site inteiro; única cor de destaque (`--oxide`); grid documental
  (números de seção, códigos "DOC-SP-009 / REV 4.1", coordenadas geográficas).

Escala tipográfica (tudo Anton, uppercase, line-height apertado): hero title
`clamp(6.5rem,20.5vw,19rem)`/0.83; manifesto `clamp(1.9rem,4.6vw,4.3rem)`/1.06; marquee
`clamp(3.4rem,8.5vw,8rem)`; panel title `clamp(3rem,6.4vw,6.2rem)`/0.88; footer mark
`clamp(5rem,19.5vw,19rem)` cor `rgba(236,234,229,0.12)` (quase invisível, textura de fundo).

## Assets

Vídeo real (`hero-fog.mp4`) + 4 fotos JPEG, todos tratados via CSS `filter: grayscale(1)
contrast(1.04-1.05)` em runtime (nunca pré-processado) — unifica paleta P&B sem editar arquivos
originais. Nenhum canvas/3D gerado — a única geração procedural é o ruído SVG do grain. Números
gigantes de projeto são texto puro com `-webkit-text-stroke`, não imagem.
