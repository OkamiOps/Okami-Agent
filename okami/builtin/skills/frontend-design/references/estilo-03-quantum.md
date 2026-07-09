# Estilo 03 — Coerência |ψ⟩ (computação quântica supercondutora)

Dark premium científico — "números medidos, não prometidos". Fonte: leitura linha a linha de
`index.html` + `css/style.css` + `js/main.js`.

## Token block (`:root`)

```css
:root{
  --bg:        #070B14;   /* navy-carvão, fundo geral */
  --surface:   #0C1322;
  --surface-2: #101A2E;
  --line:      rgba(148,178,215,.10);
  --line-soft: rgba(148,178,215,.06);
  --text:      #E8EEF7;
  --muted:     #8B99B0;
  --faint:     #55627A;
  --accent:    #6FDCCB;         /* ciano-menta, único acento */
  --accent-dim:rgba(111,220,203,.13);
  --accent-ink:#052B26;         /* texto sobre botão accent */
  --ease: cubic-bezier(.22,1,.36,1);
  --wrap: 1240px;
}
```

Cor "aço" `STEEL = 0x2a4468` só existe no JS (Three.js), não é var CSS. Fundo ambiente (não 3D):
`body::before` com 3 `radial-gradient` fixos (glows azul-aço + accent leve) — dá profundidade sem
canvas. Sistema de delay de reveal via `style="--d:.16s"` inline, não spacing tokenizado.

## Fontes e uso

`Space Grotesk` (400/500/600/700) para todo texto de UI/headings; `JetBrains Mono` (400/500/600 +
itálico) via `.mono` para tudo numérico/técnico (eyebrows, specs, dt/dd, terminal, labels de
circuito). Hierarquia por peso e cor, não só escala.

## Hero — o padrão-ouro de composição

O herói NÃO é o 3D — é a **coluna de texto editorial à esquerda**:

```css
.hero-inner{ position:relative; z-index:1; width:min(660px,92%); margin-left:clamp(20px,7.5vw,128px); }
.hero-title{ font-size:clamp(2.5rem,5vw,4.15rem); font-weight:600; letter-spacing:-.035em; line-height:1.04; }
```

