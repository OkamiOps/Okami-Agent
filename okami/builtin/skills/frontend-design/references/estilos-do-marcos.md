# Os 10 estilos do Marcos

Catálogo de referência dos 10 sites de demonstração que o dono (Marcos) construiu e do qual mais
se orgulha — "Dez sites. Dez mundos visuais.", como diz o índice dele. Não são templates para
copiar pixel a pixel: são **direções de arte completas e validadas** (cada uma passou por 3+ passes
de revisão visual real, não só "parece bom"). Use isto como fonte de vocabulário e de decisão
quando o pedido pedir uma dessas texturas — arquitetura, ciência/tech dark, saúde/longevidade,
marca real — em vez de reinventar do zero ou cair no genérico de IA.

Cada site nasceu de uma combinação de **arquétipo de composição** (`ui-brutalista-industrial`,
`ui-minimalista`, editorial de revista, spec-sheet técnica) com **assets autorais** gerados sob
direção de arte própria por projeto (nunca banco de imagem genérico) — paleta, luz e enquadramento
pensados para o layout que iriam habitar. É essa disciplina — decisão de composição ANTES de
qualquer cor — que este arquivo tenta transmitir, não só os hex.

---

## 01 — MONOLITH

**Essência**: estúdio de arquitetura brutalista tratado como pôster suíço industrial cruzado com a
fotografia P&B de Tadao Ando — voz de manifesto, frases curtas e duras.

- **Paleta**: papel `#ECEAE5`, tinta de carbono `#141412` (nunca preto puro), acento único
  vermelho-óxido `#9E3B26` (só em números de seção, fichas técnicas, setas).
- **Tipografia**: `Anton` condensada massiva no display (leading 0.83–0.92, sem itálico/peso
  alternativo — hierarquia só por escala e outline), `Archivo` no corpo, `JetBrains Mono` em
  labels/coordenadas.
- **Layout**: substrato claro de papel a página inteira; footer inverte para tinta (contracapa de
  documento); linhas divisórias de 1px em `rgba(20,20,18,.22)` no lugar de cards com sombra —
  linguagem de documento impresso, não de app.
- **Motion**: título gigante (~20vw) sobre janela de vídeo com `mix-blend-mode: difference`;
  galeria horizontal "sequestrada" (ScrollTrigger pin+scrub, painéis de largura variável,
  parallax interno); manifesto com split de palavras e reveal em scrub; marquee duplo em direções
  opostas (linha sólida + linha outline); grain de impressão via SVG `feTurbulence` fixo.
- **Movimento distintivo**: o título gigante em `difference` "tatuado" sobre o vídeo do hero — tinta
  sobre papel, claro sobre vídeo, sem nunca precisar de overlay escuro.
- **Quando usar**: portfólio/estúdio de arquitetura, marca que quer peso e autoridade "impressa",
  qualquer produto que precise de tom de manifesto (não de conversa).

## 02 — Lumen (Arquitetura da Luz)

**Essência**: firma de arquitetura serena e cara — revista impressa, o oposto deliberado do
brutalismo do 01. A página inteira é "um dia de luz" (manhã → meio-dia → poente).

- **Paleta**: branco-osso `#FAF8F4`, grafite quente `#2B2825`, acento dourado dessaturado
  `#A9885A`. Nunca `#FFF`/`#000` — tudo levemente aquecido, como papel.
- **Tipografia**: `Fraunces` variável (opsz 9–144) com itálicos dourados nos destaques,
  `Instrument Sans` na UI, `IBM Plex Mono` em legendas/coordenadas/Kelvins. Escala dramática: hero
  ~7.6vw contra corpo 16px.
- **Layout**: densidade visual baixíssima, modo galeria de arte; espaço negativo generoso; imagens
  deslocadas do eixo — o luxo é o silêncio, não o efeito.
- **Motion**: scrolltelling pinned de 380vh (relógio mono 06:30→19:45, três camadas de gradiente em
  crossfade, sol percorrendo arco SVG por bézier); zoom parallax sticky (moldura escala 1→2.24,
  imagem contra-escala 1.35→1); reveals com máscara (linha por linha subindo com stagger).
- **Movimento distintivo**: a página muda de temperatura de cor com o scroll — arquitetura contada
  pela luz do dia, não por texto.
- **Quando usar**: marca premium/editorial que vende calma e precisão (arquitetura, imobiliário de
  alto padrão, hospitalidade), qualquer superfície onde "menos e mais lento" é o argumento.

