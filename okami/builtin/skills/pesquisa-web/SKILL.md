---
name: pesquisa-web
description: Pesquisa profunda com método — múltiplas fontes, evidência rastreável, scripts p/ arXiv e Wikipedia/Wikidata.
triggers: [pesquisar, pesquisa, procurar na internet, buscar online, qual a última, notícia, cotação, preço atual, artigo científico, paper, arxiv, quem é]
intent_examples:
  - "pesquisa pra mim qual a versão mais nova disso"
  - "procura na internet o preço atual"
  - "vê as notícias sobre isso hoje"
  - "acha os papers mais recentes sobre isso no arxiv"
  - "investiga quem é essa pessoa/empresa, com fontes"
---
# Pesquisa na web

Para perguntas sobre fatos atuais, preços, versões, notícias, literatura acadêmica ou "quem é
essa entidade" — não responda de memória, busque e monte uma cadeia de evidência.

## Pesquisa geral (web_search / web_extract)

- Comece com `web_search` para mapear as fontes. Refine a query se os resultados vierem genéricos.
- Para o conteúdo real de uma página, use `web_extract` (resume) em vez de colar a página crua.
- Cruze pelo menos duas fontes independentes para qualquer afirmação que importe (número, data, fato).

## Pesquisa aprofundada (scripts stdlib, sem API key)

Pra pesquisa que precisa ir além do que `web_search` cobre bem — literatura acadêmica e
identificação/background de uma entidade (pessoa, empresa, lugar, conceito) — use os scripts
Python stdlib desta skill em `${OKAMI_SKILL_DIR}/scripts/`. Sem dependências externas, sem chave
de API.

### Literatura acadêmica (arXiv)

```bash
python3 ${OKAMI_SKILL_DIR}/scripts/search_arxiv.py "reinforcement learning from human feedback" --max 5
python3 ${OKAMI_SKILL_DIR}/scripts/search_arxiv.py --author "Yann LeCun" --sort date --max 5
python3 ${OKAMI_SKILL_DIR}/scripts/search_arxiv.py --id 2402.03300
```

Retorna título, autores, categorias, resumo e links (abstract + PDF) direto no stdout — cite o ID
arXiv e o link quando usar isso numa resposta.

### Identificação de entidade (Wikipedia + Wikidata)

Quando o usuário pergunta "quem é X" / "o que é a empresa Y" e precisa de background estruturado
(não só um resumo de uma frase), use:

```bash
python3 ${OKAMI_SKILL_DIR}/scripts/fetch_wikipedia.py --query "nome da entidade" --out /tmp/entidade.csv
```

Escreve um CSV com descrição, resumo, e fatos estruturados vindos do Wikidata (nascimento,
empregador, ocupação, país — quando existirem). Leia o CSV de volta (`read_file` ou similar) pra
compor a resposta. `--no-wikidata` pula o enriquecimento estruturado se só precisar do resumo
(mais rápido). Vazio no CSV normalmente significa que a entidade não é notável o bastante pra ter
verbete — diga isso ao usuário em vez de inventar.

Este é o mesmo padrão de investigação por fontes públicas (busca → resolve a entidade → junta fatos
estruturados → cita a fonte) usado em frameworks OSINT mais pesados — aqui simplificado pro caso
geral de "me dá o histórico verificável dessa entidade", sem os módulos de registro
financeiro/jurídico que só fazem sentido em due diligence corporativa dedicada.

## Cuidados

- Confira a DATA da fonte. Conteúdo desatualizado é a armadilha mais comum em preço/versão/notícia.
- Desconfie de uma fonte só, de conteúdo patrocinado e de página que não bate com as outras.
- Se as fontes divergem, diga isso ao usuário em vez de escolher uma e fingir certeza.
- Os endpoints do arXiv/Wikipedia/Wikidata são públicos mas têm rate-limit — não faça looping
  agressivo; se um script levantar erro de HTTP 429, espere antes de repetir.

## Ao responder

- Cite de onde veio cada afirmação relevante (nome da fonte e, se útil, o link ou ID — ex.: arXiv
  ID, URL da Wikipedia, QID do Wikidata).
- Separe o que é fato verificado do que é estimativa ou opinião.
- Diga explicitamente quando NÃO achou resposta confiável — melhor que inventar.
