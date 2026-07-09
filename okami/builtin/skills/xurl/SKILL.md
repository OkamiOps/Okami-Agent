---
name: xurl
description: Posta, busca, curte, segue e envia DM no X/Twitter via o CLI oficial `xurl` — cobre a API v2 inteira.
triggers: [twitter, x.com, posta no x, tweet, xurl, api do twitter, buscar tweets, dm no x, seguir no x]
intent_examples:
  - "posta esse texto no X"
  - "responde esse tweet com isso"
  - "busca posts recentes sobre 'lançamento okami'"
  - "manda uma DM pro @fulano no X"
  - "quantos seguidores eu tenho no X agora"
metadata:
  hermes:
    tags: [twitter, x, social-media, xurl, official-api]
    category: social
    homepage: https://github.com/xdevplatform/xurl
    requires_toolsets: [terminal]
---
# xurl — X (Twitter) via o CLI oficial

`xurl` é o CLI oficial da plataforma de desenvolvedores do X pra API v2. Tem atalhos pras ações
comuns e também acesso genérico a qualquer endpoint da v2. Toda saída é JSON no stdout.

Use essa skill pra: postar, responder, citar, apagar posts; buscar posts e ler timeline/menções;
curtir, repostar, salvar; seguir, deixar de seguir, bloquear, silenciar; mensagem direta; upload de
mídia (imagem e vídeo); acesso genérico a qualquer endpoint v2; múltiplas contas/apps.

---

## Segurança de credencial (OBRIGATÓRIO)

Regras críticas ao operar dentro de uma sessão de agente/LLM:

- **Nunca** leia, imprima, resuma ou envie o arquivo de configuração local do `xurl` (guarda a
  credencial de acesso) pro contexto do LLM.
- **Nunca** peça pro usuário colar credencial diretamente no chat.
- O usuário preenche a configuração local do `xurl` manualmente, na própria máquina dele — fora da
  sessão do agente.
- **Nunca** recomende ou rode comando de autenticação com credencial embutida inline dentro da
  sessão do agente.
- **Nunca** use a flag verbosa de debug do `xurl` numa sessão de agente — ela pode expor cabeçalho
  de autenticação.
- Pra verificar se a credencial já existe, use só: `xurl auth status`.

Flags proibidas em comando rodado pelo agente (aceitam credencial inline):
`--bearer-token`, `--consumer-key`, `--consumer-secret`, `--access-token`, `--token-secret`,
`--client-id`, `--client-secret`.

O cadastro do app e a rotação de credencial precisam ser feitos pelo usuário manualmente, fora da
sessão do agente — veja "Configuração inicial" abaixo.

---

## Instalação

Uma das opções abaixo:

```bash
# Homebrew (macOS)
brew install --cask xdevplatform/tap/xurl

# npm
npm install -g @xdevplatform/xurl

# Go
go install github.com/xdevplatform/xurl@latest
```

