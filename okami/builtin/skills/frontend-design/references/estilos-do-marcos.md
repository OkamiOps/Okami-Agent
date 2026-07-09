# Os 10 estilos do Marcos — índice

Catálogo dos 10 sites de demonstração que o dono (Marcos) construiu e do qual mais se orgulha —
"Dez sites. Dez mundos visuais." Não são templates para copiar pixel a pixel: são **direções de
arte completas e validadas**, extraídas linha a linha do HTML/CSS/JS real de cada site (fonte:
`/Users/marcos/Downloads/10 Sites — Demo de Web Design/`).

**Antes de construir**: carregue o arquivo de detalhe do estilo escolhido com
`use_skill(path="${OKAMI_SKILL_DIR}/references/estilo-NN-nome.md")` — cada um tem o `:root` de
cores exato, a técnica-assinatura em código real (Three.js/GSAP/CSS puro) e a postura de
hero/3D daquele site. Este índice é só para escolher qual carregar. Para as técnicas que se
repetem nos 10 (sistema de token CSS, dicotomia protagonista-vs-ambiente do 3D, fallback,
`prefers-reduced-motion`), veja `references/tecnicas-transversais.md`.

---

| # | Estilo | Essência | Paleta + fontes | Movimento distintivo | Postura 3D/motion | Quando usar | Detalhe |
|---|---|---|---|---|---|---|---|
| 01 | **MONOLITH** | Arquitetura brutalista, pôster suíço industrial P&B | papel `#ECEAE5` / tinta `#141412` / óxido `#9E3B26` · Anton + Archivo + JetBrains Mono | título gigante em `mix-blend-mode:difference` sobre vídeo P&B | ambiente — o blend mode é a "física", sem 3D real | portfólio/estúdio de arquitetura, tom de manifesto | `estilo-01-monolith.md` |
| 02 | **Lumen** | Firma de arquitetura serena, revista impressa, "um dia de luz" | osso `#FAF8F4` / grafite `#2B2825` / dourado `#A9885A` · Fraunces + Instrument Sans + IBM Plex Mono | 1 scroll-progress dirige céu+relógio+sol+texto simultaneamente (GSAP scrub) | sem 3D — scrollytelling 2D via crossfade de camadas | marca premium/editorial, "menos e mais lento" | `estilo-02-lumen.md` |
| 03 | **Coerência (Quantum)** | Computação quântica dark científico, "números medidos" | navy `#070B14` / ciano-teal `#6FDCCB` · Space Grotesk + JetBrains Mono | esfera de Bloch Three.js interativa (drag+inércia+hover-heat) atrás do texto | **protagonista contido** — 3D real mas `absolute`, metade da tela, atrás do texto, mask nas bordas | deep tech/hardware que precisa provar rigor sem "tech bro roxo" | `estilo-03-quantum.md` |
| 04 | **FORJA Compute** | GPU cloud, cockpit industrial de telemetria | carvão `#141210` / âmbar `#d97706` · JetBrains Mono (corpo inteiro) + Archivo condensada | inspeção 3D wireframe do die (drag/orbit) com HUD ancorado por `Vector3.project()` | **protagonista explícito** — 3D é hero de seção dedicada, interativo, zero border-radius | infra/cloud/ops, credibilidade de engenheiro | `estilo-04-foundry.md` |
| 05 | **Kinetic Labs** | Robótica lúdica à la Teenage Engineering | papel `#F2EFE9` / verde-ácido `#9BD34B` · Bricolage Grotesque + Archivo + DM Mono | tipografia letra-a-letra com física de mola de 2 fases (`power2.out` + `elastic.out`) | sem 3D real — tilt CSS (lerp em rAF) + canvas 2D de física | produto físico/hardware com personalidade lúdica | `estilo-05-kinetic.md` |
| 06 | **Hélice (Diagnósticos)** | Medicina genômica/oncologia, dark científico de microscopia | petróleo `#06090F` / ciano `#34D4CE` + magenta `#C55C97` · Archivo + Instrument Sans + JetBrains Mono | dupla hélice Three.js **scroll-driven** (rotação/posição/câmera = função do scroll), fixed atrás de várias seções | **ambiente scroll-driven** — não interativo por clique, só parallax de mouse + hover-zoom | healthtech/biotech, rigoroso e bonito | `estilo-06-helix.md` |
| 07 | **Vitalis** | Clínica de longevidade, calma orgânica, spa médico | creme `#F7F3EC` / sálvia `#8A9B84` / terracota `#C1704F` · Fraunces + Instrument Sans + Spline Sans Mono | blob SVG que respira de verdade (ciclo 4·4·6, Catmull-Rom→Bézier via rAF, zero libs) | sem 3D — geometria 2D procedural funcional, não decorativa | saúde/bem-estar, foge do jargão de coach | `estilo-07-vitalis.md` |
| 08 | **Agent Smith** | IA corporativa real, navy + azul elétrico, marca existente elevada | `#020817` / azul `#5286f4` · Plus Jakarta Sans (300) + JetBrains Mono | constelação neural 3D (120 nós, shaders GLSL custom, `AdditiveBlending`) atrás de diagrama SVG | **ambiente puro** — `pointer-events:none`, opacity .72, mask radial, nunca centro da composição | marca real com identidade definida, IA enterprise/segurança | `estilo-08-agent-smith.md` |
| 09 | **Lionclaw — Edição Nº 001** | IDE agentic coding, capa de revista de luxo | papel `#FDFCFA` / tinta `#16130F` / laranja `#E17200` · Hanken Grotesk (itálico 200) + IBM Plex Mono | leão em vídeo "sanduichado" entre 2 cópias do texto (z-index + `clip-path` + `mix-blend-mode:multiply`) | vídeo real, não 3D — protagonista emocional da composição | marca com ativo visual forte, hero-first, emoção > sistema | `estilo-09-lionclaw-editorial.md` |
| 10 | **Lionclaw — Ficha Técnica Nº 10** | Mesma marca, spec-sheet suíça, grid exposto | `#FFFFFF` puro / superfície `#FAFAF8` / laranja `#E17200` (mesmo hex do 09) · Hanken Grotesk (sem itálico) + JetBrains Mono | 12 réguas de grid `position:fixed` por cima de TUDO, inclusive vídeo | vídeo real dentro de "viewports" do grid, zoom-pin no scroll | mesma marca, mas rigor/spec/documentação em vez de emoção | `estilo-10-lionclaw-grid.md` |