Título grande em 2–3 linhas curtas, última linha na cor de acento ("A matéria mais fria / do
hemisfério sul / calcula aqui."), subtítulo com dado mono inline, dois CTAs, e `.hero-data` — grid
mono de 4 colunas (dt/dd) com números medidos reais (T₂ = 341 μs, fidelidade 99,71%, 11 mK).

O 3D (`.hero-visual`) é **ambiência silenciosa**:

```css
.hero-visual{ position:absolute; top:0; right:-9vw; bottom:0; width:60vw; z-index:0; pointer-events:none; }
.hero-visual canvas{ pointer-events:auto; cursor:grab; touch-action:pan-y; }
```

Sangra pela borda direita, fica ATRÁS do texto (`z-index:0` vs `.hero-inner{z-index:1}`),
mascarado (`mask-image: linear-gradient` horizontal some sob a coluna de texto) e SEM interação
forçada — só deriva automática lentíssima + parallax de mouse discreto. Container tem
`pointer-events:none`, só a área do canvas responde (permite drag pontual sem competir com o
texto). Mobile: cai para opacidade baixa como fundo, nunca protagonista.

**Erro comum: transformar o 3D no centro interativo — isso mata o tom editorial contido.** A
física é personagem coadjuvante; quem carrega o hero é a tipografia.

## Implementação 3D — esfera de Bloch (hero)

Three.js **r128** UMD via CDN, IIFE único com sub-cenas `blochScene()` (hero) e `latticeScene()`
(hardware). Guard de disponibilidade:

```js
function webglAvailable() {
  try {
    var c = document.createElement('canvas');
    return !!(window.WebGLRenderingContext &&
      (c.getContext('webgl') || c.getContext('experimental-webgl')));
  } catch (e) { return false; }
}
var threeOk = (typeof THREE !== 'undefined') && webglAvailable();
```

Setup:
```js
renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
renderer.setClearColor(BG, 0);           // fundo transparente
scene.fog = new THREE.FogExp2(BG, 0.055);
camera = new THREE.PerspectiveCamera(42, 1, 0.1, 60);
camera.position.set(0, 0.25, isMobile ? 9.6 : 7.6);
```
`PARTICLES = isMobile ? 700 : 2000` (redução no JS, não media query).

Tudo pendurado num `THREE.Group root`, raio de referência `R = 2.05`:
- Esfera wireframe: `SphereGeometry(R,28,18)` → `WireframeGeometry` → `LineSegments`,
  `LineBasicMaterial({ color: STEEL, opacity:.22 })`.
- Equador: `LineLoop` de 96 pontos (`circlePoints`), material accent opacity .4.
- Halo do equador: `TorusGeometry(R,0.028,8,96)`, `AdditiveBlending, depthWrite:false, opacity:.1`
  — brilho aditivo sem post-processing (a cena inteira usa `MeshBasicMaterial`/`LineBasicMaterial`,
  nenhuma `Light`).
- 3 anéis orbitais externos (`ringSpecs`), `LineLoop` de 128 pontos cada.
- Vetor de estado: `THREE.Line` de 2 pontos, `BufferAttribute` atualizado por frame.
- Ponta do vetor: esfera sólida pequena + esfera maior semitransparente aditiva atrás (glow sem
  post-processing).
- **Trilha do vetor** (`TRAIL_N=110` pontos, `vertexColors:true`, gradiente `f =
  pow(i/(N-1),1.6)*0.85`): a cada frame, `trailPos.copyWithin(0,3)` desloca o buffer inteiro
  (shift array) e escreve a posição nova no fim — rastro sem re-alocar.
- Labels `|0⟩`/`|1⟩`: sprites via `<canvas>` 2D → `CanvasTexture` → `SpriteMaterial`
  (`ctx.font='500 80px "JetBrains Mono"'` num canvas 256×128) — **texto 3D é sempre canvas→sprite,
  nunca geometria de texto real**.
- 2 nuvens de partículas (`Points`): `shell` (55%, colada à esfera, accent) e `belt` (45%,
  cinturão achatado, cor `0x9fb8dc`, contra-rotação), ambas `AdditiveBlending`.

### Interação — drag orbit com inércia + hover-heat

```js
// mousemove global → targetRX/RY (rotação-alvo), targetNX/NY (parallax-alvo)
// drag: pointerdown/move/up acumula dragRX/dragRY (dx*0.0055, dy*0.0035), clampDragX ±0.9 rad
// ao soltar, velX/velY decai *0.95/frame — inércia real, não snap-back
```

Hover-heat: raio da câmera testado contra esfera `R*1.15` (interseção analítica) ou `R*1.9` —
partículas próximas ao hover mudam de cor (accent → quase-branco) via lerp por-vértice,
`colAttr.needsUpdate=true` todo frame.

### Loop de animação

```js
root.rotation.y = curRY + t * 0.06 + dragRY;   // auto-rotação lenta + mouse + drag
root.rotation.x = curRX * 0.9 - 0.12 + dragRX;
var pulse = 1 + Math.sin(t * 1.15) * 0.02;     // "respiração" de escala
root.scale.setScalar(pulse);
shell.rotation.y = t * 0.11;
belt.rotation.y = -t * 0.07;                   // contra-rotação
// precessão do vetor: órbita cônica a colatitude fixa THETA=1.02
var phi = t * 0.5;
vx = sin(THETA)*cos(phi)*R; vy = cos(THETA)*R; vz = sin(THETA)*sin(phi)*R;
```
Todas transformações de mouse/parallax usam **lerp exponencial** (`cur += (target-cur)*k`,
k≈0.045–0.05) — nunca movimento direto.

**Pause/resume**: `IntersectionObserver` + `visibilitychange` cancelam o rAF fora da viewport.
**Fallback sem WebGL**: `no-webgl` class ativa "Bloch fake" só de `radial-gradient` + 2 `div` com
`border-radius:50%` + `transform:rotateX()`. **Reduced motion**: renderiza 1 frame estático, vetor
fixo em `rotation.set(-0.12,0.4,0)`, sem loop/listeners.

## Cena B — rede heavy-hexagonal (`#latticeHost`, seção Hardware)

`COLS=15, ROWS=7`, 127 "sítios" (referência real à topologia IBM heavy-hex), `Points` +
`LineSegments`. Câmera `PerspectiveCamera(34,1,.1,60)`, `position.set(0,3.4,6.0)` — vista de cima
em ângulo, "PCB view". **Onda de calibração** por frame (`paintWave(t)`): gaussiana `h =
exp(-e*e*2.4)` varre a rede radialmente, cor interpola `baseCol→hotCol`. Máscara CSS:
`mask-image:linear-gradient(90deg,transparent,#000 7%,#000 93%,transparent)`. Começa **parada**
até entrar na viewport.

## Motion (sem GSAP)

`IntersectionObserver` + CSS transitions em toda a página:

```css
.rv{ opacity:0; transform:translateY(26px); transition:opacity .9s var(--ease) var(--d,0s), transform .9s var(--ease) var(--d,0s); }
.rv.in{ opacity:1; transform:none; }
```
Delay por elemento via `style="--d:Xs"` inline — orquestração de cascata é estática no markup.

**Contadores numéricos**: easing cúbico custom `1-(1-p)^3`, 1500ms, formatação pt-BR manual.
**Diagrama de circuito SVG**: `stroke-dasharray:1; stroke-dashoffset:1` (com `pathLength="1"`) →
transição para 0, delay `--d` por wire/gate, dispara com `.draw` classe. **Barras de coerência**:
mesma técnica, `scaleX(0)→scaleX(var(--w))`. `prefers-reduced-motion:reduce` desliga tudo.

## Layout

`.wrap{max-width:1240px; padding-inline:clamp(20px,4vw,48px)}`. Linhas de 1px em vez de sombras
para separar; glass (`backdrop-filter:blur(14px)`) só em painéis específicos (circuito, terminal,
coerência), não em tudo. Assimetria: `.hw-flip` inverte ordem texto/imagem, grid `1fr 1.1fr`.

## Assets

Fotos reais (`quantum-chip.jpg`, `quantum-cryostat.jpg`) em "duplo bezel" CSS. Diagrama de
circuito: SVG hand-authored inline (H-gate, 3 CNOTs, barreira, medidores). Bloch fallback: puro
CSS. Toda cena 3D é geometria matemática pura, nenhum modelo `.glb`/`.obj`. Grão: SVG
`feTurbulence`, `opacity:.05`, `z-index:60`.

## O movimento distintivo

A esfera de Bloch interativa como hero-piece semi-narrativa: não é decoração ambiente genérica —
representa literalmente o estado quântico do produto, com vetor precessando em tempo real, trilha
que se dissolve, e "aquecimento por proximidade do cursor" nas partículas simulando "colapso na
medição" (hint de texto). Drag = orbitar o estado, hover = "medir"/aquecer — física-como-metáfora
de interação, não Three.js genérico de fundo.
