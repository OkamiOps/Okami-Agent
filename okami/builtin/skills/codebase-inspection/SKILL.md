---
name: codebase-inspection
description: Inspeciona um repositório com pygount — linhas de código, quebra por linguagem, contagem de arquivo, proporção código/comentário.
triggers: [linhas de código, loc, tamanho do repo, quebra por linguagem, quantas linhas tem, métrica de código, quão grande é esse repo]
intent_examples:
  - "quantas linhas de código tem esse projeto"
  - "faz uma quebra por linguagem desse repo"
  - "quão grande é essa base de código"
  - "qual a proporção de comentário nesse projeto"
metadata:
  hermes:
    tags: [LOC, code-analysis, pygount, codebase, metrics, repository]
    related_skills: []
    category: software-development
    ported_from: hermes-agent/skills/github/codebase-inspection
---

# Inspeção de codebase com pygount

Analisa repositórios pra ter linhas de código, quebra por linguagem, contagem de arquivo e
proporção código-vs-comentário usando `pygount`.

## Quando usar

- Dono pede contagem de LOC (linhas de código)
- Dono quer uma quebra por linguagem do repo
- Dono pergunta sobre tamanho ou composição da base de código
- Dono quer proporção código-vs-comentário
- Pergunta geral de "quão grande é esse repo"

## Pré-requisito

```bash
pip install --break-system-packages pygount 2>/dev/null || pip install pygount
```

Se `pip` não estiver disponível ou a instalação falhar (ambiente sem rede, por exemplo), caia
pra uma contagem manual com `find` + `wc -l` por extensão — menos precisa (não separa
código/comentário) mas não depende de instalar nada.

## 1. Resumo básico (o mais comum)

Pega a quebra completa por linguagem com contagem de arquivo, linhas de código e linhas de
comentário:

```bash
cd /caminho/do/repo
pygount --format=summary \
  --folders-to-skip=".git,node_modules,venv,.venv,__pycache__,.cache,dist,build,.next,.tox,.eggs,*.egg-info" \
  .
```

**IMPORTANTE:** sempre use `--folders-to-skip` pra excluir diretório de dependência/build, senão
o pygount vasculha tudo e demora muito ou trava.

## 2. Exclusões de pasta comuns

Ajuste conforme o tipo de projeto:

```bash
# Projetos Python
--folders-to-skip=".git,venv,.venv,__pycache__,.cache,dist,build,.tox,.eggs,.mypy_cache"

# Projetos JavaScript/TypeScript
--folders-to-skip=".git,node_modules,dist,build,.next,.cache,.turbo,coverage"

# Genérico
--folders-to-skip=".git,node_modules,venv,.venv,__pycache__,.cache,dist,build,.next,.tox,vendor,third_party"
```

## 3. Filtrar por linguagem específica

```bash
# Só arquivos Python
pygount --suffix=py --format=summary .

# Python e YAML
pygount --suffix=py,yaml,yml --format=summary .
```

## 4. Saída detalhada arquivo-por-arquivo

```bash
# Formato padrão mostra a quebra por arquivo
pygount --folders-to-skip=".git,node_modules,venv" .

# Ordena por linhas de código (via pipe pro sort)
pygount --folders-to-skip=".git,node_modules,venv" . | sort -t$'\t' -k1 -nr | head -20
```

## 5. Formatos de saída

```bash
# Tabela resumo (recomendação padrão)
pygount --format=summary .

# Saída JSON pra uso programático
pygount --format=json .

# Amigável pra pipe: Linguagem, contagem de arquivo, código, docs, vazio, string
pygount --format=summary . 2>/dev/null
```

## 6. Interpretando os resultados

Colunas da tabela resumo:
- **Language** — linguagem de programação detectada
- **Files** — número de arquivos daquela linguagem
- **Code** — linhas de código de fato (executável/declarativo)
- **Comment** — linhas de comentário ou documentação
- **%** — percentual do total

Pseudo-linguagens especiais:
- `__empty__` — arquivos vazios
- `__binary__` — arquivos binários (imagem, compilado, etc.)
- `__generated__` — arquivo auto-gerado (detectado heuristicamente)
- `__duplicate__` — arquivos com conteúdo idêntico
- `__unknown__` — tipo de arquivo não reconhecido

## Armadilhas

1. **Sempre exclua `.git`, `node_modules`, `venv`** — sem `--folders-to-skip`, o pygount vasculha
   tudo e pode demorar minutos ou travar em árvore de dependência grande.
2. **Markdown mostra 0 linhas de código** — pygount classifica todo conteúdo Markdown como
   comentário, não código. Isso é esperado.
3. **Arquivo JSON mostra contagem de código baixa** — pygount pode contar linha de JSON de forma
   conservadora. Para contagem precisa de linha JSON, use `wc -l` direto.
4. **Monorepo grande** — para repo muito grande, considere usar `--suffix` pra focar em
   linguagens específicas em vez de escanear tudo.
