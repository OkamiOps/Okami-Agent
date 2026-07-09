---
name: google-workspace
description: Gmail, Calendar, Drive, Sheets e Docs via CLI `gws` (preferido) ou fallback Python puro. Exige o dono criar a própria credencial OAuth no Google Cloud — o Okami nunca gera ou adivinha isso.
triggers: [gmail, google calendar, google drive, google sheets, google docs, agenda do google, planilha do google, email do google, evento na agenda]
intent_examples:
  - "manda um email pelo gmail pra fulano"
  - "cria um evento amanhã às 15h na minha agenda do google"
  - "lista os arquivos recentes do meu drive"
  - "lê essa planilha do google sheets"
  - "acrescenta um parágrafo nesse documento do google docs"
metadata:
  hermes:
    tags: [Google, Gmail, Calendar, Drive, Sheets, Docs, Contacts, Email, OAuth]
    category: productivity
    ported_from: hermes google-workspace skill (Nous Research, MIT)
    requires_external: [gws CLI (opcional), credencial OAuth própria do dono]
---

# Google Workspace

Gmail, Calendar, Drive, Sheets e Docs — via OAuth gerenciado pelo Okami e um wrapper fino de CLI.
Quando o binário `gws` está instalado, ele é o backend de execução preferido (cobertura mais ampla
da API); senão, cai pro cliente Python embutido nesta skill.

**Esta skill NUNCA gera nem adivinha a credencial OAuth.** O par client_id/client_secret vem de um
projeto Google Cloud que o próprio dono cria — sem isso configurado, pare e peça ao dono, não
tente contornar.

## Antes de tudo — credencial

**Leia `${OKAMI_SKILL_DIR}/references/credencial.md`** — checagem de status, triagem de que
serviços o dono realmente precisa, criação do client OAuth (feita pelo dono, passo a passo), e a
troca do código de autorização pela credencial guardada. Todo o fluxo é não-interativo — o agente
conduz o dono por cada passo.

Antes de qualquer operação, rode:

```bash
python3 ${OKAMI_SKILL_DIR}/scripts/setup.py --check --format json
```

Se não devolver `AUTHENTICATED`, siga o guia de credencial antes de tentar qualquer comando abaixo.

## Só precisa de email?

Se o dono só quer enviar/ler email (sem Calendar/Drive/Sheets/Docs), considere a skill mais leve
de email por senha de aplicativo em vez desta — evita o projeto inteiro do Google Cloud. Pergunte
ao dono qual ele prefere se a skill de email estiver disponível.

## Uso — caminho A: `gws` CLI

```bash
python3 ${OKAMI_SKILL_DIR}/scripts/gws_bridge.py <argumentos do gws>
```

O bridge garante que a credencial gerenciada esteja válida (renovando se preciso) antes de invocar
`gws`. Consulte `gws --help` na máquina de destino pra sintaxe completa — a cobertura da API dele
é mais ampla que o fallback Python.

## Uso — caminho B: fallback Python puro

Quando `gws` não está instalado:

```bash
GAPI="python3 ${OKAMI_SKILL_DIR}/scripts/google_api.py"

$GAPI gmail-search --query "is:unread newer_than:7d" --max 10
$GAPI gmail-read --id <message_id>
$GAPI gmail-send --to alguem@exemplo.com --subject "Oi" --body "texto do email"

$GAPI calendar-list --calendar primary --max 10
$GAPI calendar-create --summary "Reunião" --start 2026-07-10T15:00:00-03:00 --end 2026-07-10T16:00:00-03:00

$GAPI drive-list --query "name contains 'relatorio'" --max 20

$GAPI sheets-read --sheet-id <id> --range "Sheet1!A1:D10"
$GAPI sheets-append --sheet-id <id> --range "Sheet1!A1" --values '[["a","b"]]'

$GAPI docs-read --doc-id <id>
$GAPI docs-append --doc-id <id> --text "novo parágrafo"
```

Toda saída é UMA linha JSON: `{"ok": true, ...}` ou `{"ok": false, "error": "..."}`.

Sintaxe de busca do Gmail (`is:unread`, `from:`, `newer_than:` etc.): veja
`${OKAMI_SKILL_DIR}/references/gmail-search-syntax.md`.

## Armadilhas

- Datas do Calendar precisam de fuso horário explícito no formato ISO 8601
  (`2026-07-10T15:00:00-03:00`), não confie em interpretação implícita.
- `sheets-append` espera `--values` como array 2D JSON válido — uma linha vira `[["a","b"]]`.
- `docs-append` só sabe acrescentar texto simples no fim do documento — pra formatação rica ou
  inserção em posição específica, use o `gws` CLI (cobertura completa da API do Docs) se disponível.
- Se a credencial expirar no meio de uma tarefa longa, tanto `gws_bridge.py` quanto `google_api.py`
  renovam sozinhos — se a renovação falhar, o dono precisa refazer o Passo 3/4 do guia de
  credencial (a sessão de consentimento anterior pode ter sido revogada).
- Nunca leia nem repita o conteúdo do arquivo de credencial guardado numa mensagem pro dono — só
  confirme status (`AUTHENTICATED`/`NOT_AUTHENTICATED`).
