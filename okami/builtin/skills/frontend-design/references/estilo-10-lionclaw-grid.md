# Estilo 10 — Lionclaw, Ficha Técnica Nº 10 (grid/spec-sheet)

Conceito B para a mesma marca do estilo 09 — deliberadamente o oposto: International Typographic
Style encontrando spec-sheet de software. Racional, seco, sistemático. Fonte: leitura linha a
linha de `10-lionclaw-grid/index.html` + `css/style.css` + `js/main.js`.

Ver `estilo-09-lionclaw-editorial.md` para a outra execução da mesma marca (mesmo laranja
`#E17200`, mesma `Hanken Grotesk`, mesmo `cubic-bezier(.16,1,.3,1)`) — a marca é a mesma pessoa em
dois figurinos: 09 é a capa de revista, 10 é a ficha técnica que vem depois.

## Token block (`:root`)

```css
:root {
  --maxw: 1400px;
  --gutter: 28px;
  --ink: #141518;
  --ink-2: #5c5d61;
  --ink-3: #8e8f93;
  --line: rgba(20, 21, 24, 0.10);
  --line-soft: rgba(20, 21, 24, 0.055);
  --orange: #E17200;               /* MESMO hex do --accent do site 09 */
  --bg: #ffffff;
  --bg-warm: #fafaf8;
  --font-sans: "Hanken Grotesk", "Helvetica Neue", Arial, sans-serif;
  --font-mono: "JetBrains Mono", "SF Mono", monospace;
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
}
```

Sem itálico em lugar nenhum (reforça o tom técnico, sem floreio) — diferença única de fonte vs 09:
mono muda de "editorial" (`IBM Plex Mono`) pra "técnica" (`JetBrains Mono`). Fundo `#ffffff` puro
(não off-white como 09) — estética "papel de plotter", não "papel de revista".

## Técnica-assinatura: grid de 12 colunas visível por cima de tudo

`<div>` fixo logo no `<body>`, antes de qualquer conteúdo, com 12 `<i>` vazios:
```html
<div class="grid-lines" aria-hidden="true">
  <div class="grid-lines-inner">
    <i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i>
  </div>
</div>
```

Cada `<i>` é só uma borda esquerda; vira 12 réguas verticais fixas na tela:
```css
.grid-lines {
  position: fixed; inset: 0; pointer-events: none;
  z-index: 40;                       /* ACIMA de todo o conteúdo, abaixo só do nav/metabar (z:45) */
}
.grid-lines-inner {
  height: 100%; max-width: var(--maxw); margin: 0 auto; padding: 0 var(--gutter);
  display: grid; grid-template-columns: repeat(12, 1fr);
}
.grid-lines-inner i {
  display: block; border-left: 1px solid var(--line-soft);   /* opacidade ~5.5% */
}
.grid-lines-inner i:last-child { border-right: 1px solid var(--line-soft); }
```

Por que funciona como feature de design e não "grid de dev esquecido no CSS": (1)
`pointer-events:none` — nunca bloqueia clique. (2) `var(--line-soft)` ~5.5% opaco — textura de
régua de papel, nunca compete com o conteúdo. (3) `position:fixed` — as réguas ficam craveadas na
viewport; o conteúdo real (`.g{display:grid;grid-template-columns:repeat(12,1fr)}`) **usa as
mesmas 12 colunas e o mesmo `--gutter`**, então todo `grid-column:X/Y` se alinha exatamente às
réguas visíveis — a régua vira prova visual de que o layout obedece à grade. (4) respeita o mesmo
`max-width`/`padding` do `.container`, então em telas ultra-largas as réguas param de esticar
junto com o conteúdo central.

