---
name: api-debug
description: Depura APIs REST/GraphQL — status code, autenticação, introspecção de schema, reprodução de falha com curl/execute_code.
triggers: [api, rest, graphql, curl, status code, 401, 403, 404, 422, 429, 500, webhook, autenticação, schema, endpoint]
intent_examples:
  - "a API está devolvendo 401, não sei por quê"
  - "funciona no Postman mas falha no meu código"
  - "reproduz essa falha de webhook"
  - "a query GraphQL não traz os dados certos"
  - "essa API está com rate limit, como eu lido com isso"
metadata:
  hermes:
    tags: [api, rest, graphql, http, debugging, testing, curl, integration]
    category: software-development
    related_skills: [depuracao-sistematica]
---
# Depurar APIs REST/GraphQL

Isole a camada que está falhando antes de sair trocando código. Use `run_shell` pra `curl`,
`execute_code` pra scripts Python multi-etapa, e `web_extract`/`web_search` pra achar a
documentação do provedor em vez de adivinhar o formato do payload. Quando o script stdlib desta
skill (`${OKAMI_SKILL_DIR}/scripts/api_probe.py`) já resolve — request com cabeçalho redigido,
decodificar expiração de JWT — prefira ele a montar curl à mão toda vez.

## Quando usar

- API devolve status ou corpo inesperado.
- Autenticação falha (401/403 depois de renovar credencial, OAuth, chave dedicada).
- Funciona no Postman/Insomnia mas falha no código.
- Depuração de integração de webhook/callback.
- Escrever ou revisar teste de integração de API.
- Problema de rate limit ou paginação.

Não é o caso pra: renderização de UI, tuning de query de banco, ou infra de DNS/firewall (escale
pro time responsável). Para o "depois de achar a causa, corrigir o código", veja
`depuracao-sistematica`.

## Princípio central

**Isole a camada, depois corrija.** Um 200 OK pode esconder dado quebrado. Um 500 pode mascarar um
typo de um caractere na autenticação. Percorra a cadeia em ordem, sem pular etapa:

```
1. Conectividade    → dá pra alcançar o host?
1.5 Timeout         → conecta devagar ou lê devagar?
2. TLS/SSL          → certificado válido e confiável?
3. Autenticação     → credencial correta e não expirada?
4. Formato do request → o payload bate com o que o servidor espera?
5. Parse da resposta → seu código aceita o que voltou?
6. Semântica        → o dado significa o que você está assumindo?
```

## Início rápido

### REST via `run_shell`

```bash
curl -v https://api.exemplo.com/users/1                      # troca verbosa de request/response
curl -sI https://api.exemplo.com/health                      # só cabeçalhos
curl -s https://api.exemplo.com/users | python3 -m json.tool # JSON formatado
```

### GraphQL via `run_shell`

```bash
curl -X POST https://api.exemplo.com/graphql \
  -H 'Content-Type: application/json' \
  -d '{"query":"{ user(id: 1) { name email } }"}'
```

**Pegadinha do GraphQL:** o servidor costuma devolver HTTP 200 mesmo quando a query falhou.
Sempre inspecione o campo `errors` independente do status:

```python
# via execute_code
import requests
resp = requests.post(
    "https://api.exemplo.com/graphql",
    json={"query": "{ user(id: 1) { name email } }"},
)
data = resp.json()
if data.get("errors"):
    for err in data["errors"]:
        print(f"erro GraphQL: {err['message']} (path: {err.get('path')})")
print(data.get("data"))
```

### Script desta skill

```bash
python3 ${OKAMI_SKILL_DIR}/scripts/api_probe.py request --url https://api.exemplo.com/users/1 \
  --header "Accept: application/json" --credential-var API_CREDENCIAL
```

Imprime request e response (cabeçalhos redigidos automaticamente), detecta `errors` no corpo
GraphQL, e devolve exit code != 0 em status >= 400 — dá pra encadear em teste de regressão.
`--credential-var` aceita mais de um nome (tenta cada um, nessa ordem) e busca só na variável de
ambiente do processo e no arquivo de configuração global do Okami — não vasculha mais nada.

## Fluxo de depuração em camadas

### Passo 1 — Conectividade

