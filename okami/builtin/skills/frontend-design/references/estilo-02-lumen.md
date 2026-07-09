# Estilo 02 — Lumen (Arquitetura da Luz)

Firma de arquitetura serena e cara — revista impressa, oposto deliberado do brutalismo do 01. A
página inteira é "um dia de luz" (manhã → meio-dia → poente). Fonte: leitura linha a linha de
`index.html` + `css/style.css` + `js/main.js`.

## Token block (`:root`)

```css
:root{
  --bone:      #FAF8F4;
  --sand:      #F1EBE0;
  --cream:     #F6F1E7;
  --ink:       #2B2825;
  --ink-soft:  #6E675C;
  --gold:      #A9885A;
  --gold-soft: #C4A97E;
  --line:      rgba(43, 40, 37, .14);
  --serif: "Fraunces", "Georgia", serif;
  --sans:  "Instrument Sans", "Helvetica Neue", sans-serif;
  --mono:  "IBM Plex Mono", "SF Mono", monospace;
  --pad-l: 7vw;
  --pad-r: 5vw;
}
```

Monocromática quente (osso → areia → creme → grafite) com **um único** acento dourado — usado só
em `em`, sublinhados de link, índice de projeto e o ponto do sol no arco SVG. `--pad-l`/`--pad-r`
assimétrico (7vw/5vw) é usado em todo o layout em vez de padding fixo — dá a régua vertical
consistente do site inteiro.

## Fontes e uso

`Fraunces` (serif variável `ital,opsz,wght`, pesos leves 300/400/500, itálico em `<em>`) em
títulos/H1/H2/citações; `Instrument Sans` no corpo/nav; `IBM Plex Mono` em todo metadado
(coordenadas, legendas de figura, labels, relógio do dia) com `letter-spacing: .14em` — o "selo
editorial" recorrente. Escala dramática: hero `clamp(48px, 7.6vw, 114px)`.

## Técnica-assinatura: scrolltelling "um dia de luz" (GSAP ScrollTrigger)

Seção `#dia`: `section.dia{height:380vh}` funciona como trilho de scroll, contendo
`.dia-sticky{position:sticky; top:0; height:100dvh}` fixo na tela durante os 380vh.

3 camadas de céu empilhadas (`position:absolute; inset:0`), cada uma com seu próprio gradiente:

```css
.dia-bg-manha{ background: linear-gradient(165deg, #D7E1E6 0%, #EAECE6 55%, #F4F1E9 100%); }
.dia-bg-meiodia{
  background:
    radial-gradient(ellipse 70% 55% at 50% -10%, rgba(255,251,238,.9) 0%, rgba(255,251,238,0) 60%),
    linear-gradient(180deg, #FBF8F1 0%, #F7F3E9 100%);
  opacity: 0;
}
.dia-bg-poente{
  background: linear-gradient(170deg, #F4E0C2 0%, #EFD2A8 52%, #E8C393 100%);
  opacity: 0;
}
```

A transição é **crossfade de opacity entre 3 camadas pré-desenhadas**, não interpolação de cor —
controlada por uma timeline GSAP com `scrub` amarrada ao scroll:

```js
var diaTl = gsap.timeline({
  scrollTrigger: {
    trigger: ".dia", start: "top top", end: "bottom bottom", scrub: 0.5,
    onUpdate: function (self) {
      var p = self.progress;
      var mins = Math.round(DAY_START + p * (DAY_END - DAY_START));
      var h = Math.floor(mins / 60), m = mins % 60;
      clockEl.textContent = (h < 10 ? "0" + h : h) + ":" + (m < 10 ? "0" + m : m);
      tempEl.textContent = temps[p < 0.38 ? 0 : p < 0.72 ? 1 : 2];
      var pos = sunPos(p);
      gsap.set(dot, { attr: { cx: pos.x, cy: pos.y } });
    }
  }
});
diaTl
  .to(".dia-bg-manha",   { opacity: 0, duration: 0.22, ease: "none" }, 0.24)
  .to(".dia-bg-meiodia", { opacity: 1, duration: 0.22, ease: "none" }, 0.24)
  .to(".dia-bg-meiodia", { opacity: 0, duration: 0.24, ease: "none" }, 0.62)
  .to(".dia-bg-poente",  { opacity: 1, duration: 0.24, ease: "none" }, 0.62);
```

`scrub:0.5` (numérico, não boolean) amarra o progresso com 0.5s de "atraso elástico". O relógio,
SVG e texto do "momento" são todos derivados do mesmo `self.progress` (0→1) dentro de um único
`onUpdate` — **um único número dirige céu, relógio, texto e posição do sol**.

O sol se move sobre uma curva de Bézier quadrática SVG (`M 20 195 Q 300 -60 580 195`), recalculada
em JS puro:

```js
function sunPos(t) {
  var mt = 1 - t;
  return {
    x: mt * mt * 20 + 2 * mt * t * 300 + t * t * 580,
    y: mt * mt * 195 + 2 * mt * t * (-60) + t * t * 195
  };
}
```

