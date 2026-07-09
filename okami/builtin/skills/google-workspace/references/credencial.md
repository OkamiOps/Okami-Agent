# Credencial do Google Workspace

Sem chamada de rede neste arquivo — só de onde vem a credencial e como o dono a autoriza. As
chamadas de rede em si ficam nos scripts (`gws_bridge.py`, `google_api.py`, `setup.py`), que nunca
inventam nem adivinham essa credencial.

## O Okami NUNCA gera essa credencial sozinho

O par client_id/client_secret vem de um projeto Google Cloud que o **dono** cria e baixa. O Okami
só guarda o que o dono forneceu e conduz o fluxo padrão de autorização (Authorization Code + PKCE)
contra os endpoints publicados do Google — nenhum segredo é fabricado, adivinhado ou lido de outro
lugar do disco.

## Caminho A — CLI `gws` (preferido quando instalado)

Se o binário `gws` estiver disponível no PATH, use-o como backend de execução — ele já sabe
falar com Gmail/Calendar/Drive/Sheets/Docs. O script `${OKAMI_SKILL_DIR}/scripts/gws_bridge.py`
garante que a credencial gerenciada pelo Okami esteja válida (renovando se preciso) antes de
invocar `gws` com os argumentos passados.

```bash
python3 ${OKAMI_SKILL_DIR}/scripts/gws_bridge.py <argumentos do gws>
```

## Caminho B — fallback Python puro

Se `gws` não estiver instalado, use `${OKAMI_SKILL_DIR}/scripts/google_api.py` — fala direto com a
API REST do Google via stdlib, autenticado pela mesma credencial gerenciada.

## Configuração inicial (uma vez, conduzida passo a passo pelo agente)

Todo o setup é não-interativo — o agente conduz o dono por cada passo, funcionando em CLI,
Telegram ou qualquer canal.

### Passo 0 — checar se já está configurado

```bash
python3 ${OKAMI_SKILL_DIR}/scripts/setup.py --check --format json
```

Se devolver `AUTHENTICATED`, pule pro uso direto — setup já feito.

### Passo 1 — triagem: pergunte ao dono o que ele precisa

**Pergunta 1**: "Você precisa só de email, ou também Calendar/Drive/Sheets/Docs?" Escolha o
conjunto de `--services` mais estreito possível pra tela de consentimento pedir só os escopos
necessários (`email`, `calendar`, `drive`, `sheets`, `docs`, `contacts`, ou `all`).

**Pergunta 2**: "Sua conta Google usa Proteção Avançada (chave de segurança física pra login)? Se
não tem certeza, provavelmente não usa." Se usa, o administrador do Workspace precisa liberar o
client ID na lista de apps permitidos antes do Passo 3 funcionar.

### Passo 2 — criar as credenciais OAuth (uma vez, ~5 minutos, feito pelo dono)

Oriente o dono:

1. Criar/selecionar um projeto em https://console.cloud.google.com/projectselector2/home/dashboard
2. Ativar as APIs necessárias em https://console.cloud.google.com/apis/library (Gmail, Calendar,
   Drive, Sheets, Docs, People conforme o que ele escolheu no Passo 1)
3. Criar o client OAuth em https://console.cloud.google.com/apis/credentials → "Create Credentials"
   → "OAuth 2.0 Client ID" → tipo "Desktop app"
4. Se o app ainda está em modo Testing, adicionar a própria conta como test user em
   https://console.cloud.google.com/auth/audience
5. Baixar o arquivo JSON e informar o caminho pro agente

Quando o dono informar o caminho:

```bash
python3 ${OKAMI_SKILL_DIR}/scripts/setup.py --client-secret /caminho/para/client.json --format json
```

### Passo 3 — gerar a URL de autorização

```bash
python3 ${OKAMI_SKILL_DIR}/scripts/setup.py --auth-url --services email,calendar --format json
```

Mande a URL exata pro dono. Avise que o navegador provavelmente vai falhar em
`http://localhost:1` depois de autorizar — isso é esperado. Peça pra ele copiar a URL inteira da
barra de endereço redirecionada (ou só o parâmetro `code`).

### Passo 4 — trocar o código pela credencial

```bash
python3 ${OKAMI_SKILL_DIR}/scripts/setup.py --auth-code "URL_OU_CODIGO_QUE_O_DONO_COLOU" --format json
```

Se falhar por código expirado/já usado, peça pro dono repetir o Passo 3 do zero (nova URL, nova
tentativa).

### Passo 5 — confirmar

```bash
python3 ${OKAMI_SKILL_DIR}/scripts/setup.py --check --format json
```

Deve devolver `AUTHENTICATED`.