## 03 — Coerência |ψ⟩

**Essência**: computação quântica supercondutora brasileira, dark premium científico — "números
medidos, não prometidos".

- **Paleta**: navy-carvão `#070B14` (nunca `#000`), acento único ciano-teal dessaturado `#6FDCCB`
  — sem roxo neon, sem gradiente de texto, sombras tingidas do próprio fundo.
- **Tipografia**: `Space Grotesk` no display/UI, `JetBrains Mono` em todos os números/specs/fórmulas
  — hierarquia por peso e cor, não só escala.
- **Layout**: dark tech denso mas disciplinado; glassmorphism controlado; dados orgânicos e
  irregulares (T₂ = 341 μs, fidelidade 99,71%, 11 mK) em vez de round numbers de marketing.
- **Motion**: esfera de Bloch em Three.js (wireframe + anéis orbitais, vetor de estado precessando,
  2.000 partículas com additive blending), drag com inércia, parallax de mouse em 3 camadas,
  circuito GHZ desenhado por `stroke-dashoffset`.
- **Movimento distintivo**: hero 3D real e interativo (drag/orbit) em vez de vídeo — o produto é a
  física, então a física é o hero.
- **Quando usar**: deep tech / hardware / infra que precisa provar rigor técnico sem cair em "tech
  bro roxo-neon"; qualquer produto cujo diferencial seja precisão numérica.

## 04 — FORJA Compute

**Essência**: GPU cloud brasileira apresentada como cockpit industrial de telemetria tática —
densidade altíssima, tom de engenheiro, zero adjetivo de marketing.

- **Paleta**: carvão quente `#141210`, acento único âmbar industrial `#d97706`, verde utilitário
  `#a3b18a` só em pontos de status. Sem preto puro, **sem border-radius, sem box-shadow**.
- **Tipografia**: `JetBrains Mono` dominante (dados, tabelas, nav, títulos de seção, sempre
  `tabular-nums`) + `Archivo` variável black condensada só nos títulos monumentais.
- **Layout**: grid com `gap:1px` sobre fundo de linha (réguas matematicamente perfeitas);
  agrupamento por linhas de 1px em vez de cards com sombra; hero em moldura de câmera de
  segurança ("CAM_04 // SALA-B", REC piscando, timestamp real).
- **Motion**: telemetria viva com jitter orgânico (8 métricas, sparklines em block chars
  `▁▂▃▄▅▆▇`); cena 3D "pacote de GPU aberto" em wireframe âmbar tipo holograma CAD com HUD de tags
  ancoradas por `Vector3.project()`; varredura CRT em `repeating-linear-gradient` fixo; ticker
  marquee infinito.
- **Movimento distintivo**: telemetria que nunca para (métricas com jitter contínuo, sparklines
  vivas) — a página parece um painel operando de verdade, não uma screenshot estática.
- **Quando usar**: infra/cloud/ops, qualquer produto que venda performance/capacidade crua e precise
  de credibilidade de engenheiro (specs reais, não benefício vago).

## 05 — Kinetic Labs

**Essência**: estúdio de robótica criativa à la Teenage Engineering — fundo claro de papel quente,
energia lúdica mas técnica, deliberadamente o oposto de dark-tech.

- **Paleta**: papel quente `#F2EFE9`, tinta quase-preta `#1A1918`, acento único verde-ácido
  `#9BD34B`, lilás em dose homeopática `#E7E2F1` só como eco dos fundos das fotos.
- **Tipografia**: `Bricolage Grotesque` 700/800 no display (variável — permite a "onda de peso"),
  `Archivo` no texto, `DM Mono` em labels/números.
- **Layout**: cards de produto em pilha sticky escalonada, não grid uniforme; sombras sempre
  tingidas do papel ou do lilás da foto.
- **Motion**: headline cinética (split por letra, física de mola no hover — a letra empurra as
  vizinhas); sticky scroll stack com tilt 3D via CSS transform (lerp em rAF, sem WebGL, por
  decisão); canvas 2D com física própria (gravidade/colisão); botões magnéticos (`gsap.quickTo`);
  onda de peso animando `font-variation-settings "wght"` por letra, em CSS puro.
- **Movimento distintivo**: tipografia que reage ao toque como "um robô bem calibrado" — mola
  elástica por letra é a assinatura do site inteiro (headline e footer).
