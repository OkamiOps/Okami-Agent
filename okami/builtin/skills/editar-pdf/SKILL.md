---
name: editar-pdf
description: Edita PDF existente — metadata (título/autor), corrige texto pontual (título/data/nome), junta/divide/gira páginas. Pura-Python (pypdf), sem serviço externo.
triggers: [editar pdf, corrigir pdf, mudar o pdf, trocar o título do pdf, juntar pdf, dividir pdf, girar pagina, metadata do pdf]
intent_examples:
  - "corrige a data nesse PDF, tá 'janeiro' e devia ser 'fevereiro'"
  - "muda o título do documento pra 'Relatório Q3'"
  - "junta esses três PDFs num só"
  - "tira a página 2 desse contrato"
metadata:
  hermes:
    tags: [PDF, Documents, Editing]
    category: productivity
---

# Editar PDF

Edição de PDF EXISTENTE, pura-Python (`pypdf` + `fpdf2` — já são deps lazy do Okami, instalam sob
demanda). SEM serviço externo, SEM LLM adicional: metadata é edição direta; correção de texto usa
overlay (apaga um retângulo e escreve o texto novo por cima — é assim que editores de PDF corrigem
texto pontual sem re-renderizar o documento inteiro).

Para GERAR um PDF do zero (markdown/HTML → PDF), use a tool `generate_pdf`, não esta skill — esta é
só para PDF que já existe.

## Como rodar

```
python3 ${OKAMI_SKILL_DIR}/scripts/edit_pdf.py <comando> ...
```

Toda saída é UMA linha JSON no stdout: `{"ok": true, ...}` ou `{"ok": false, "error": "..."}`.

## Fluxo recomendado

1. **Sempre olhe antes de editar**: `info` (nº de páginas + metadata) e `extract` (texto de uma
   página) — sem isso você não sabe ONDE fica o trecho a corrigir.
2. Para corrigir um pedaço de texto (título, data, nome): `patch`. Você precisa do RETÂNGULO
   aproximado onde o texto está — se não souber as coordenadas exatas, comece com uma estimativa
   generosa (ex.: topo da página inteiro) e ajuste ao ver o resultado (`extract` de novo no PDF de
   saída pra conferir).
3. Sempre grave num arquivo de SAÍDA diferente do original (nunca sobrescreva sem o dono pedir).

## Comandos

```
python3 $SCRIPT info arquivo.pdf
python3 $SCRIPT extract arquivo.pdf --page 1
python3 $SCRIPT extract arquivo.pdf                          # todas as páginas

python3 $SCRIPT metadata in.pdf out.pdf --title "Novo Título" --author "Nome"

python3 $SCRIPT patch in.pdf out.pdf --page 1 \
    --rect 50,700,400,730 --text "Q3 Results" --font-size 14

python3 $SCRIPT delete-page in.pdf out.pdf --page 2
python3 $SCRIPT rotate in.pdf out.pdf --page 1 --degrees 90
python3 $SCRIPT merge junto.pdf a.pdf b.pdf c.pdf
python3 $SCRIPT split in.pdf ./paginas --prefix pagina
```

### `patch` — coordenadas do `--rect`

`x0,y0,x1,y1` em PONTOS PDF (1pt = 1/72"), origem no canto INFERIOR-esquerdo da página (padrão PDF —
NÃO é o topo). Uma página carta (letter) tem ~612×792pt; A4 tem ~595×842pt. Se a correção sair na
posição errada, ajuste `y0`/`y1` (lembrando que Y cresce de baixo pra cima) e rode `patch` de novo —
o comando é idempotente sobre o arquivo de ENTRADA original.

## Limitações (avise o dono se topar com isso)

- `patch` cobre o texto antigo com um retângulo BRANCO — se a página tiver fundo colorido/imagem
  naquela área, o patch também vai ficar branco (não preserva o fundo). Para esses casos, avise que
  a correção pontual não é confiável e sugira gerar o documento de novo via `generate_pdf`.
- PDF com texto como IMAGEM (scan) não tem texto extraível — `extract` devolve vazio. Não dá pra
  editar texto que não existe como texto.
- PDF criptografado/protegido por senha: `info` reporta `encrypted: true`; sem a senha não dá pra
  editar (pypdf não quebra proteção).
