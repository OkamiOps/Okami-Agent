---
name: pesquisa-web
description: Pesquisar na web com método — múltiplas fontes, conferir datas, citar de onde veio cada afirmação.
triggers: [pesquisar, pesquisa, procurar na internet, buscar online, qual a última, notícia, cotação, preço atual]
intent_examples:
  - "pesquisa pra mim qual a versão mais nova disso"
  - "procura na internet o preço atual"
  - "vê as notícias sobre isso hoje"
---
# Pesquisa na web

Para perguntas sobre fatos atuais, preços, versões ou notícias — não responda de memória, busque.

## Como pesquisar
- Comece com `web_search` para mapear as fontes. Refine a query se os resultados vierem genéricos.
- Para o conteúdo real de uma página, use `web_extract` (resume) em vez de colar a página crua.
- Cruze pelo menos duas fontes independentes para qualquer afirmação que importe (número, data, fato).

## Cuidados
- Confira a DATA da fonte. Conteúdo desatualizado é a armadilha mais comum em preço/versão/notícia.
- Desconfie de uma fonte só, de conteúdo patrocinado e de página que não bate com as outras.
- Se as fontes divergem, diga isso ao usuário em vez de escolher uma e fingir certeza.

## Ao responder
- Cite de onde veio cada afirmação relevante (nome da fonte e, se útil, o link).
- Separe o que é fato verificado do que é estimativa ou opinião.
- Diga explicitamente quando NÃO achou resposta confiável — melhor que inventar.