Também existe um script de instalação oficial no repositório do projeto (README em
https://github.com/xdevplatform/xurl) — prefira Homebrew/npm/Go num ambiente de agente; scripts de
instalação baixados e executados direto de uma sessão do agente exigem revisão manual antes de
rodar.

Confira:

```bash
xurl --help
xurl auth status
```

Se `xurl auth status` não mostrar app/credencial nenhuma, o usuário precisa terminar a configuração
manual — ver seção abaixo.

---

## Configuração inicial (o usuário roda isso, não o agente)

Esses passos são do usuário, NUNCA do agente — envolvem colar credencial. Direcione o usuário pra
esse bloco; não execute por ele.

1. Cria/abre um app em https://developer.x.com/en/portal/dashboard.
2. Define o redirect URI como `http://localhost:8080/callback`.
3. Copia o Client ID e o Client Secret do app.
4. Registra o app localmente (usuário roda):
   ```bash
   xurl auth apps add meu-app --client-id SEU_CLIENT_ID --client-secret SEU_CLIENT_SECRET
   ```
5. Autentica (com `--app` pra vincular a credencial ao app certo):
   ```bash
   xurl auth oauth2 --app meu-app
   ```
   (abre o navegador pro fluxo OAuth 2.0 PKCE.)
6. Define esse app como padrão:
   ```bash
   xurl auth default meu-app
   ```
7. Confirma:
   ```bash
   xurl auth status
   xurl whoami
   ```

Depois disso o agente usa qualquer comando abaixo sem precisar de mais configuração — a credencial
OAuth 2.0 renova sozinha.

> **Pegadinha comum:** se o usuário esquecer `--app meu-app` no passo 5, a credencial cai no app
> embutido `default` (sem client-id/client-secret) — os comandos falham mesmo o fluxo tendo
> "funcionado". Refaça o passo 5 com `--app meu-app` e repita o passo 6.

---

## Referência rápida

| Ação | Comando |
| --- | --- |
| Postar | `xurl post "Olá mundo!"` |
| Responder | `xurl reply ID_DO_POST "boa!"` |
| Citar | `xurl quote ID_DO_POST "meu comentário"` |
| Apagar | `xurl delete ID_DO_POST` |
| Ler um post | `xurl read ID_DO_POST` |
| Buscar posts | `xurl search "QUERY" -n 10` |
| Quem sou eu | `xurl whoami` |
| Ver um usuário | `xurl user @handle` |
| Timeline | `xurl timeline -n 20` |
| Menções | `xurl mentions -n 10` |
| Curtir / descurtir | `xurl like ID_DO_POST` / `xurl unlike ID_DO_POST` |
| Repostar / desfazer | `xurl repost ID_DO_POST` / `xurl unrepost ID_DO_POST` |
| Seguir / deixar de seguir | `xurl follow @handle` / `xurl unfollow @handle` |
| Bloquear / silenciar | `xurl block @handle` / `xurl mute @handle` |
| Enviar DM | `xurl dm @handle "mensagem"` |
| Listar DMs | `xurl dms -n 10` |
| Upload de mídia | `xurl media upload caminho/do/arquivo.mp4` |
| Status do upload | `xurl media status MEDIA_ID` |
| Listar apps | `xurl auth apps list` |
| App padrão | `xurl auth default NOME` |
| Status da credencial | `xurl auth status` |

Notas: `ID_DO_POST` também aceita URL completa (o `xurl` extrai o ID). Handle funciona com ou sem
`@` na frente.

---

## Detalhes de comando

### Postar

```bash
xurl post "Olá mundo!"
xurl post "Olha só isso" --media-id MEDIA_ID
xurl reply 1234567890 "Ótimo ponto!"
xurl quote 1234567890 "Meu comentário"
xurl delete 1234567890
```

### Ler e buscar

```bash
xurl read 1234567890
xurl search "golang"
xurl search "from:algumusuario" -n 20
xurl search "#buildinpublic lang:pt" -n 15
```

Pra artigos longos do X (X Articles), use o modo de endpoint genérico em vez do atalho `read` —
peça o campo `article` e leia `data.article.plain_text` da resposta JSON.

### Usuário, timeline, menções

```bash
xurl whoami
xurl user algumusuario
xurl timeline -n 25
xurl mentions -n 20
```

### Engajamento

```bash
xurl like 1234567890
xurl repost 1234567890
xurl bookmark 1234567890
xurl bookmarks -n 20
```

### Grafo social

```bash
xurl follow @handle
xurl following -n 50
xurl followers --of algumusuario -n 20
xurl block @spammer
xurl mute @chato
```

### Mensagem direta

```bash
xurl dm @algumusuario "vi seu post!"
xurl dms -n 25
```

### Upload de mídia

```bash
xurl media upload foto.jpg
xurl media upload video.mp4
xurl media status --wait MEDIA_ID
```

---

## Acesso a endpoint genérico

Os atalhos cobrem o comum. Pra qualquer outra coisa, o `xurl` também aceita endpoint v2 direto:

```bash
xurl /2/users/me
xurl -X POST /2/tweets -d '{"text":"Olá mundo!"}'
xurl -X DELETE /2/tweets/1234567890
xurl -s /2/tweets/search/stream   # força modo streaming
```

---

## Formato de saída

Toda resposta é JSON. Sucesso: `{ "data": { "id": "...", "text": "..." } }`. Erro:
`{ "errors": [ { "message": "...", "code": 403 } ] }` — código de saída != 0 em qualquer erro.

---

## Fluxo do agente

1. Verifica pré-requisito: `xurl --help` e `xurl auth status`.
2. Confirma que o app padrão tem credencial válida (procure o marcador de "app ativo" na saída de
   `auth status`). Se o app padrão não tiver credencial mas outro app tiver, avise o usuário pra
   rodar `xurl auth default <esse-app>`.
3. Se não houver credencial nenhuma, pare e direcione o usuário pra "Configuração inicial" — não
   tente cadastrar app nem lidar com credencial você mesmo.
4. Comece com uma leitura barata (`xurl whoami`, `xurl search ... -n 3`) pra confirmar que está
   tudo respondendo.
5. Confirme o post/usuário-alvo e a intenção antes de qualquer ação de escrita (postar, responder,
   curtir, repostar, DM, seguir, bloquear, apagar).
6. Nunca cole o conteúdo do arquivo de configuração do `xurl` de volta na conversa.

---

## Limites e observações

- **Limite de taxa:** o X aplica limite por endpoint. Código 429 = espera e tenta de novo.
  Ações de escrita têm limite mais apertado que leitura.
- **Escopo:** se uma ação específica der 403, provavelmente falta escopo na credencial — o usuário
  precisa refazer a autenticação.
- **Renovação automática:** a credencial OAuth 2.0 renova sozinha, nada a fazer.
- **Múltiplos apps/contas:** cada app tem credencial isolada; troque com `xurl auth default` ou
  `--app`.
- **Custo:** acesso à API do X costuma ser pago pra uso significativo — muita falha é problema de
  plano/permissão, não de comando errado.

---

## Atribuição

- CLI original: https://github.com/xdevplatform/xurl (time da plataforma de desenvolvedores do X).
- Adaptação Okami: reformatado pro padrão de skill do Okami a partir do port já feito pelo Hermes
  Agent, com as regras de segurança de credencial preservadas.