Textos de cada "momento" entram/saem em janelas de progresso fixas com `fromTo` curtíssimos
(0.06–0.07s) — o efeito de suavidade vem do `scrub`, não da duração da tween:

```js
var slots = [{ inAt: 0.02, outAt: 0.30 }, { inAt: 0.38, outAt: 0.64 }, { inAt: 0.72, outAt: 1.01 }];
moments.forEach(function (el, i) {
  var s = slots[i];
  diaTl.fromTo(el, { autoAlpha: 0, y: 26 }, { autoAlpha: 1, y: 0, duration: 0.07, ease: "power2.out" }, s.inAt);
  if (s.outAt <= 1) diaTl.to(el, { autoAlpha: 0, y: -18, duration: 0.06, ease: "power2.in" }, s.outAt - 0.06);
});
```

Sem `ScrollTrigger.pin` — o "prender a tela" é CSS `position:sticky`; o GSAP só controla a
timeline de opacidade/texto (mais leve que `pin:true`).

### Receita mínima para reproduzir

```html
<section class="dia" style="height:380vh; position:relative">
  <div class="dia-sticky" style="position:sticky; top:0; height:100vh; overflow:hidden">
    <div class="bg-a" style="position:absolute; inset:0"></div>
    <div class="bg-b" style="position:absolute; inset:0; opacity:0"></div>
    <div class="bg-c" style="position:absolute; inset:0; opacity:0"></div>
    <span id="clock"></span>
  </div>
</section>
```
```js
gsap.timeline({
  scrollTrigger: { trigger: ".dia", start: "top top", end: "bottom bottom", scrub: 0.5,
    onUpdate(self){ /* derive clock/label/sun-x-y de self.progress aqui */ } }
})
.to(".bg-a", { opacity: 0, duration: .22 }, .24)
.to(".bg-b", { opacity: 1, duration: .22 }, .24)
.to(".bg-b", { opacity: 0, duration: .24 }, .62)
.to(".bg-c", { opacity: 1, duration: .24 }, .62);
```
Chave: `scrub` numérico, `ease:"none"` nas tweens de crossfade, `onUpdate` central como única
fonte de verdade do "tempo do dia" — tudo o resto (texto, SVG) lê dali.

## Postura: sem 3D — só camadas 2D

Lumen não usa Three.js. A profundidade vem de crossfade de gradientes + parallax de imagem, nunca
de WebGL — a "luz" é inteiramente CSS/SVG.

## Motion geral (4 famílias)

1. **Reveal de linhas com máscara** (`.reveal-lines`): `<span class="line"><span
   class="line-in">...</span></span>`, `.line{overflow:hidden}`, GSAP anima `.line-in` de
   `yPercent:112 → 0`, `stagger:0.09`, `power4.out`, trigger `top 84%, once:true`.
2. **Fade genérico** (`.reveal-fade`): `y:22, autoAlpha:0→1`, `power3.out`, `top 88%, once:true`.
3. **Parallax interno de imagem**: `.parallax-img{height:112%}` desloca `yPercent:-9→0` com
   `scrub:true` enquanto a section atravessa a viewport.
4. **Zoom cinematográfico** (`.zoom`, section `240vh` com `.zoom-sticky`): escala o frame de
   `1→2.24` enquanto a imagem interna desescala `1.35→1` no mesmo intervalo — zoom óptico sem
   cortar bordas; citação faz fade-in só após 55% do progresso.

Easing: `power3.out`/`power4.out` para entradas de texto; `ease:"none"`/`power1.inOut` para tudo
scrubado (nunca easing não-linear em tweens com `scrub`).

`prefers-reduced-motion`: o script faz early-return após resolver só o estado da nav, sem
registrar nenhuma animação; CSS zera `.dia`/`.zoom` para layout estático.

## Layout / ritmo espacial

- Unidades `vw`/`vh`/`dvh` para todo respiro vertical — ritmo proporcional à viewport, não `rem`.
- Grids assimétricos: `.proj-1{grid-template-columns:1fr 1.15fr}` vs `.proj-2{grid-template-columns:
  1.35fr 1fr}` — projetos alternam esquerda/direita e proporções.
- Off-grid overlaps: `.hero-title{margin-top:-36vh}` sobrepõe o título ao vídeo;
  `.filosofia-aside{margin-left:52%}` empurra texto para colunas invisíveis — não há grid de 12
  colunas visível, elementos vazam de propósito.

## Assets

3 fotos reais + 1 vídeo (`hero-light.mp4`) — sem geração via canvas/SVG para conteúdo. Único
elemento gerado por código: o arco solar SVG (Bézier quadrática, geometria pura). Grão de ruído
via `feTurbulence` data-URI. Gradientes de céu são CSS puro.

## O movimento distintivo

**A sombra sabe a hora**: um único `self.progress` de scroll dirige simultaneamente relógio
digital, temperatura de cor, texto do período do dia, posição do sol numa Bézier e crossfade
entre 3 fundos de céu — tudo sincronizado por uma única fonte de verdade, nada dessincronizado por
triggers separados.