## A lição de postura 3D/motion (não default para "loud")

Os 10 sites dividem seus efeitos ricos (3D, blobs, telas cheias de vídeo) em duas posturas
deliberadas — **escolha uma por site, nunca misture sem motivo**:

- **Protagonista/interativo** (03-quantum, 04-foundry): o efeito é hero de uma seção dedicada,
  aceita `pointerdown`/drag/orbit, tem hint de interação explícito ("arraste para orbitar"). Usa
  quando o efeito **é** o produto (estado quântico, hardware físico).
- **Ambiente/background** (06-helix, 08-agent-smith): `pointer-events:none`, `mask-image` nas
  bordas, opacidade reduzida, nunca captura clique — só deriva automática + parallax de mouse
  discreto. Usa quando o efeito **sustenta** o argumento sem competir com o texto/copy.

Errar essa escolha é o erro mais comum ao reproduzir estes estilos: transformar um 3D que devia
ser ambiente (ex.: Coerência/Quantum) no centro interativo mata o tom editorial contido do site.
Ver `tecnicas-transversais.md` para a dicotomia completa com os dois padrões de código.

## Fonte primária

`/Users/marcos/Downloads/10 Sites — Demo de Web Design/GUIA.html` (guia de bastidores do dono) e
os 10 `index.html` + `css/style.css` + `js/main.js` de cada pasta. Os arquivos de detalhe deste
diretório (`estilo-NN-*.md`) já extraem o essencial linha a linha — só abra o GUIA/fonte original
se precisar de um detalhe além do que está nos arquivos de detalhe.