- **Quando usar**: produto físico/hardware com personalidade, marca que quer ser técnica sem ser
  fria — design industrial descontraído, não corporate.

## 06 — Hélice (Diagnósticos de Precisão)

**Essência**: laboratório de medicina genômica/oncologia de precisão — dark científico elegante
cuja cor vem da microscopia de fluorescência, não de "tech bro".

- **Paleta**: azul-petróleo quase preto `#06090F`, ciano de microscopia `#34D4CE`, magenta raro
  `#C55C97` — nunca gritante, nunca roxo-neon; os acentos vêm literalmente das imagens.
- **Tipografia**: `Archivo` em headlines assimétricas de tracking apertado, `Instrument Sans` no
  corpo, `JetBrains Mono` nos dados genômicos (a nomenclatura HGVS vira elemento gráfico).
- **Layout**: cards de exame com spotlight border seguindo o cursor; linha SVG de pipeline que se
  desenha; no mobile a hélice vira fundo sutil só do hero (opacity 0.22 + scrim) — legibilidade
  acima do efeito.
- **Motion**: dupla hélice de DNA em Three.js que acompanha o leitor nas primeiras seções e faz
  fade-out dirigido por scroll ao chegar nas células (devolve contraste); marquee genômico
  (sequências ACGT + nomenclatura HGVS real) com variantes pulsando; 150 partículas 3D com
  parallax oposto ao cursor.
- **Movimento distintivo**: o 3D "sai de cena na hora certa" — a hélice acompanha só onde ajuda e
  desaparece quando atrapalharia a leitura de dados.
- **Quando usar**: healthtech/biotech/diagnóstico, qualquer produto científico que precise parecer
  rigoroso e bonito ao mesmo tempo sem virar corporate genérico.

## 07 — Vitalis (Medicina da Longevidade)

**Essência**: clínica de longevidade e medicina preventiva — calma, quente, orgânica, humana; luxo
silencioso de spa médico, oposto ao dark do 06.

- **Paleta**: creme `#F7F3EC`, sálvia dessaturada `#8A9B84`, acento único terracota `#C1704F`,
  texto marrom-café `#2E2A26`; sombras tingidas de creme.
- **Tipografia**: `Fraunces` variável com itálicos expressivos no display, `Instrument Sans` no
  corpo, `Spline Sans Mono` em números/CRMs/legendas.
- **Layout**: assimetria e blobs orgânicos fazem o trabalho visual (nada grita); programas em
  zig-zag de 2 colunas — nunca 3 cards iguais; dados críveis no lugar de promessa vazia (63
  biomarcadores, −22%, HbA1c).
- **Motion**: exercício de respiração 4·4·6 **funcional de verdade** — blob SVG com 9 raios
  levemente irregulares redesenhado por rAF (Catmull-Rom → Bézier), escala segue as fases
  inspire/segure/solte com texto guiado e contador de ciclos; linha da vida 40→90+ com scroll
  nativo + snap, arrastável; zero bibliotecas JS externas — tudo canvas/SVG/CSS autoral.
- **Movimento distintivo**: a respiração guiada que efetivamente funciona (não é decoração) — o
  produto é experimentado, não só descrito.
- **Quando usar**: saúde/bem-estar/longevidade, qualquer produto que venda cuidado humano e precise
  fugir do jargão de coach e da promessa vazia.

## 08 — Agent Smith

**Essência**: landing definitiva de um produto de IA corporativo **real** (não é redesign
especulativo) — navy profundo, energia elétrica azul, identidade extraída do deploy oficial e
elevada a execução estado-da-arte.

- **Paleta**: fundo `#020817`, acento único `#5286f4` (verde só em LEDs de status), bordas
  `#263047` translúcidas.
- **Tipografia**: `Plus Jakarta Sans` com display font-light 300 + `JetBrains Mono` em stats,
  preços e labels técnicos; gradiente de texto white→white/50 **apenas** no headline.
