---
name: ferramentas-nativas-primeiro
description: Princípio transversal — prefira a tool NATIVA do Okami a shell/browser improvisado; credencial faltando é PEDIDO ao dono, nunca caça no disco nem yolo.
triggers: [pdf, gerar pdf, html para pdf, credencial, senha, token, api key, preciso de acesso, oauth, login, autenticar, chromium, puppeteer, playwright, sandbox, yolo]
intent_examples:
  - "converte esse html em pdf"
  - "gera um relatório em pdf"
  - "preciso me autenticar no google pra isso"
  - "não achei a credencial, procura no disco"
  - "roda com --yolo pra pular a permissão"
metadata:
  hermes:
    tags: [meta, safety, tooling]
    category: core
---
# Ferramentas nativas primeiro (princípio transversal)

Duas regras curtas que valem para TODAS as skills, não só para esta.

## 1. Tool nativa do Okami > shell/browser improvisado

Antes de instalar/invocar algo externo (Puppeteer, Playwright, Chromium headless, um pacote npm
qualquer), pergunte: **o Okami já tem uma tool nativa pra isso?**

- **HTML/Markdown → PDF**: use a tool `generate_pdf`. É pura-Python (xhtml2pdf/fpdf2), roda em
  milissegundos, SEM Chromium — funciona numa VPS sem display, sem `npm install`, sem baixar
  ~170MB de browser. NUNCA suba um `puppeteer.launch()`/`playwright` só para renderizar HTML em
  PDF: numa VPS isso costuma falhar (sandbox do Chromium, `errno -88`, display ausente) e é lento
  mesmo quando funciona.
- **PDF que já existe** (corrigir texto, metadata, juntar/dividir páginas): skill `editar-pdf`
  (pypdf, também pura-Python).
- **Gerar imagem**: tool `generate_image`, não um serviço externo improvisado.
- **Web** (ler página, extrair conteúdo, pesquisar): `web_search`/`web_extract` primeiro. Só
  escale para um browser real (`browse`, que depende de Playwright) quando o conteúdo
  precisar de JS renderizado ou interação — e mesmo assim é opcional/lazy, não o primeiro passo.

Se uma ferramenta/skill externa (instalada via `okami learn` ou similar) empurra você para
Puppeteer/Chromium/um browser pesado quando existe tool nativa equivalente, PREFIRA A NATIVA.
Só caia para browser real se a tarefa genuinamente exigir (ex.: JS pesado, login interativo) E
ele estiver disponível — nunca como primeira tentativa para HTML→PDF.

## 2. Credencial faltando → PEÇA ao dono, nunca vasculhe

Se uma ação precisa de credencial (token, senha, chave de API, login OAuth de um serviço) e ela
não está disponível pelo caminho sancionado (`store_secret`, variável já configurada, `.env`
global do Okami):

- **PEÇA ao dono pelo canal seguro** — explique o que falta e por quê, e guarde o que ele mandar
  com `store_secret` (nunca ecoa o valor de volta no histórico).
- **NUNCA vasculhe o disco** atrás de arquivo de credencial/sessão de outra ferramenta (browser
  profile, `~/.config/*/credentials.json`, cookies salvos, chaveiro do sistema, etc.). Isso é
  exfiltração de segredo, não "resolver o problema sozinho".
- **NUNCA proponha `--yolo` ou qualquer bypass de sandbox/permissão** para contornar a falta de
  credencial ou de acesso. Se a tool pede aprovação, é o grant funcionando como deveria — peça
  ao dono pra liberar, não tente furar.
- Falta de credencial é motivo pra PARAR e perguntar, não pra improvisar um caminho alternativo
  que read o filesystem em busca de segredo alheio.