Marcas de registro (crosshairs, linguagem de gráfica offset/print) em cada início de seção:
```css
.cross { position: absolute; width: 15px; height: 15px; pointer-events: none; z-index: 41; }
.cross::before, .cross::after { content: ""; position: absolute; background: rgba(20, 21, 24, 0.38); }
.cross::before { left: 0; right: 0; top: 7px; height: 1px; }   /* traço horizontal */
.cross::after  { top: 0; bottom: 0; left: 7px; width: 1px; }   /* traço vertical: junto formam "+" */
```
Rodapé impresso de cada seção, paginação estilo catálogo:
```html
<p class="sec-print mono"><span>LCW/GRID — arquitetura</span><span>p. 02 / 07 · v2.4.1</span></p>
```
Cada seção literalmente se numera como página de catálogo impresso (`p. 02/07` ... `p. 07/07` no
footer) — metáfora de "documento paginado", não "seção de scroll infinito".

Régua de medição (`.band-ruler`) com tick marks gerados por `repeating-linear-gradient` (zero
imagens): 96 ticks por largura, literalmente uma fita métrica em CSS puro.

### Código mínimo reproduzível

```html
<div class="grid-lines" aria-hidden="true">
  <div class="grid-lines-inner">
    <i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i>
  </div>
</div>
<div class="container"><div class="g"> ...conteúdo real, grid-column: X/Y... </div></div>
```
```css
:root{ --maxw:1400px; --gutter:28px; }
.container{ max-width:var(--maxw); margin:0 auto; padding:0 var(--gutter); }
.g{ display:grid; grid-template-columns:repeat(12,1fr); }
.grid-lines{ position:fixed; inset:0; pointer-events:none; z-index:40; }
.grid-lines-inner{
  height:100%; max-width:var(--maxw); margin:0 auto; padding:0 var(--gutter);
  display:grid; grid-template-columns:repeat(12,1fr);
}
.grid-lines-inner i{ display:block; border-left:1px solid rgba(20,21,24,.055); }
.grid-lines-inner i:last-child{ border-right:1px solid rgba(20,21,24,.055); }
```

## Spec-sheet / estética de print

Tabela de especificações em colunas fixas mono:
```css
.spec-row {
  display: grid; grid-template-columns: 56px 220px 1fr 130px;
  gap: 0 24px; align-items: baseline; padding: 15px 4px;
  border-bottom: 1px solid var(--line);
  transition: background 0.18s var(--ease-out), padding-left 0.18s var(--ease-out);
}
.spec-row:hover { background: var(--bg-warm); padding-left: 12px; }
```
Cada linha: índice mono (`A.01`), rótulo mono uppercase, valor legível em sans, unidade/tag à
direita — layout clássico de datasheet de hardware. Diagrama SVG com fundo de papel milimetrado:
```css
.arch-diagram {
  border: 1px solid var(--line);
  background:
    repeating-linear-gradient(to right, transparent 0 39px, var(--line-soft) 39px 40px),
    repeating-linear-gradient(to bottom, transparent 0 39px, var(--line-soft) 39px 40px),
    var(--bg-warm);
  padding: 8px;
}
```
SVG (`viewBox="0 0 1160 700"`) escrito manualmente: retângulos, linhas ortogonais em L
(`path d="M... H... V... H..."`), texto mono, nós de sincronização (círculos laranja) — diagrama
de arquitetura como blueprint técnico.

## Postura: vídeo real dentro de "viewports" do grid + pin-zoom no scroll

O leão vive dentro de "viewports" retangulares do grid, como instrumentação observando um animal
(SPEC 01 — LEO PANTHERA / RUNTIME, HUD com resolução e ponto REC) — nunca solto na tela como no 09.