- **Layout**: pills glassmorphism, bento de 4 pilares com micro-animações perpétuas; diagrama SVG
  de arquitetura com fluxos animados (argumento central do produto — "dados nunca saem da
  infraestrutura" — vira imagem, não só texto).
- **Motion**: canvas 2D de relâmpagos procedurais sobre o vídeo do hero (`mix-blend-mode: screen`);
  chat demo autônomo (digitação char-a-char, chip de fonte citada); constelação neural 3D (120 nós,
  ShaderMaterial próprio, raycast do mouse incha nós e acende arestas).
- **Movimento distintivo**: fidelidade estrita à identidade real da marca (cor, tipografia, tom de
  voz) mesmo sob execução muito mais ambiciosa — o upgrade nunca traiu o original.
- **Quando usar**: quando já existe uma marca real com identidade definida e o pedido é elevar a
  execução (não reinventar); IA corporativa/enterprise que precisa provar segurança de dados.

## 09 — Lionclaw — Edição Nº 001 (editorial)

**Essência**: conceito A para uma IDE de agentic coding — capa de revista de luxo em movimento,
leão em vídeo como protagonista absoluto, laranja usado com precisão cirúrgica.

- **Paleta**: papel `#FDFCFA`, tinta `#16130F`, laranja da marca `#E17200` só em detalhes de
  precisão (ponto final, números-stroke, orbes de botão, sublinhados, dois wipes).
- **Tipografia**: `Hanken Grotesk` em pesos extremos contrastados (200 itálico contra 800) +
  `IBM Plex Mono` em números/legendas de figura. Sem serif, por brief do cliente.
- **Layout**: página tratada como "Edição Nº 001" — nav com número de edição, kickers numerados,
  figuras com legenda ("fig. 01 — o olhar de quem revisa"), colofão no rodapé.
- **Motion**: leão sem retângulo de vídeo (`mix-blend-mode: multiply` + brightness + máscara radial
  feather — dissolve no papel); texto na frente E atrás do leão (duas camadas, oclusão via
  multiply + `clip-path`); text-mask por blend (`screen` + preto vira janela para o vídeo); wipes
  laranja em `scaleX` revelando conteúdo.
- **Movimento distintivo**: o leão "anda para dentro da página", atravessando a palavra headline com
  texto na frente e atrás dele — o vídeo nunca parece um `<video>` retangular colado.
- **Quando usar**: marca real com ativo visual forte (mascote, fundador, produto físico) que merece
  tratamento de capa de revista; lançamento/hero-first onde emoção > sistema.

## 10 — Lionclaw — Ficha Técnica Nº 10 (grid)

**Essência**: conceito B para a mesma marca — deliberadamente o oposto do 09: International
Typographic Style encontrando spec-sheet de software. Racional, seco, sistemático.

- **Paleta**: fundo `#FFFFFF` puro (obrigatório do cliente) com superfície quente `#FAFAF8`, tinta
  off-black `#141518`, laranja `#E17200` estritamente funcional (números de seção, status RUNNING,
  nós de diagrama, botão primário).
- **Tipografia**: `Hanken Grotesk` (300–800) no display e corpo + `JetBrains Mono` em todos os
  labels técnicos, tabelas e changelog.
- **Layout**: grid de 12 colunas **visível** (réguas de 1px fixas na viewport, atravessando todas as
  seções, inclusive por cima dos vídeos), crosshairs nos cruzamentos, número de página por seção
  (`p. 02 / 07 · v2.4.1`); assimetria dentro da ordem (hero 7+5, arquitetura 5+7, spec-sheet 3+9).
- **Motion**: hero zoom parallax (pin+scrub, janela de vídeo escala de 5 colunas até ~94vw/88vh);
  diagrama de arquitetura de agentes em SVG hand-coded desenhado por `stroke-dashoffset` no scroll;
  fundo de papel milimetrado (`repeating-linear-gradient`).
  - O leão vive **dentro** de "viewports" retangulares do grid, como instrumentação observando um
    animal (SPEC 01 — LEO PANTHERA / RUNTIME, HUD com resolução e ponto REC).
- **Movimento distintivo**: as réguas do grid ficam por cima de TUDO, inclusive vídeo, o tempo todo
  — o grid não é fundo decorativo, é a lente através da qual a página inteira é lida.
- **Quando usar**: mesma marca do 09, mas quando o pedido pede rigor/spec/documentação técnica em
  vez de emoção; produto de dev tools, plataforma técnica, qualquer coisa que precise parecer
  "engenharia", não "revista".

---

## Como reproduzir — técnicas comuns aos 10

Não existe uma folha de CSS compartilhada entre os sites (cada `NN-slug/css/style.css` é
autocontido) — o que se repete é a **disciplina**, não o arquivo. Ao construir um site novo nessa
linhagem, reaplique isto:

1. **Direção antes de cor.** Cada site parte de um arquétipo de composição escolhido antes de
   qualquer hex (`ui-brutalista-industrial` nos sites 01/04, `ui-minimalista` no 02, editorial de
   revista no 09, spec-sheet no 10). Diga em uma frase que mundo é esse antes de tocar em CSS — ver
   seção 1 do `SKILL.md` principal.
2. **CSS custom properties no `:root`**, sempre: fundo, superfície/painel, tinta/texto principal,
   texto secundário/mudo, borda/linha, **um** acento primário. Nunca `#000`/`#FFF` puros exceto
   quando a marca exige (caso do 10) — prefira tons levemente quentes ou frios de propósito
   (`#141412`, `#ECEAE5`, `#070B14`...).
3. **Um acento só, com papel definido.** Em todos os 10 sites há exatamente UM acento de cor (às
   vezes dois em doses desiguais, como Hélice ciano+magenta-raro) usado com função clara — nunca
   arco-íris, nunca gradiente azul→roxo genérico. A cor do acento geralmente vem do produto/imagem
   (ciano/magenta da microscopia real, verde-ácido de robótica, laranja da marca Lionclaw), não de
   "o que fica bonito".
4. **Tipografia: 2-3 famílias com papel fixo.** Um display de personalidade (serif variável tipo
   `Fraunces`, condensada tipo `Anton`, grotesca de peso extremo tipo `Hanken Grotesk`), uma sans
   neutra pro corpo (`Archivo`, `Instrument Sans`), e **sempre** um mono técnico em dados/labels/
   coordenadas (`JetBrains Mono`, `IBM Plex Mono`, `DM Mono`, `Spline Sans Mono`) — o mono é o que
   dá credibilidade "medida, não prometida" em todos os 10.
5. **Linhas de 1px em vez de cards com sombra.** Documento/spec-sheet/grid em vez de "app de
   cartões" — é o tell visual mais recorrente do conjunto (01, 04, 10 explicitamente; os demais
   evitam sombra decorativa também).
