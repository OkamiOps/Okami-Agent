# Técnicas transversais aos 10 estilos do Marcos

Não existe uma folha de CSS compartilhada entre os 10 sites (cada `NN-slug/css/style.css` é
autocontido) — o que se repete é a **disciplina**, não o arquivo. Isto é o "como reproduzir"
comum, extraído de ler os 10 `index.html`/`css/style.css`/`js/main.js` linha a linha. Use isto
DEPOIS de escolher o estilo em `estilos-do-marcos.md` e carregar o detalhe de `estilo-NN-*.md` —
aqui estão os padrões que atravessam todos eles.

## 1. Direção antes de cor

Cada site parte de um arquétipo de composição escolhido antes de qualquer hex
(`ui-brutalista-industrial` nos sites 01/04, `ui-minimalista` no 02, editorial de revista no 09,
spec-sheet no 10). Diga em uma frase que mundo é esse antes de tocar em CSS — ver seção 1 do
`SKILL.md` principal.

## 2. Sistema de token CSS: um único `:root` por site

Todos os 10 sites usam um único bloco `:root` com: fundo, superfície/painel, tinta/texto
principal, texto secundário/mudo, borda/linha, e **um** acento primário. Nunca `#000`/`#FFF` puros
exceto quando a marca exige (caso do estilo 10) — prefira tons levemente quentes ou frios de
propósito (`#141412`, `#ECEAE5`, `#070B14`...). Alguns sites adicionam uma segunda camada de
opacidade de linha (`--line`/`--line-2`, estilo 06) para hierarquia de borda fraca-vs-enfatizada,
ou um token de easing único reutilizado em toda a interface (`--ease-out`, estilos 07/09/10).
Delays de reveal são quase sempre inline via `style="--d:.16s"`/`style="--i:2"` consumidos por uma
única regra `transition-delay:calc(var(--i,0)*Nms)` — não um sistema de spacing tokenizado
completo, é ad hoc por seção com `clamp()`.

## 3. Um acento só, com papel definido

Em todos os 10 sites há exatamente UM acento de cor (às vezes dois em doses desiguais, como
estilo 06 ciano+magenta, ou estilo 08 que usa verde só em LEDs de status) usado com função clara —
nunca arco-íris, nunca gradiente azul→roxo genérico. A cor do acento geralmente vem do
produto/imagem (ciano/magenta da microscopia real, verde-ácido de robótica, laranja da marca
Lionclaw), não de "o que fica bonito".

## 4. Tipografia: 2-3 famílias com papel fixo

Um display de personalidade (serif variável tipo `Fraunces`, condensada tipo `Anton`, grotesca de
peso extremo tipo `Hanken Grotesk`), uma sans neutra pro corpo (`Archivo`, `Instrument Sans`), e
**sempre** um mono técnico em dados/labels/coordenadas (`JetBrains Mono`, `IBM Plex Mono`,
`DM Mono`, `Spline Sans Mono`) — o mono é o que dá credibilidade "medida, não prometida" em todos
os 10. Fontes variáveis (`font-variation-settings`) aparecem em dois papéis: eixo de peso `wght`
para "respiração"/personalidade (estilo 05, `kin-weight` contínuo) e eixo óptico `opsz` para
ajuste fino conforme o tamanho do texto (estilo 07, títulos grandes = opsz alto).

## 5. Linhas de 1px em vez de cards com sombra

Documento/spec-sheet/grid em vez de "app de cartões" — é o tell visual mais recorrente do conjunto
(01, 04, 10 explicitamente; os demais evitam sombra decorativa também, ou usam sombra **tingida**
da própria paleta em vez de cinza — estilo 07 `--shadow-cream`, tingida de marrom).

## 6. A dicotomia protagonista-vs-ambiente do 3D/motion grande

Esta é a lição mais fácil de errar ao reproduzir estes estilos: **escolha uma postura por site,
nunca misture sem motivo**.