**Efeito headline: o viewport do leão "zoom" até quase tela cheia**, pin de seção:
```js
ScrollTrigger.matchMedia({
  "(min-width: 768px) and (max-height: 1599px)": function () {
    var stage = document.querySelector(".hero-stage");
    var vp = document.getElementById("heroViewport");
    function target() {
      var w = vp.offsetWidth, h = vp.offsetHeight;
      var vw = window.innerWidth, vh = window.innerHeight;
      var o = offsetWithin(vp, stage);
      var s = Math.min((vw * 0.94) / w, (vh * 0.88) / h);
      return { s: s, x: vw/2 - (o.x + w/2), y: vh/2 - (o.y + h/2) };
    }
    var tl = gsap.timeline({
      scrollTrigger: { trigger: stage, start: "top top", end: "+=160%",
        scrub: 0.6, pin: true, anticipatePin: 1, invalidateOnRefresh: true }
    });
    tl.to(".hero-copy", { opacity: 0, y: -70, ease: "power1.in", duration: 0.42 }, 0)
      .to(vp, { scale: function(){return target().s;}, x: function(){return target().x;},
                y: function(){return target().y;}, ease: "power1.inOut", duration: 1 }, 0);
  }
});
```
Calcula em tempo real o fator de escala pra centralizar o viewport do vídeo na tela conforme o
scroll — o "spec box" do leão vira tela cheia (contraste com 09, onde o leão nunca sai do
enquadramento do headline).

**Diagrama SVG se desenha no scroll** (técnica clássica `strokeDasharray = strokeDashoffset =
totalLength`, depois anima para 0):
```js
strokes.forEach(function (el) {
  var len = el.getTotalLength();
  el.style.strokeDasharray = String(len);
  el.style.strokeDashoffset = String(len);
});
var dtl = gsap.timeline({ scrollTrigger: { trigger: ".arch-diagram", start: "top 82%", end: "bottom 62%", scrub: 0.8 } });
strokes.forEach(function (el, i) {
  dtl.to(el, { strokeDashoffset: 0, duration: 0.5, ease: "none" }, i * 0.055);
});
```
Fallback anti-tela-vazia: se o usuário não rolar em 2.6s, força todos `.rv` a `in` e o diagrama a
`progress(1)` — útil para screenshot headless.

## Motion: `IntersectionObserver` para reveal simples, GSAP só para scroll-scrubbed complexo

```js
var io = new IntersectionObserver(function (entries) {
  entries.forEach(function (e) {
    if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
  });
}, { threshold: 0.12, rootMargin: "0px 0px -6% 0px" });
```
```css
.rv { opacity: 0; transform: translateY(18px);
  transition: opacity 0.7s var(--ease-out), transform 0.7s var(--ease-out);
  transition-delay: calc(var(--rvi, 0) * 90ms); }         /* stagger via custom property inline */
.rv.in { opacity: 1; transform: translateY(0); }
```

## Layout: grid técnico exposto, posicionamento explícito

```css
.hero-copy    { grid-column: 1 / 8; }
.hero-vp-wrap { grid-column: 8 / 13; }
.nav-brand    { grid-column: 1 / 4; }
.nav-links    { grid-column: 4 / 11; }
.foot-col     { grid-column: span 3; border-left: 1px solid var(--line); padding-left: 26px; }
```
`border-left` em links de nav e `.foot-col` reforça as divisórias de coluna — o grid não é só
posicionamento, é literalmente desenhado com bordas que coincidem com as réguas fixas. Mobile:
grid colapsa de 12 para 4 colunas e as réguas acompanham (`grid-template-columns:repeat(4,1fr)`,
esconde `i:nth-child(n+5)`).

## Assets

Mesmo pool de footage do 09 (arquivos de vídeo próprios reaproveitados). Diagrama de arquitetura:
SVG escrito à mão inline (não gerado por ferramenta), ~30 elementos comentados por seção. Réguas
do grid, crosshairs e band-ruler: 100% CSS, zero imagem.

## O movimento distintivo

Grid de 12 colunas materializado como `<div>` fixo com 12 filhos vazios de `border-left`, em
`position:fixed; z-index:40` acima do conteúdo mas abaixo do nav, alinhado ao `max-width`/`padding`
do container real — todo elemento posicionado por `grid-column` bate exatamente nas réguas
visíveis. As réguas ficam por cima de TUDO, inclusive vídeo, o tempo todo — o grid não é fundo
decorativo, é a lente através da qual a página inteira é lida.
