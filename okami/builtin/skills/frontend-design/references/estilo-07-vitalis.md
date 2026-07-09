# Estilo 07 — Vitalis (medicina da longevidade)

Clínica de longevidade e medicina preventiva — calma, quente, orgânica, humana; luxo silencioso de
spa médico, oposto do dark do estilo 06. Fonte: leitura linha a linha de `index.html` +
`css/style.css` + `js/main.js`.

## Token block (`:root`)

```css
:root {
  --cream: #F7F3EC;
  --cream-deep: #F0E9DC;
  --cream-card: #FBF8F2;
  --sage: #8A9B84;
  --sage-deep: #6E8068;
  --sage-tint: #E3E8DF;
  --terra: #C1704F;
  --terra-soft: #CE8A6C;
  --terra-tint: #F1E0D4;
  --ink: #2E2A26;
  --ink-60: #6E655A;
  --ink-40: #96897A;
  --line: rgba(46, 42, 38, 0.13);
  --shadow-cream: 0 24px 48px -20px rgba(103, 82, 55, 0.18);
  --shadow-cream-soft: 0 12px 32px -16px rgba(103, 82, 55, 0.14);
  --serif: "Fraunces", Georgia, serif;
  --sans: "Instrument Sans", "Helvetica Neue", sans-serif;
  --mono: "Spline Sans Mono", "SF Mono", monospace;
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
  --pad-x: clamp(1.25rem, 5vw, 5.5rem);
}
```

Paleta "orgânico-calma": creme quente + 2 acentos complementares — sálvia (calma/respiração/saúde)
e terracota (`.label`, `em`, CTAs). Nunca branco/preto puro — `--ink` é marrom-carvão. As sombras
(`--shadow-cream*`) são **tingidas de marrom**, não `rgba(0,0,0,...)` — cards/fotos parecem
"aconchegantes" em vez de flutuar sobre cinza técnico. `--ease-out` reutilizado como token único em
~15 lugares — uma curva de easing "orgânica" para toda a interface, sem GSAP.

## Fontes e uso

`Fraunces`/`Instrument Sans` (mesma dupla do Lumen), mas usando `font-variation-settings:"opsz"
NN` explicitamente (`h2{"opsz" 90}`, `.philosophy__text{"opsz" 60}`, `.decade h3{"opsz" 40}`,
`.footer__word{"opsz" 144}`) — controle fino do eixo óptico conforme o tamanho do texto (títulos
grandes usam opsz alto/mais contraste, textos médios usam opsz baixo/mais robusto). `--mono:
"Spline Sans Mono"` para metadado/números (CRM, telefone, badges).

## Técnica-assinatura: respiração guiada 4·4·6 — SVG morphing via rAF (zero libs)

**Não é `@keyframes` CSS** — é um blob SVG orgânico redesenhado a cada frame via
`requestAnimationFrame`, JS vanilla puro (CSS só cuida da transição de cor de preenchimento).

```html
<svg class="breath__svg" id="breath-svg" viewBox="0 0 400 400">
  <g id="breath-halo-g" opacity="0.35"><path id="breath-halo" fill="none" stroke="var(--sage)" stroke-width="1"/></g>
  <g id="breath-blob-g"><path id="breath-blob" fill="var(--sage)" fill-opacity="0.9"/></g>
</svg>
<div class="breath__guide">
  <p class="breath__word" id="breath-word">pronto?</p>
  <p class="breath__count mono" id="breath-count">4 · 4 · 6</p>
</div>
```

Timing exato como array de fases `[duração_s, rótulo, escalaInicial, escalaFinal]`:
```js
var PHASES = [
  [4, "inspire", 0.74, 1.0],
  [4, "segure",  1.0, 1.0],
  [6, "solte",   1.0, 0.74]
];
var IDLE_SCALE = 0.74;
```
Inspire (4s): escala 0.74→1.0. Segure (4s): constante (mas o wobble orgânico continua). Solte (6s):
1.0→0.74, maior duração — exalação mais longa, fisiologicamente correta.

Avanço de fase medido contra `performance.now()`, não `animation-duration` CSS:
```js
function draw(now) {
  var t = now / 1000;
  if (running) {
    var phase = PHASES[phaseIdx];
    var elapsed = t - phaseStart;
    if (elapsed >= phase[0]) {
      phaseStart += phase[0];
      phaseIdx = (phaseIdx + 1) % PHASES.length;
      if (phaseIdx === 0) { cycles++; cyclesEl.textContent = "ciclos completos: " + cycles; }
      phase = PHASES[phaseIdx];
      elapsed = t - phaseStart;
    }
    var p = Math.min(elapsed / phase[0], 1);
    currentScale = phase[2] + (phase[3] - phase[2]) * easeInOut(p);
    setWord(phase[1]);
    setCount(Math.max(1, Math.ceil(phase[0] - elapsed)) + "s");
  }
  var d = blobD(t, currentScale, wobbleScale);
  blobPath.setAttribute("d", d);
  haloPath.setAttribute("d", blobD(t * 0.7 + 40, Math.min(currentScale + 0.14, 1.18), wobbleScale));
  rafId = requestAnimationFrame(draw);
}
function easeInOut(t) { return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2; }
```

