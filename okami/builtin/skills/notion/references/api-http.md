# Notion via HTTP (curl) — funciona em qualquer plataforma

Pré-requisito: `$NOTION_CRED` já exportado na sessão — veja
`${OKAMI_SKILL_DIR}/references/credencial.md` pra como obter e carregar essa variável. Esse arquivo
aqui não sabe de onde a credencial vem, só como usá-la.

`Notion-Version: 2025-09-03` é obrigatório em toda chamada. Nessa versão, o que os usuários chamam
de "database" virou **data source** na API.

Todas as chamadas seguem este padrão:

```bash
curl -s -X GET "https://api.notion.com/v1/..." \
  -H "Authorization: Bearer $NOTION_CRED" \
  -H "Notion-Version: 2025-09-03" \
  -H "Content-Type: application/json"
```

## Buscar (search)

```bash
curl -s -X POST "https://api.notion.com/v1/search" \
  -H "Authorization: Bearer $NOTION_CRED" \
  -H "Notion-Version: 2025-09-03" \
  -H "Content-Type: application/json" \
  -d '{"query": "título da página"}'
```

## Ler metadados de uma página

```bash
curl -s "https://api.notion.com/v1/pages/{page_id}" \
  -H "Authorization: Bearer $NOTION_CRED" \
  -H "Notion-Version: 2025-09-03"
```

## Ler página como Markdown (bom pra alimentar o modelo)

```bash
curl -s "https://api.notion.com/v1/pages/{page_id}/markdown" \
  -H "Authorization: Bearer $NOTION_CRED" \
  -H "Notion-Version: 2025-09-03"
```

## Ler conteúdo da página como blocos (quando precisa da estrutura)

```bash
curl -s "https://api.notion.com/v1/blocks/{page_id}/children" \
  -H "Authorization: Bearer $NOTION_CRED" \
  -H "Notion-Version: 2025-09-03"
```

Ver `${OKAMI_SKILL_DIR}/references/block-types.md` pro formato de cada tipo de bloco.

## Criar página a partir de Markdown

`POST /v1/pages` aceita o parâmetro `markdown` no corpo.

```bash
curl -s -X POST "https://api.notion.com/v1/pages" \
  -H "Authorization: Bearer $NOTION_CRED" \
  -H "Notion-Version: 2025-09-03" \
  -H "Content-Type: application/json" \
  -d '{
    "parent": {"page_id": "xxx"},
    "properties": {"title": [{"text": {"content": "Notas da reunião"}}]},
    "markdown": "# Pauta\n\n- Roadmap Q3\n- Contratação\n\n## Decisões\n- Lançar o MVP na sexta"
  }'
```

## Atualizar página com Markdown

```bash
curl -s -X PATCH "https://api.notion.com/v1/pages/{page_id}/markdown" \
  -H "Authorization: Bearer $NOTION_CRED" \
  -H "Notion-Version: 2025-09-03" \
  -H "Content-Type: application/json" \
  -d '{"markdown": "## Atualização\n\nPrototipo entregue."}'
```

## Criar página dentro de um database (propriedades tipadas)

```bash
curl -s -X POST "https://api.notion.com/v1/pages" \
  -H "Authorization: Bearer $NOTION_CRED" \
  -H "Notion-Version: 2025-09-03" \
  -H "Content-Type: application/json" \
  -d '{
    "parent": {"database_id": "xxx"},
    "properties": {
      "Name": {"title": [{"text": {"content": "Novo item"}}]},
      "Status": {"select": {"name": "A fazer"}}
    }
  }'
```

## Consultar um database (data source)

```bash
curl -s -X POST "https://api.notion.com/v1/data_sources/{data_source_id}/query" \
  -H "Authorization: Bearer $NOTION_CRED" \
  -H "Notion-Version: 2025-09-03" \
  -H "Content-Type: application/json" \
  -d '{
    "filter": {"property": "Status", "select": {"equals": "Ativo"}},
    "sorts": [{"property": "Date", "direction": "descending"}]
  }'
```

## Criar um database

```bash
curl -s -X POST "https://api.notion.com/v1/data_sources" \
  -H "Authorization: Bearer $NOTION_CRED" \
  -H "Notion-Version: 2025-09-03" \
  -H "Content-Type: application/json" \
  -d '{
    "parent": {"page_id": "xxx"},
    "title": [{"text": {"content": "Meu Database"}}],
    "properties": {
      "Name": {"title": {}},
      "Status": {"select": {"options": [{"name": "A fazer"}, {"name": "Feito"}]}},
      "Date": {"date": {}}
    }
  }'
```

## Atualizar propriedades de uma página

```bash
curl -s -X PATCH "https://api.notion.com/v1/pages/{page_id}" \
  -H "Authorization: Bearer $NOTION_CRED" \
  -H "Notion-Version: 2025-09-03" \
  -H "Content-Type: application/json" \
  -d '{"properties": {"Status": {"select": {"name": "Feito"}}}}'
```

## Adicionar blocos a uma página

```bash
curl -s -X PATCH "https://api.notion.com/v1/blocks/{page_id}/children" \
  -H "Authorization: Bearer $NOTION_CRED" \
  -H "Notion-Version: 2025-09-03" \
  -H "Content-Type: application/json" \
  -d '{
    "children": [
      {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "Oi do Okami!"}}]}}
    ]
  }'
```

## Upload de arquivo (fluxo em 3 passos)

```bash
# 1. Cria o upload
curl -s -X POST "https://api.notion.com/v1/file_uploads" \
  -H "Authorization: Bearer $NOTION_CRED" \
  -H "Notion-Version: 2025-09-03" \
  -H "Content-Type: application/json" \
  -d '{"filename": "foto.png", "content_type": "image/png"}'

# 2. PUT dos bytes na upload_url devolvida acima
curl -s -X PUT "{upload_url}" --data-binary @foto.png

# 3. Referencia {file_upload_id} no payload da página/bloco
```

## Migração 2025-09-03 — databases viraram data sources

- **Databases viraram data sources.** Use os endpoints `/data_sources/` pra consulta e leitura.
- **Dois IDs por database**: `database_id` e `data_source_id`.
  - `database_id` ao criar página: `parent: {"database_id": "..."}`
  - `data_source_id` ao consultar: `POST /v1/data_sources/{id}/query`
- A busca devolve databases como `"object": "data_source"` com o campo `data_source_id`.

## Notas

- IDs de página/database são UUIDs (com ou sem hífen — ambos aceitos).
- Limite de taxa: ~3 requisições/segundo em média.
- A API não consegue configurar filtro de **view** — isso é só na interface.
- Use `"is_inline": true` ao criar data sources pra embutir num página.
- Sempre passe `-s` no curl pra suprimir a barra de progresso (saída mais limpa).
- Encadeie com `jq` na leitura: `... | jq '.results[0].properties'`.
