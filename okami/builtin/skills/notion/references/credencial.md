# Credencial do Notion

Sem chamada de rede neste arquivo — só onde a credencial mora e como confirmar que ela está
disponível. As chamadas HTTP em si ficam em `${OKAMI_SKILL_DIR}/references/api-http.md` e no
`SKILL.md`, que só referenciam a credencial pela variável de ambiente `$NOTION_CRED` — nunca leem
nem repetem o valor aqui.

## 1. Criar a integração (uma vez, feito pelo dono)

1. O dono cria uma integração em https://notion.so/my-integrations.
2. Copia a credencial gerada (prefixo `ntn_` nas integrações mais novas, ou o formato antigo de
   dois-pontos usado antes da migração de 2024).
3. Guarda essa credencial em `$OKAMI_HOME/.env` (default `~/.okami/.env`, o mesmo lugar dos outros
   segredos globais do Okami) na chave `NOTION_API_KEY`.
4. **Compartilha a página/database alvo com a integração** dentro do Notion: menu `...` da página →
   `Connect to` → nome da integração. Sem isso, a API devolve 404 pra aquela página mesmo ela
   existindo.

O Okami NUNCA gera essa credencial sozinho nem tenta adivinhar — se `$OKAMI_HOME/.env` não tiver a
chave, peça ao dono pra criar a integração e colar o valor pelo canal seguro (veja a skill
`acesso-vps` pro fluxo de `store_secret`).

## 2. Disponibilizar como `$NOTION_CRED` na sessão

Antes de qualquer chamada HTTP, exporte a credencial guardada com um nome neutro:

```bash
export NOTION_CRED="$(grep '^NOTION_API_KEY=' "${OKAMI_HOME:-$HOME/.okami}/.env" | cut -d= -f2-)"
```

Se a variável ficar vazia, a credencial não está configurada — avise o dono, não invente um valor
nem tente outra fonte no disco.

## 3. `ntn` CLI (opcional, mac/Linux)

Se o `ntn` (CLI oficial do Notion) estiver instalado, ele também aceita a mesma credencial via uma
variável de ambiente própria do binário — consulte `ntn --help` na máquina de destino pra saber o
nome exato e exporte `$NOTION_CRED` para ela antes de chamar `ntn`. Ative `NOTION_KEYRING=0` se
quiser forçar armazenamento em arquivo em vez do chaveiro do SO (útil em VPS sem chaveiro gráfico).