```bash
nslookup api.exemplo.com
curl -v --connect-timeout 5 https://api.exemplo.com/health
```
Falhas típicas: DNS não resolve, firewall, VPN necessária, proxy ausente.

### Passo 1.5 — Timeout

Separe "não alcança" de "alcança mas está lento":

```bash
curl -w "dns:%{time_namelookup}s connect:%{time_connect}s tls:%{time_appconnect}s ttfb:%{time_starttransfer}s total:%{time_total}s\n" \
  -o /dev/null -s https://api.exemplo.com/endpoint
```

`time_connect` alto é rede/firewall; `time_starttransfer` alto com `time_connect` baixo é servidor
lento. Em Python, sempre passe timeout em tupla — `requests` não tem default e trava pra sempre:

```python
requests.get(url, timeout=(3.05, 30))  # (connect, read)
```

### Passo 2 — TLS/SSL

```bash
curl -vI https://api.exemplo.com 2>&1 | grep -E "SSL|subject|expire|issuer"
```
Falhas: certificado expirado, self-signed, hostname não bate, CA bundle ausente. `-k` só em
depuração pontual, nunca em código de produção.

### Passo 3 — Autenticação

```bash
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $CREDENCIAL" https://api.exemplo.com/me
python3 ${OKAMI_SKILL_DIR}/scripts/api_probe.py jwt-decode --value "$CREDENCIAL"
```
Checklist:
- A credencial expirou? (campo `exp` se for JWT — use `jwt-decode` acima)
- Esquema certo? `Bearer` vs `Basic` vs cabeçalho de chave dedicado do provedor
- Ambiente certo? Credencial de staging em produção é clássico
- Vai no cabeçalho ou em query param (`?key=…`)? Query param vaza em log de servidor — evite.

Se a credencial não está disponível pelas fontes sancionadas (variável de ambiente já exportada,
arquivo de configuração global do Okami), **peça ao dono pelo canal seguro** e guarde no cofre de
segredos do Okami — nunca vasculhe disco atrás de sessão/perfil de outra ferramenta, e nunca
proponha bypass de sandbox pra contornar a falta de acesso (mesmo princípio da skill
`ferramentas-nativas-primeiro`).

### Passo 4 — Formato do request

```bash
curl -v -X POST https://api.exemplo.com/endpoint \
  -H 'Content-Type: application/json' -d '{"key":"value"}'
```

**Content-Type vs corpo — o 415/400 silencioso:**

```python
# ERRADO — data= manda form-encoded, o cabeçalho mente
requests.post(url, data='{"k":"v"}', headers={"Content-Type": "application/json"})
# CERTO — json= já ajusta o cabeçalho e serializa
requests.post(url, json={"k": "v"})
```

Comuns: form-encoded vs JSON, campo obrigatório faltando, verbo HTTP errado, query param sem
encode.

### Passo 5 — Parse da resposta

Sempre confira o `Content-Type` antes de chamar `.json()`:

```python
resp = requests.post(url, json=payload, timeout=10)
ct = resp.headers.get("Content-Type", "")
if "application/json" in ct:
    print(resp.json())
else:
    print(f"content-type inesperado {ct!r}, corpo={resp.text[:500]!r}")
```
Falhas: página HTML de erro onde JSON era esperado, corpo vazio, charset errado.

### Passo 6 — Validação semântica

Deu parse limpo — mas o dado está *correto*?
- `"status": "active"` significa o que seu código está assumindo?
- O `id` da resposta bate com o que foi pedido?
- Timestamp no fuso esperado?
- Paginação trazendo tudo, ou só a primeira página?

## Playbook de status HTTP

| Status | Causa provável | Onde olhar |
|---|---|---|
| 401 | Credencial ausente/inválida | `curl -v` confirma se o cabeçalho `Authorization` foi mesmo enviado; esquema certo? |
| 403 | Autenticado mas sem permissão | Escopo da credencial, dono do recurso, allowlist de IP, CORS |
| 404 | Recurso/URL errados | Caminho, barra final, versão da API (`/v1/` vs `/v2/`), base URL (staging vs prod) |
| 409 | Conflito de estado | Recurso duplicado, `ETag`/`If-Match` desatualizado, escrita concorrente |
| 422 | JSON válido, dado inválido | Corpo do erro costuma nomear o campo — tipo, obrigatoriedade, valor de enum |
| 429 | Rate limit | Cabeçalhos `Retry-After`/`X-RateLimit-*`, backoff exponencial |
| 5xx | Lado do servidor | 500 bug do provedor (capture o ID de correlação); 502/503/504 backoff + retry |