O blob é um polígono de 9 pontos, cada um com "wobble" senoidal individual (amplitude/frequência/
fase aleatórias fixadas por sessão), convertido em curva fechada via **Catmull-Rom → Bézier
cúbica**:
```js
var wob = [];
for (var i = 0; i < POINTS; i++) {
  wob.push({ amp: 0.032 + Math.random()*0.04, freq: 0.22 + Math.random()*0.3, phase: Math.random()*Math.PI*2 });
}
function blobD(time, scale, wobbleScale) {
  var pts = [];
  for (var i = 0; i < POINTS; i++) {
    var a = (i / POINTS) * Math.PI * 2 - Math.PI / 2;
    var w = wob[i];
    var r = BASE_R * scale * (1 + Math.sin(time * w.freq * Math.PI * 2 + w.phase) * w.amp * wobbleScale);
    pts.push([CX + Math.cos(a) * r, CY + Math.sin(a) * r]);
  }
  var d = "M" + pts[0][0].toFixed(2) + "," + pts[0][1].toFixed(2);
  for (var j = 0; j < POINTS; j++) {
    var p0 = pts[(j-1+POINTS)%POINTS], p1 = pts[j], p2 = pts[(j+1)%POINTS], p3 = pts[(j+2)%POINTS];
    var c1x = p1[0]+(p2[0]-p0[0])/6, c1y = p1[1]+(p2[1]-p0[1])/6;
    var c2x = p2[0]-(p3[0]-p1[0])/6, c2y = p2[1]-(p3[1]-p1[1])/6;
    d += "C"+c1x.toFixed(2)+","+c1y.toFixed(2)+" "+c2x.toFixed(2)+","+c2y.toFixed(2)+" "+p2[0].toFixed(2)+","+p2[1].toFixed(2);
  }
  return d + "Z";
}
```
Isso faz o círculo "respirar" organicamente em vez de escalar como `transform:scale()` mecânico —
a borda ondula continuamente mesmo em idle, e um segundo path "halo" desenhado com deslocamento de
tempo (`t*0.7+40`) e escala levemente maior cria um rastro/aura defasado atrás do blob principal.

Único CSS envolvido: transição de cor do preenchimento e fade da palavra-guia — a geometria em si
nunca usa `@keyframes`. Pausa em `visibilitychange` (reseta `phaseStart` ao retomar, evita "pular"
tempo); `prefers-reduced-motion` zera `wobbleScale` mas mantém 1 frame de desenho estático.

### Receita mínima para reproduzir

```js
var PHASES = [[4,'inspire',0.74,1],[4,'segure',1,1],[6,'solte',1,0.74]];
function easeInOut(t){ return t<.5 ? 2*t*t : 1-Math.pow(-2*t+2,2)/2; }
function blobD(time, scale){
  var pts=[];
  for(var i=0;i<9;i++){
    var a=(i/9)*Math.PI*2 - Math.PI/2;
    var r = R*scale*(1+Math.sin(time*FREQ[i]+PHASE[i])*AMP[i]);
    pts.push([CX+Math.cos(a)*r, CY+Math.sin(a)*r]);
  }
  // Catmull-Rom -> Bézier cúbica fechada (ver blobD() completo acima)
}
function draw(now){
  var t=now/1000, phase=PHASES[phaseIdx];
  var p = Math.min((t-phaseStart)/phase[0], 1);
  var scale = phase[2] + (phase[3]-phase[2])*easeInOut(p);
  path.setAttribute('d', blobD(t, scale));
  requestAnimationFrame(draw);
}
```
Chave: a escala vem de uma máquina de fases com tempos reais (o timer também alimenta o texto e o
contador de ciclos), e o "orgânico" vem do ruído senoidal por vértice — nunca `border-radius`
animado.

## Postura: sem 3D — o único "efeito grande" é 100% funcional, não decorativo

Vitalis não usa Three.js nem WebGL. A peça mais sofisticada é o blob de respiração — e ele é
literalmente experimentado pelo usuário (segue o próprio ritmo respiratório), não apenas visto.

## Motion geral: `IntersectionObserver` + CSS, zero libs

```css
.reveal {
  opacity: 0; transform: translateY(18px);
  transition: opacity 0.85s var(--ease-out), transform 0.85s var(--ease-out);
  transition-delay: calc(var(--i, 0) * 110ms);
}
.reveal.in { opacity: 1; transform: none; }
```
Stagger via `style="--i:N"` inline — 100% CSS custom property, sem JS calculando delays. Trata o
caso de "salto por âncora" (clique em link de nav): se o elemento já passou do topo sem nunca ter
interceptado, zera o delay e revela na hora (evita seção "vazia" por 1s+).

Nav "scrolled" sem `scroll` listener: `<div id="nav-sentinel">` de 1px + segundo
`IntersectionObserver` observando-o. Blobs decorativos de fundo usam `@keyframes` simples
(rotação+escala infinita, durações dessincronizadas 26/30/28s). Trilha de décadas com scroll
horizontal nativo (`scroll-snap-type:x proximity`) + drag-to-scroll via Pointer Events, sem lib.

## Layout

`--pad-x` único (mais contido/simétrico que o par assimétrico do Lumen — Vitalis é acolhedor,
Lumen é editorial). Grids alternantes com inversão de ordem (`.program--alt`). Cards com leve
rotação física (`rotate(1.5deg)`/`rotate(-1.2deg)`) — imitam fotos "coladas com fita". Sombras
tingidas de marrom em vez de cinza — assinatura "calor humano" que evita o clichê spa-médico
frio/azul-clínico.

## Assets

3 fotos reais, nenhuma gerada por código. Blobs decorativos de fundo são SVG estáticos desenhados
à mão, reciclados 3x com cores/tamanhos diferentes via `fill="currentColor"`. O blob de respiração
é o único elemento gerado dinamicamente em runtime.

## O movimento distintivo

O blob que respira: polígono orgânico com ruído senoidal por vértice, interpolado por
Catmull-Rom, escalado ao longo de fases de tempo reais (4s/4s/6s) via `requestAnimationFrame` —
nunca para completamente, e uma segunda camada (halo) segue defasada no tempo para dar
profundidade, tudo sem nenhuma lib de animação. Prova que se pode simular sofisticação de lib de
animação com ~80 linhas de JS vanilla.