6. **Motion tem sempre 3 garantias:**
   - **Fallback incondicional**: se o JS/WebGL/CDN falhar, o conteúdo aparece 100% legível (timers
     de segurança de ~1.2–3s que revelam tudo se o scroll nunca disparar os reveals).
   - **`prefers-reduced-motion` desliga tudo** — o estado final vira o default, sem depender de JS.
   - **Pausa fora do viewport** (`document.hidden`, `IntersectionObserver`) e `DPR ≤ 2` em cenas
     3D — custo de bateria/CPU não é opcional.
7. **GSAP + ScrollTrigger via build UMD de CDN** (cdnjs) funciona em `file://` sem servidor/build —
   é assim que todos os sites rodam local. Three.js `r128` UMD para as cenas 3D (esfera de Bloch,
   dupla hélice, pacote de GPU, constelação neural) — sempre com fallback CSS/SVG se WebGL faltar.
8. **Reveal padrão**: `IntersectionObserver` com stagger por variável CSS, texto em máscara
   (`overflow:hidden` + linha subindo), nunca `opacity:0` que pode ficar "fantasma" — sempre com a
   rede de segurança do item 6.
9. **Assets autorais, nunca banco de imagem genérico.** Cada site define paleta/luz/enquadramento
   da própria imagem antes de gerar/escolher qualquer asset — a imagem serve a composição, não o
   contrário. Ao criar um site novo sem gerador de imagem disponível, ainda assim escolha
   deliberadamente o mood da imagem/vídeo placeholder em vez de usar o primeiro stock genérico.
10. **Densidade e tom seguem o domínio**: arquitetura/saúde-longevidade → generoso, lento, quente;
    tech/infra/ciência → denso, mono, frio (mas nunca roxo-neon); marca real → fidelidade estrita
    à identidade existente antes de qualquer ambição visual nova.

Fonte primária: `/Users/marcos/Downloads/10 Sites — Demo de Web Design/GUIA.html` (o guia de
bastidores do próprio dono, com paleta/tipografia/técnica/decisões e histórico de iteração de cada
site) e os 10 `index.html` + `css/style.css` de cada pasta. Abra o guia se precisar do detalhe
exato de uma técnica (ex.: como o blend do leão foi calibrado, como o safety-net do reveal foi
corrigido) além do que está resumido aqui.