Backoff simples para 429/5xx:
```python
import time
def with_backoff(method, url, **kwargs):
    for attempt in range(5):
        resp = requests.request(method, url, **kwargs)
        if resp.status_code not in (429, 500, 502, 503, 504):
            return resp
        wait = int(resp.headers.get("Retry-After", 2 ** attempt))
        time.sleep(wait)
    return resp
```

## Paginação e idempotência

- **Paginação**: confirme que está pegando *todos* os resultados. Procure `next_cursor`,
  `next_page`, `total_count`. Cursor (`?cursor=abc`) é mais confiável que offset
  (`?limit=100&offset=200`) quando o dado muda entre páginas.
- **Idempotência**: em operação não idempotente (POST), mande `Idempotency-Key: <uuid>` pra retry
  não duplicar criação/cobrança. Obrigatório em pagamento e pedido.

## ID de correlação

Sempre capture o ID de request do provedor — é o caminho mais rápido pro suporte deles:

```python
request_id = (resp.headers.get("X-Request-Id") or resp.headers.get("X-Trace-Id")
              or resp.headers.get("CF-Ray"))
```

Template de relato pro provedor:
```
Endpoint:    POST /api/v1/orders
Request ID:  req_abc123xyz
Timestamp:   2026-03-17T14:30:00Z
Status:      500
Esperado:    201 com o objeto do pedido
Recebido:    500 {"error":"internal server error"}
Repro:       curl -X POST … (credencial: <REDACTED>)
```

## Validação de contrato / teste de regressão

Rode após upgrade de API ou integração de terceiro novo — ajuda a pegar drift de schema antes de
chegar em produção:

```python
def validate_user(data: dict) -> list[str]:
    errors = []
    required = {"id": int, "email": str, "created_at": str}
    for field, expected in required.items():
        if field not in data:
            errors.append(f"campo ausente: {field}")
        elif not isinstance(data[field], expected):
            errors.append(f"{field}: esperava {expected.__name__}, veio {type(data[field]).__name__}")
    return errors
```

Coloque um smoke test em `tests/` (health, listagem, campo obrigatório, autenticação inválida →
401) e rode com `run_shell('pytest tests/test_api_smoke.py -v')` depois de qualquer mudança de
integração.

## Segurança

- Nunca logue a credencial inteira — redija como `Bearer <REDACTED>` (o `api_probe.py` já faz isso
  sozinho pros cabeçalhos sensíveis).
- Nunca hardcode a credencial no script — leia de variável de ambiente ou do cofre do Okami.
- Gire a credencial imediatamente se ela vazar em log, mensagem de erro ou histórico do git.
- Credencial em query string vaza em log de servidor, histórico de navegador, cabeçalho referrer —
  prefira cabeçalho.
- 404 não deve revelar se um recurso existe pra outra conta (enumeração).
- Stack trace em produção não deve vazar caminho de arquivo nem versão de framework.
- Hostname/IP interno (`10.x.x.x`, `interno.corp.local`) não deve aparecer em corpo de erro.
- Confira se a credencial não volta ecoada no detalhe de um erro.
- Cabeçalho `Server`/`X-Powered-By` verboso demais é achado pra revisão de segurança, não pra
  ignorar.

## Delegação (`spawn`)

Para uma varredura completa de CRUD (todo verbo, caminho feliz + erro esperado por endpoint), use
`spawn` com o contexto apontando pra esta skill em vez de tentar caber tudo numa mensagem só —
volta com pass/fail por endpoint e o ID de correlação de cada falha.

## Relacionado

- `depuracao-sistematica` — depois de isolar a camada que falha, siga a causa raiz no seu código
- `ferramentas-nativas-primeiro` — credencial ausente é sempre pedido ao dono, nunca busca no disco
