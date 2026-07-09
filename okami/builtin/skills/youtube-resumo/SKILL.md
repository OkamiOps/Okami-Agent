---
name: youtube-resumo
description: Busca a transcrição de um vídeo do YouTube e transforma em resumo, capítulos, thread ou post — cenário comum quando o dono manda um link no chat pedindo "resume esse vídeo".
triggers: [resume esse vídeo, resume esse video, resume esse youtube, transcreve esse vídeo, do que fala esse vídeo, o que fala esse video, resumo do video, capítulos desse vídeo, transforma esse vídeo em post]
intent_examples:
  - "resume esse vídeo pra mim: https://youtube.com/watch?v=..."
  - "o que fala esse youtube que eu mandei?"
  - "transforma esse vídeo num thread pro Twitter"
  - "quais os capítulos desse vídeo?"
metadata:
  hermes:
    tags: [YouTube, Video, Transcript, Summary, Telegram]
    category: media
---

# YouTube — Transcrição e Resumo

Busca a transcrição de um vídeo do YouTube e transforma em resumo/capítulos/thread/post — cenário
comum quando o dono manda um link do YouTube no chat. Sem serviço externo pago: usa a legenda
pública do próprio vídeo (via `youtube-transcript-api`, se instalado, ou `urllib` puro como
alternativa embutida — nenhuma das duas exige chave de API).

## Como rodar

`OKAMI_SKILL_DIR` é a pasta desta skill (onde está este SKILL.md).

```
python3 ${OKAMI_SKILL_DIR}/scripts/fetch_transcript.py "<url_ou_id>"
```

Aceita qualquer formato de link do YouTube (watch, youtu.be, shorts, embed, live) ou o ID de 11
caracteres direto. Saída é UMA linha JSON: `{"ok": true, "full_text": "...", ...}` ou
`{"ok": false, "error": "..."}`.

## Comandos

```
python3 $SCRIPT "https://youtube.com/watch?v=VIDEO_ID"              # JSON com metadados + texto completo
python3 $SCRIPT "URL" --text-only                                    # só o texto puro (bom pra encadear)
python3 $SCRIPT "URL" --text-only --timestamps                       # texto com timestamp por linha
python3 $SCRIPT "URL" --language pt,en                                # idioma preferido, com fallback
```

## Fluxo recomendado

1. **Busca** a transcrição com `--text-only --timestamps`.
2. **Valida**: se `ok: false` ou texto vazio, tente de novo SEM `--language` (pega qualquer legenda
   disponível). Se continuar vazio, avise o dono que o vídeo provavelmente não tem legenda.
3. **Corta se for grande**: transcrição acima de ~50 mil caracteres, divida em blocos com sobreposição
   (~40 mil caracteres, 2 mil de sobreposição) e resuma cada bloco antes de juntar.
4. **Transforma** no formato pedido. Se o dono não especificou, o padrão é um resumo direto (5 a 10
   frases). Outros formatos comuns:
   - **Capítulos**: lista com timestamp e um título curto por trecho.
   - **Resumo por capítulo**: capítulos + um parágrafo curto cada.
   - **Thread**: posts numerados, cada um dentro do limite de caracteres da rede (ex.: 280 no X).
   - **Post/artigo**: título + seções + conclusão.
   - **Citações marcantes**: trechos com o timestamp de onde saíram.
5. **Revisa** o resultado antes de mandar: coerência, timestamps corretos, nada inventado que não
   estava na transcrição.

## Tratamento de erro

- **Legenda desativada/vídeo sem transcrição**: avise o dono; sugira conferir se o vídeo tem
  legendas ativadas na própria página do YouTube.
- **Vídeo privado/removido**: repasse o erro, peça pro dono confirmar o link.
- **Idioma pedido não disponível**: rode de novo sem `--language` pra pegar qualquer legenda
  existente, e avise qual idioma veio.
- **`youtube-transcript-api` ausente**: sem problema — o script cai sozinho pro método `urllib`
  embutido (mais frágil a mudanças de layout do YouTube, mas funciona sem instalar nada). Se
  quiser mais robustez, `pip install youtube-transcript-api` é opcional.
