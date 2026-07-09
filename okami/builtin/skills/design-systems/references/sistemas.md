# Catálogo completo de sistemas de design

Cada entrada resume a assinatura visual do sistema em 2-4 linhas: paleta, tipografia, spacing/sombra
e o "sentimento" que ele passa. Fonte original costuma ser proprietária — a coluna **fonte** já traz
o substituto do Google Fonts que preserva o caráter (peso, tracking) sem depender de licença.

Origem: adaptado do catálogo `popular-web-designs` do Hermes Agent (54 sistemas reais, fontes
VoltAgent/awesome-design-md), reescrito e condensado em pt-BR para uso rápido durante geração de UI.

## IA & Machine Learning

- **Claude / Anthropic** — terracota quente como acento, layout editorial limpo, muito espaço em
  branco. Tipografia serve o texto, não compete com ele — sensação de calma e cuidado.
  Fonte: `Inter` / mono `JetBrains Mono`.
- **Cohere** — gradientes vibrantes, dashboard denso em dado. Paleta mais ousada que a média do
  setor, com cartões coloridos por categoria.
- **ElevenLabs** — UI escura cinematográfica, estética de waveform de áudio, muito contraste.
  Fonte: sans geométrica + mono técnico.
- **Mistral AI** — minimalismo "engenharia francesa", tom roxo, tipografia enxuta e precisa.
- **Ollama** — terminal-first, monocromático, quase sem cor — o oposto de "design chamativo".
  Fonte: mono em quase tudo.
- **OpenCode AI** — tema escuro centrado no dev, monospace em praticamente toda a interface.
- **Replicate** — canvas branco limpo, code-forward (blocos de código como elemento central).
- **RunwayML** — UI escura cinematográfica, layout rico em mídia (vídeo/imagem em destaque).
- **Together AI** — técnico, estilo "blueprint" (grid, linhas finas, tom de engenharia).
- **VoltAgent** — canvas preto-vazio, acento esmeralda, estética terminal-nativa.
- **xAI** — monocromático stark, minimalismo futurista, tipografia mono em quase tudo.

## Ferramentas de dev & plataformas

- **Linear** — dark-mode nativo (não é "tema escuro aplicado", é a mídia nativa): canvas
  quase-preto `#08090a`, texto luminoso `#f7f8f8`, bordas quase invisíveis
  (`rgba(255,255,255,0.05)`). `Inter` com peso 510 (assinatura — entre regular e medium) e
  tracking bem negativo em headline (-1.58px a 72px). Mono: `JetBrains Mono`. Hierarquia via
  luminância, não cor — precisão cirúrgica.
- **Vercel** — minimalismo como princípio de engenharia: fundo branco puro `#ffffff`, texto
  quase-preto `#171717`, cada pixel precisa se justificar. Fonte `Geist` (substituto: `Geist` no
  Google Fonts) com tracking bem negativo (-2.4px a -2.88px em display) — headline parece
  "minificada para produção". Mono: `Geist Mono`, ligaduras ligadas.
- **Cursor** — interface escura elegante, acentos em gradiente, tom "ferramenta premium de dev".
- **Expo** — tema escuro, tracking apertado, visual code-centric.
- **Mintlify** — limpo, acento verde, otimizado pra leitura longa (documentação).
- **PostHog** — branding divertido, dark UI amigável ao dev — foge do "enterprise sério".
- **Raycast** — chrome escuro elegante, acentos em gradiente vibrante, sensação de ferramenta rápida.
- **Resend** — tema escuro minimalista, acentos monospace, tom técnico sem ser frio.
- **Sentry** — dashboard escuro denso em dado, acento rosa-roxo — dado como protagonista.
- **Supabase** — tema escuro esmeralda, code-first, identidade forte de "dev tool open source".
- **Superhuman** — UI escura premium, keyboard-first, glow roxo — sensação de exclusividade.
- **Warp** — interface tipo IDE escura, UI baseada em blocos (como comandos de terminal).
- **Zapier** — laranja quente, ilustração amigável — foge do visual "SaaS B2B frio".

## Infraestrutura & cloud

