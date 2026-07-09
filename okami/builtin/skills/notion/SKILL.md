---
name: notion
description: Lê e escreve páginas/databases do Notion via API HTTP (ou CLI `ntn` quando instalado) — página, bloco, database, Markdown. Credencial via variável de ambiente, nunca inventada.
triggers: [notion, página do notion, database do notion, cria uma nota no notion, atualiza o notion, busca no notion]
intent_examples:
  - "cria uma página no notion com essas notas da reunião"
  - "busca a página do notion sobre o roadmap"
  - "adiciona esse item no database de tarefas do notion"
  - "atualiza o status dessa página pra concluído no notion"
  - "lê o conteúdo dessa página do notion"
metadata:
  hermes:
    tags: [Notion, Productivity, Notes, Database, API, CLI, Workers]
    homepage: https://developers.notion.com
    category: productivity
    ported_from: hermes notion skill (community, MIT)
---

# Notion

Duas formas de falar com o Notion, mesma credencial pras duas — escolha pela disponibilidade:

- **`ntn` CLI** — CLI oficial do Notion. Sintaxe mais curta, upload de arquivo em uma linha,
  obrigatório pra Workers. Só mac/Linux. Preferido quando instalado.
- **HTTP puro (curl)** — funciona em qualquer plataforma, inclusive Windows. Fallback padrão quando
  `ntn` não está instalado.

## Credencial

**Leia `${OKAMI_SKILL_DIR}/references/credencial.md` primeiro** — como o dono cria a integração no
Notion, onde ela fica guardada nas configurações globais do Okami e como carregá-la na sessão como
`$NOTION_CRED`. O Okami nunca gera ou adivinha essa credencial — sem ela configurada, avise o dono
e pare.

Lembrete importante: a integração só enxerga página/database que o dono **compartilhou com ela**
explicitamente dentro do Notion (menu `...` → `Connect to`). 404 em algo que existe geralmente
significa isso.

## Chamadas via HTTP (curl)

**Leia `${OKAMI_SKILL_DIR}/references/api-http.md`** — todos os exemplos de busca, leitura,
criação e atualização de página/database/bloco via curl, já assumindo `$NOTION_CRED` carregado.

## Tipos de bloco

**Leia `${OKAMI_SKILL_DIR}/references/block-types.md`** — estrutura JSON de cada tipo de bloco
(parágrafo, heading, lista, to-do, quote, callout, code etc.) pra criar ou ler conteúdo.

## Tipos de propriedade (campos de database)

- **Title:** `{"title": [{"text": {"content": "..."}}]}`
- **Rich text:** `{"rich_text": [{"text": {"content": "..."}}]}`
- **Select:** `{"select": {"name": "Opção"}}`
- **Multi-select:** `{"multi_select": [{"name": "A"}, {"name": "B"}]}`
- **Date:** `{"date": {"start": "2026-01-15", "end": "2026-01-16"}}`
- **Checkbox:** `{"checkbox": true}`
- **Number:** `{"number": 42}`
- **URL:** `{"url": "https://..."}`
- **Email:** `{"email": "user@example.com"}`
- **Relation:** `{"relation": [{"id": "page_id"}]}`

## Markdown com sabor Notion (endpoints `/markdown`)

CommonMark padrão + tags estilo XML pros blocos específicos do Notion. Use **tab** pra indentação.

**Blocos além do CommonMark:**
```
<callout icon="🎯" color="blue_bg">
	Entrega o MVP até **sexta**.
</callout>

<details color="gray">
<summary>Título do toggle</summary>
	Filhos indentados um tab
</details>

<columns>
	<column>Lado esquerdo</column>
	<column>Lado direito</column>
</columns>

<table_of_contents color="gray"/>
```

**Inline:**
- Menções: `<mention-user url="..."/>`, `<mention-page url="...">Título</mention-page>`,
  `<mention-date start="2026-05-15"/>`
- Sublinhado: `<span underline="true">texto</span>`
- Cor: `<span color="blue">texto</span>` ou no nível do bloco com `{color="blue"}` na primeira linha
- Matemática: inline `$x^2$`, bloco `$$ ... $$`
- Citações: `[^https://example.com]`

**Cores:** `gray brown orange yellow green blue purple pink red`, mais variantes `*_bg` de fundo.

Headings 5/6 viram H4. Múltiplas linhas de `>` viram blocos de citação separados — use `<br>`
dentro de um único `>` pra citação multi-linha.

## Notion Workers (avançado, requer `ntn`)

Workers são programas TypeScript hospedados pelo Notion (syncs, tools, webhooks). Requer plano
Business/Enterprise pra deploy e só roda em mac/Linux. **Leia
`${OKAMI_SKILL_DIR}/references/workers.md`** pro guia completo — scaffold, comandos de ciclo de
vida e onde ficam segredos de webhook.

## Escolhendo o caminho certo

| Tarefa | mac/Linux | Windows |
|---|---|---|
| Ler/escrever página, buscar, consultar database | `ntn api ...` | curl (`references/api-http.md`) |
| Ler página pro modelo resumir | `ntn api v1/pages/{id}/markdown` | curl no endpoint `/markdown` |
| Upload de arquivo | `ntn files create < arquivo` | fluxo HTTP em 3 passos |
| Explorar a API pontualmente | `ntn api ...` | curl |
| Construir sync/webhook/tool hospedado pelo Notion | `ntn workers ...` | WSL2 + `ntn workers ...` |

## Armadilhas

- IDs de página/database são UUIDs (com ou sem hífen).
- Databases viraram **data sources** na versão 2025-09-03 da API — dois IDs diferentes, ver
  `references/api-http.md`.
- A API não configura filtro de view (só a interface faz isso).
- O Notion também tem um MCP server — se estiver conectado ao Okami, prefira ele pra sessões que
  precisam de acesso contínuo; os caminhos acima bastam pra tarefas pontuais.