**Protagonista/interativo** (estilos 03, 04): o efeito é hero de uma seção dedicada, aceita
`pointerdown`/drag/orbit com inércia real, tem hint de interação explícito no texto ("arraste a
esfera", "arraste para orbitar"). Padrão de código:
```css
.hero-visual{ position:absolute; /* metade da tela, não full-bleed */ z-index:0; pointer-events:none; }
.hero-visual canvas{ pointer-events:auto; cursor:grab; }  /* só o canvas captura, o container não */
```
```js
// drag acumula rotação com inércia real (decai por atrito, nunca snap-back)
vel *= 0.95; // ou 0.95-ish por frame após soltar o ponteiro
rotY += vel;
```
Use quando o efeito **é** o produto (estado quântico em 03, hardware físico em 04) — a interação
prova algo sobre o que está sendo vendido.

**Ambiente/background** (estilos 06, 08): `pointer-events:none` no elemento inteiro (não só no
container), opacidade reduzida (.55–.8), `mask-image` radial ou linear dissolvendo bordas, nunca
captura clique — só deriva automática + parallax de mouse discreto ou scroll-progress. Padrão de
código:
```css
#efeito-canvas{
  position:absolute; inset:0; z-index:0; pointer-events:none; opacity:0.72;
  mask-image: radial-gradient(85% 82% at 58% 46%, #000 30%, transparent 98%);
}
```
Use quando o efeito **sustenta** o argumento sem competir com o texto — atmosfera de confiança
(estilo 08, rede neural atrás do diagrama de segurança) ou acompanhamento narrativo que sai de
cena na hora certa (estilo 06, hélice que desaparece perto do vídeo de células).

**Erro mais comum ao reproduzir**: transformar um 3D que devia ser ambiente no centro interativo —
isso mata o tom editorial contido do estilo 03 se aplicado errado, por exemplo. Decida a postura
ANTES de escrever o setup do Three.js, junto com a decisão de composição do passo 1.

## 7. Um único progress-scrub dirigindo N sistemas visuais (padrão Lumen)

A técnica mais sofisticada de scroll-driven storytelling do conjunto (estilo 02): um único
`self.progress` (0→1) de um `ScrollTrigger` com `scrub` numérico alimenta, dentro de um único
`onUpdate`, vários sistemas visuais em paralelo (céu, relógio, texto, posição do sol via Bézier).
```js
scrollTrigger:{ trigger:".dia", start:"top top", end:"bottom bottom", scrub:0.5,
  onUpdate(self){ /* self.progress é a ÚNICA fonte de verdade — deriva tudo daqui */ } }
```
Regra: nunca sincronize os sistemas por triggers separados — um número, N efeitos, sempre
coerentes entre si. `scrub` numérico (não `true` puro) dá "atraso elástico"; `ease:"none"` em
tudo que é scrubado (nunca easing não-linear competindo com o controle do usuário).

## 8. Spring physics por letra (padrão Kinetic)

Timeline GSAP de 2 fases para simular física de mola real em hover de tipografia letra-a-letra
(estilo 05): impacto rápido (`power2.out`, ~0.16s) seguido de retorno elástico com overshoot
(`elastic.out(amplitude, period)`, ~1.1s). Propague o efeito às letras vizinhas com deslocamento
menor e rotação invertida/atenuada para simular "corrente mecânica":
```js
function pop(el, dy, rot, scale) {
  gsap.killTweensOf(el);   // SEMPRE, antes de disparar um novo pop — evita tremedeira em hover rápido
  gsap.timeline()
    .to(el, { y: dy, rotation: rot, scale, duration: 0.16, ease: 'power2.out' })
    .to(el, { y: 0, rotation: 0, scale: 1, duration: 1.1, ease: 'elastic.out(1.1,0.32)' });
}
```

## 9. `mix-blend-mode: difference` arithmetic (padrão Monolith)

`difference` calcula `|cor-elemento - cor-fundo|` pixel a pixel — texto claro sobre fundo claro
some (~0), mas onde cruza uma mídia P&B por baixo, o contraste aparece automaticamente sem código
de leitura de luminância:
```css
.title{ mix-blend-mode: difference; color:#eee; }  /* precisa de background OPACO conhecido no ancestral */
```
Pré-requisito inegociável: o elemento por trás precisa de `background` sólido e conhecido — senão
o `difference` calcula contra o branco/transparente do navegador e não "lê" a mídia. O mesmo
princípio serve para nav sempre-legível (`.nav{mix-blend-mode:difference; pointer-events:none}`
+ `.nav > *{pointer-events:auto}`).

## 10. Grid de 12 colunas visível compartilhando métricas com o container real (padrão Lionclaw-grid)

`<div>` `position:fixed` com N filhos vazios de `border-left`, usando o MESMO `max-width` e
`padding`/`gutter` do `.container` real — assim todo elemento posicionado por `grid-column:X/Y`
bate exatamente nas réguas visíveis (não é decoração solta, é prova visual da grade):
```css
.grid-lines{ position:fixed; inset:0; pointer-events:none; z-index:40; }
.grid-lines-inner{ max-width:var(--maxw); padding:0 var(--gutter); display:grid; grid-template-columns:repeat(12,1fr); }
.grid-lines-inner i{ border-left:1px solid var(--line-soft); } /* opacidade baixa, ~5% */
```

## 11. `requestAnimationFrame` como motor de física sem libs (padrão Vitalis)

Riqueza visual sem dependências: um laço `rAF` funcionando como motor de física simples (fase →
escala → geometria), com geometria orgânica gerada por ruído senoidal por vértice interpolado via
Catmull-Rom → Bézier cúbica fechada — não `@keyframes` CSS, porque o timer também precisa
alimentar texto/contador dinâmicos. Use quando o efeito precisa ser **funcional** (guiar uma
respiração real), não só decorativo.

## 12. Três garantias obrigatórias de motion

Todo motion nos 10 sites — 3D, GSAP, CSS puro — tem sempre:

1. **Fallback incondicional**: se JS/WebGL/CDN falhar, o conteúdo aparece 100% legível. Timer de
   segurança (~1.2–3s) que força tudo visível se o scroll/observer nunca disparar os reveals:
   ```js
   setTimeout(function(){ /* força .in em tudo, progress(1) em timelines pendentes */ }, 2600);
   ```
2. **`prefers-reduced-motion` desliga tudo** — vira o estado final default, sem depender de JS
   continuar rodando. Cenas 3D renderizam 1 frame estático em vez de loop (exceção documentada:
   estilo 06 mantém a rotação por scroll mesmo em reduced-motion, só corta o parallax de mouse).
3. **Pausa fora do viewport** (`IntersectionObserver`) e em aba oculta (`document.hidden`/
   `visibilitychange`), `DPR ≤ 2` em cenas 3D — custo de bateria/CPU não é opcional.

## 13. Three.js r128 UMD + convenção de fallback CSS/SVG

Todos os sites com 3D usam **Three.js r128** (API pré-`ColorManagement`) via CDN UMD clássico —
nunca ES modules, nunca bundler:
```html
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script src="js/main.js"></script>
```
Guard obrigatório antes de qualquer setup:
```js
function webglAvailable() {
  try {
    var c = document.createElement('canvas');
    return !!(window.WebGLRenderingContext && (c.getContext('webgl') || c.getContext('experimental-webgl')));
  } catch (e) { return false; }
}
```
Fallback sem WebGL varia por site mas é sempre visual, nunca um erro em branco: SVG técnico já
embutido no HTML (estilo 04), CSS puro com gradientes/anéis rotacionados (estilo 03), imagem
estática com máscara (estilo 06), ou remoção silenciosa do canvas quando o efeito é puramente
atmosférico (estilo 08). Toda geometria 3D é procedural (esferas, cilindros, grids matemáticos) —
nenhum modelo `.glb`/`.obj` importado em nenhum dos 10 sites. Texto dentro de cena 3D é sempre
canvas 2D → `CanvasTexture` → sprite, nunca geometria de texto real.

## 14. GSAP + Three.js: DECOUPLING obrigatório, nunca a mesma timeline

Quando um site usa GSAP/ScrollTrigger E Three.js juntos (estilo 08), as duas engines **nunca
compartilham timeline**: GSAP/ScrollTrigger controla exclusivamente a camada DOM (headings, cards,
diagrama SVG) entrando com fade+translate; o Three.js roda **independentemente** num loop `rAF`
próprio, controlado por `IntersectionObserver` (não por `ScrollTrigger`), sincronizado no máximo a
parallax de mouse ou a um progress de scroll lido manualmente (estilo 06) — nunca dentro de uma
`gsap.timeline()` compartilhada com tweens de DOM. Motivo prático: a cena 3D tem seu próprio ciclo
de vida (pause/resume por visibilidade) que não deve depender do ScrollTrigger da página.

## 15. Reveal padrão: `IntersectionObserver` + máscara, nunca `opacity:0` "fantasma"

```css
.rv{ opacity:0; transform:translateY(24px); transition:opacity .9s var(--ease) var(--d,0s), transform .9s var(--ease) var(--d,0s); }
.rv.in{ opacity:1; transform:none; }
```
```js
var io = new IntersectionObserver(function(entries){
  entries.forEach(function(entry){
    if (!entry.isIntersecting) return;
    entry.target.classList.add("in");
    io.unobserve(entry.target);   // dispara uma vez só
  });
}, { threshold: 0.1, rootMargin: "0px 0px -6% 0px" });
```
Delay individual por elemento via `style="--d:Xs"`/`style="--i:N"` inline — a orquestração de
"cascata" é estática no markup, não calculada em JS. Variações documentadas: `filter:blur(6px)`
extra no reveal (estilo 06), tratamento do caso "salto por âncora" que zera o delay se o elemento
já passou do topo sem nunca ter interceptado (estilo 07) — sempre com a rede de segurança do
item 12.

## 16. Assets autorais, nunca banco de imagem genérico

Cada site define paleta/luz/enquadramento da própria imagem antes de gerar/escolher qualquer
asset — a imagem serve a composição, não o contrário. Ao criar um site novo sem gerador de imagem
disponível, ainda assim escolha deliberadamente o mood da imagem/vídeo placeholder em vez de usar
o primeiro stock genérico. SVGs de diagrama técnico são quase sempre hand-authored inline no HTML
(não gerados por lib), com `stroke-dasharray`/`stroke-dashoffset` = `getTotalLength()` para o
efeito de "desenhar" a linha no scroll ou ao entrar em viewport.

## 17. Densidade e tom seguem o domínio

Arquitetura/saúde-longevidade → generoso, lento, quente (estilos 01/02/07). Tech/infra/ciência →
denso, mono, frio, mas nunca roxo-neon (estilos 03/04/06/08). Marca real → fidelidade estrita à
identidade existente antes de qualquer ambição visual nova (estilos 08/09/10).
