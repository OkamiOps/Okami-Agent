---
name: documentos-ocr
description: Extrai texto de PDF, foto de documento ou print/screenshot que o dono manda pelo Telegram — recibo, contrato, boleto, print de conversa. Pura-Python (pymupdf), sem serviço externo.
triggers: [extrai o texto, lê esse pdf, o que diz esse documento, transcreve essa foto, le esse print, tira o texto dessa imagem, resume esse pdf, o que tá escrito aqui, digitaliza esse documento]
intent_examples:
  - "manda o texto desse boleto que tirei foto"
  - "lê esse contrato em pdf pra mim"
  - "o que esse print de tela tá dizendo?"
  - "transcreve essa nota fiscal"
metadata:
  hermes:
    tags: [PDF, Documents, OCR, Text-Extraction, Telegram]
    category: productivity
---

# Documentos & OCR

Extração de texto de PDF e imagem (foto de documento, print/screenshot, recibo) que o dono manda
pelo chat — cenário comum no Telegram. Pura-Python via `pymupdf` (~25MB, sem modelo pesado, sem
serviço externo, sem chamada de rede). Veja também a skill `ferramentas-nativas-primeiro`.

Para EDITAR um PDF que já existe (metadata, corrigir texto pontual, juntar/dividir páginas), use a
skill `editar-pdf` — esta skill aqui é só LEITURA/extração.

## Como rodar

```
python3 ${OKAMI_SKILL_DIR}/scripts/extract_text.py <arquivo>
```

Toda saída é UMA linha JSON no stdout: `{"ok": true, ...}` ou `{"ok": false, "error": "..."}`.

## Comandos

```
python3 $SCRIPT documento.pdf                    # texto de todas as páginas
python3 $SCRIPT documento.pdf --page 2            # só a página 2 (0-indexado)
python3 $SCRIPT documento.pdf --pages 0-4         # intervalo de páginas (0-indexado)
python3 $SCRIPT documento.pdf --metadata          # nº de páginas + título/autor/etc.
python3 $SCRIPT foto_recibo.png                   # extrai texto de imagem (raster)
```

## Fluxo recomendado

1. Se o dono mandou um **PDF**: rode direto, sem `--metadata` primeiro (a menos que o pedido seja
   sobre autor/título). Documento com texto extraível (não-scan) resolve na hora.
2. Se o dono mandou uma **foto/print** (jpg/png): passe o caminho do arquivo direto — `pymupdf` lê
   raster e tenta extrair texto embutido, mas **não faz OCR de imagem sem camada de texto** (foto
   pura de papel escrito à mão, por exemplo). Se a extração vier vazia, avise o dono: precisaria de
   um OCR dedicado (ex.: `pytesseract`) que este script não cobre — não invente resultado.
3. PDF **criptografado/protegido por senha**: pymupdf pode recusar abrir; sem a senha não dá pra
   extrair — peça a senha ao dono, nunca tente força bruta.
4. Depois de extrair, o pedido normal é **resumir** ou **responder pergunta** sobre o conteúdo — isso
   é trabalho do modelo sobre o texto já extraído, não do script.

## Dependência

`pymupdf` é lazy — se ausente, o script devolve `{"ok": false, "error": "pymupdf não instalado..."}`
em vez de traceback. Instale com `pip install pymupdf` (ou `uv pip install pymupdf`) se precisar.

## Limitações (avise o dono se topar com isso)

- Scan/foto sem camada de texto (imagem pura) → `pymupdf` não faz OCR; texto vem vazio. Não é bug,
  é o limite da lib — comunique isso em vez de devolver texto inventado.
- PDF protegido por senha sem a senha fornecida: não dá pra abrir.
- Arquivo corrompido ou formato não suportado: o script devolve `{"ok": false, "error": ...}` com o
  motivo — repasse a mensagem de erro ao dono, não tente adivinhar o conteúdo.