- **ClickHouse** — acento amarelo, estilo documentação técnica, tom "ferramenta séria de dado".
- **HashiCorp** — enterprise-clean, preto e branco, zero ruído visual.
- **MongoDB** — verde-folha como marca, foco em documentação pra dev.
- **Sanity** — acento vermelho, layout editorial content-first.
- **Stripe** — o padrão-ouro de design fintech: canvas branco `#ffffff`, headings em navy profundo
  `#061b31` (não preto — mais quente), roxo assinatura `#533afd` como âncora de marca e CTA.
  Fonte `sohne-var` peso 300 em display (leve, quase sussurrada — o oposto do "headline bold
  gritando"); substituto: `Source Sans 3`. Sombra em multi-camada com tom azulado
  (`rgba(50,50,93,0.25)`) — elevação que parece cor de marca, não cinza genérico.

## Design & produtividade

- **Airtable** — colorido, amigável, estética de dado estruturado (planilha bonita).
- **Cal.com** — UI neutra e limpa, simplicidade orientada a dev.
- **Clay** — formas orgânicas, gradientes suaves, layout com direção de arte.
- **Figma** — multi-cor vibrante, divertido mas profissional — reflete a própria ferramenta.
- **Framer** — preto e azul ousados, motion-first, visual "eu sou uma ferramenta de design".
- **Intercom** — paleta azul amigável, padrões de UI conversacional.
- **Miro** — acento amarelo vibrante, estética de canvas infinito.
- **Notion** — minimalismo quente (não frio): fundo branco puro, mas texto quase-preto com leve
  transparência (`rgba(0,0,0,0.95)`) — mais suave que preto puro. Cinza-cru com fundo
  amarelo-marrom (`#f6f5f4`, `#31302e`) dá textura tátil, quase analógica. `Inter` modificado com
  tracking negativo forte em display (-2.1px a 64px). Sensação: "papel de qualidade", não vidro
  estéril.
- **Pinterest** — acento vermelho, grid masonry, layout dirigido por imagem.
- **Webflow** — acento azul, estética de site de marketing polido.

## Fintech & cripto

- **Coinbase** — identidade azul limpa, foco em confiança/institucional.
- **Kraken** — dark UI com acento roxo, dashboards densos em dado.
- **Revolut** — interface escura elegante, cartões em gradiente, precisão fintech.
- **Wise** — acento verde vibrante, tom amigável e claro (o oposto de "banco sisudo").

## Enterprise & consumidor

- **Airbnb** — acento coral quente, fotografia em destaque, UI arredondada e convidativa.
- **Apple** — espaço em branco premium, `SF Pro`, imagem cinematográfica — luxo por ausência de
  ruído.
- **BMW** — superfícies escuras premium, estética de engenharia de precisão.
- **IBM** — Carbon Design System, paleta azul estruturada, grid rígido.
- **NVIDIA** — energia verde-preto, estética de "poder técnico".
- **SpaceX** — preto e branco stark, imagem full-bleed, futurismo sem enfeite.
- **Spotify** — verde vibrante sobre preto, tipografia ousada, capa de álbum como elemento central.
- **Uber** — preto e branco ousado, tipografia apertada, energia urbana.

## Substituição de fonte (referência rápida)

A maioria dos sites acima usa fonte proprietária. Ao gerar HTML autocontido, use o substituto do
Google Fonts que preserva o caráter (peso, tracking, humor) — o que carrega mais identidade
visual é o **peso e o letter-spacing**, não a face exata da fonte:

| Fonte proprietária | Substituto CDN | Caráter |
|---|---|---|
| Geist / Geist Sans (Vercel) | Geist (Google Fonts) | Geométrica, tracking comprimido |
| Geist Mono | Geist Mono | Monospace limpo, com ligaduras |
| sohne-var (Stripe) | Source Sans 3 | Elegância em peso leve |
| Berkeley Mono | JetBrains Mono | Monospace técnico |
| Airbnb Cereal VF | DM Sans | Geométrica arredondada, amigável |
| Circular (Spotify) | DM Sans | Geométrica, calorosa |
| figmaSans | Inter | Humanista limpa |
| Pin Sans (Pinterest) | DM Sans | Amigável, arredondada |
| CoinbaseDisplay/Sans | DM Sans | Geométrica, confiável |
| UberMove | DM Sans | Firme, apertada |
| HashiCorp Sans | Inter | Enterprise, neutra |
| waldenburgNormal (Sanity) | Space Grotesk | Geométrica, levemente condensada |
| IBM Plex Sans/Mono | IBM Plex Sans/Mono | Já disponível no Google Fonts |
| Rubik (Sentry) | Rubik | Já disponível no Google Fonts |
| NotionInter | Inter | Humanista, tracking negativo em display |

Quando o CDN já bate com o original (Inter, IBM Plex, Rubik, Geist) não há perda. Quando é
substituto (DM Sans no lugar de Circular, Source Sans 3 no lugar de sohne-var), siga de perto o
peso/tamanho/tracking do sistema original — isso carrega mais identidade que a face exata da fonte.

## Padrão de aplicação em HTML/CSS

```html
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
  :root {
    --color-bg: #ffffff;
    --color-text: #171717;
    --color-accent: #533afd; /* exemplo Stripe */
  }
  body {
    font-family: 'Inter', system-ui, -apple-system, sans-serif;
    color: var(--color-text);
    background: var(--color-bg);
  }
</style>
```

Trate paleta, tipografia e sombra como variáveis CSS (`:root`), aplique de forma consistente em
todos os componentes — é isso que faz a UI parecer um sistema, não um mosaico de escolhas soltas.
