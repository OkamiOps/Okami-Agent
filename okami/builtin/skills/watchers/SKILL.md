---
name: watchers
description: Poll RSS, GitHub e endpoints JSON com dedup por watermark — a base pra "me avisa quando X mudar".
triggers: [monitorar, watcher, ficar de olho, avisar quando, notificar quando, acompanhar feed, rss, poll]
intent_examples:
  - "fica de olho nesse feed RSS e me avisa quando sair notícia nova"
  - "monitora as issues desse repositório no github"
  - "cria um watcher pra essa API e me avisa quando aparecer item novo"
  - "quero ser notificado quando esse endpoint mudar"
metadata:
  hermes:
    tags: [cron, polling, rss, github, http, automation, monitoring]
    category: devops
    requires_toolsets: [terminal]
---
# Watchers

Poll uma fonte externa num intervalo e reage só ao que é NOVO. Três scripts prontos + um helper de
watermark compartilhado — funciona junto de um cron job (ou rodado ad-hoc pelo terminal). Este é o
padrão pra "me avisa quando X mudar/sair/atualizar" — o daily-driver de monitoramento na VPS.

## Quando usar

- Usuário quer acompanhar um feed RSS/Atom e ser avisado de itens novos.
- Usuário quer acompanhar issues/pulls/releases/commits de um repo GitHub.
- Usuário quer fazer poll de um endpoint JSON qualquer e ser avisado de itens novos.
- Usuário pede "um watcher pra X" ou "me avisa quando X mudar".

## Modelo mental

Um watcher é só um script que:

1. Busca dados da fonte externa.
2. Compara contra um watermark (arquivo com os IDs já vistos).
3. Grava o watermark atualizado de volta.
4. Imprime os itens novos no stdout (ou nada, se não houve mudança).

Os três scripts abaixo cuidam disso. Rode via terminal — de um cron job, de um webhook, ou
interativamente — e reporte o que é novo pro usuário.

## Scripts prontos

Os três vivem em `${OKAMI_SKILL_DIR}/scripts/`. Cada um lê `WATCHER_STATE_DIR` (default:
`$OKAMI_HOME/watcher-state/`) pro seu arquivo de estado, chaveado pelo argumento `--name`.

| Script | O que monitora | Chave de dedup |
|---|---|---|
| `watch_rss.py` | Feed RSS 2.0 ou Atom | `<guid>` / `<id>` |
| `watch_http_json.py` | Qualquer endpoint JSON que retorne uma lista de objetos | Campo id configurável |
| `watch_github.py` | Issues / pulls / releases / commits de um repo GitHub | `id` / `sha` |

Todos os três:

- Na primeira execução, gravam uma baseline — nunca reproduzem o feed inteiro de uma vez.
- Watermark é um conjunto de IDs limitado (máx. 500) pra não crescer sem limite.
- Formato de saída: `## <título>\n<url>\n\n<corpo opcional>` por item.
- Stdout vazio quando não há nada novo — trate isso como silêncio.
- Saem com código != 0 em erro de fetch.

## Uso

Rode um watcher direto pelo terminal:

```bash
python3 ${OKAMI_SKILL_DIR}/scripts/watch_rss.py \
  --name hn --url https://news.ycombinator.com/rss --max 5
```

Acompanhar um repo GitHub (defina `GITHUB_TOKEN` no `.env` global do Okami pra evitar o rate limit
anônimo de 60 req/hora):

```bash
python3 ${OKAMI_SKILL_DIR}/scripts/watch_github.py \
  --name okami-issues --repo owner/repo --scope issues
```

Fazer poll de uma API JSON qualquer:

```bash
python3 ${OKAMI_SKILL_DIR}/scripts/watch_http_json.py \
  --name api --url https://api.example.com/events \
  --id-field event_id --items-path data.events
```

## Ligando num cron

Peça pro sistema agendar um cron job (ferramenta/skill de agendamento do Okami) com um prompt do tipo:

> A cada 15 minutos, roda `watch_rss.py --name hn --url https://news.ycombinator.com/rss`. Se
> imprimir algo, resume as manchetes e me manda pelo Telegram. Se não imprimir nada, fica quieto.

O agente invoca o script pelo terminal dentro do loop do cron job — não precisa mudar nada no
agendador em si.

## Arquivos de estado

Cada watcher grava `$OKAMI_HOME/watcher-state/<name>.json`. Pra inspecionar:

```bash
cat $OKAMI_HOME/watcher-state/hn.json
```

Forçar replay (próxima execução tratada como primeira):

```bash
rm $OKAMI_HOME/watcher-state/hn.json
```

## Escrevendo o seu próprio

Os três scripts seguem o mesmo template: carrega watermark, busca, faz diff, salva, emite.
`scripts/_watermark.py` é o helper compartilhado — importe pra ganhar escrita atômica + conjunto de
IDs limitado + baseline de primeira execução de graça. Veja qualquer um dos três como referência de
quão pouco boilerplate isso exige.

## Erros comuns

1. **Imprimir um cabeçalho de "nada novo" a cada tick.** Quem consome espera stdout vazio = silêncio.
   Se você imprime algo mesmo sem delta, spamma o canal. Os scripts prontos já tratam isso — scripts
   customizados também precisam tratar.
2. **Esperar que a primeira execução emita itens.** Não emite — a primeira execução grava a baseline.
   Se precisar de um resumo inicial, apague o arquivo de estado depois da primeira execução ou
   adicione uma flag tipo `--prime-with-latest N` no seu próprio script.
3. **Watermark crescendo sem limite.** O helper compartilhado limita a 500 IDs. Aumente para feeds de
   alto volume; diminua em filesystems restritos.
4. **Colocar o diretório de estado num lugar que o sandbox do agente não escreve.**
   `$OKAMI_HOME/watcher-state/` é sempre gravável — prefira sempre esse caminho (ou o override
   explícito `WATCHER_STATE_DIR`).
