---
name: obsidian
description: Lê, busca, cria e edita notas no vault do Obsidian usando as tools de arquivo do Okami (não shell) — caminho do vault resolvido antes de qualquer chamada.
triggers: [obsidian, vault, nota, anotação, wikilink, minhas notas]
intent_examples:
  - "cria uma nota nova no meu vault do obsidian sobre essa reunião"
  - "busca nas minhas notas do obsidian por 'roadmap'"
  - "lê a nota sobre o projeto X"
  - "adiciona um link pra essa outra nota"
  - "lista as notas dessa pasta do vault"
metadata:
  hermes:
    tags: [obsidian, notes, vault, markdown, knowledge-base]
    category: productivity
    ported_from: hermes obsidian skill
---

# Vault do Obsidian

Use esta skill pra trabalho local no vault do Obsidian: ler nota, listar nota, buscar conteúdo,
criar nota, acrescentar conteúdo, adicionar wikilink. Tudo via sistema de arquivos — o Obsidian em
si não precisa estar aberto.

## Caminho do vault

Resolva um caminho conhecido antes de chamar qualquer tool de arquivo.

A convenção documentada é a variável de ambiente `OBSIDIAN_VAULT_PATH`, guardada por exemplo em
`$OKAMI_HOME/.env`. Se não estiver definida, use `~/Documents/Obsidian Vault` como fallback.

As tools de arquivo não expandem variável de shell. Não passe caminhos contendo
`$OBSIDIAN_VAULT_PATH` literal pra `read_file`, `write_file`, `patch` ou `search_files` — resolva o
caminho do vault primeiro e passe um caminho absoluto concreto. Caminho de vault pode ter espaço,
mais um motivo pra preferir as tools de arquivo em vez de comando de shell.

Se o caminho do vault for desconhecido, um comando de terminal é aceitável só pra resolver
`OBSIDIAN_VAULT_PATH` ou checar se o caminho de fallback existe. Assim que souber o caminho, volte
pras tools de arquivo.

## Ler uma nota

Use `read_file` com o caminho absoluto resolvido da nota. Prefira isso a `cat` porque devolve
número de linha e paginação.

## Listar notas

Use `search_files` com `target: "files"` e o caminho resolvido do vault. Prefira isso a `find` ou
`ls`.

- Pra listar todas as notas markdown, use `pattern: "*.md"` sob o caminho do vault.
- Pra listar uma subpasta, busque sob o caminho absoluto dessa subpasta.

## Buscar

Use `search_files` tanto pra nome de arquivo quanto pra conteúdo. Prefira isso a `grep`, `find` ou
`ls`.

- Pra nome de arquivo, use `search_files` com `target: "files"` e um `pattern` de nome.
- Pro conteúdo da nota, use `search_files` com `target: "content"`, o regex de conteúdo como
  `pattern`, e `file_glob: "*.md"` quando quiser restringir a match a notas markdown.

## Criar uma nota

Use `write_file` com o caminho absoluto resolvido e o conteúdo markdown completo. Prefira isso a
heredoc de shell ou `echo` porque evita problema de quoting e devolve resultado estruturado.

## Acrescentar a uma nota

Prefira um fluxo com tool de arquivo nativa quando não ficar estranho:

- Leia a nota alvo com `read_file`.
- Use `patch` pra um append ancorado quando houver contexto estável, tipo adicionar uma seção
  depois de um heading existente ou acrescentar antes de um bloco final conhecido.
- Use `write_file` quando reescrever a nota inteira for mais claro que montar um patch frágil.

Pra um append ancorado com `patch`, substitua a âncora pela âncora mais o conteúdo novo.

Pra um append simples sem contexto estável, um comando de terminal é aceitável se for a opção
segura mais clara.

## Edições pontuais

Use `patch` pra mudanças focadas na nota quando o conteúdo atual dá contexto estável. Prefira isso
a reescrita de texto via shell.

## Wikilinks

O Obsidian liga notas com a sintaxe `[[Nome da Nota]]`. Ao criar nota, use isso pra linkar
conteúdo relacionado.
