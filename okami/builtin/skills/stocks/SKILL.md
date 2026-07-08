---
name: stocks
description: Cotação de ações/cripto, histórico, busca e comparação — via Yahoo Finance, sem API key.
triggers: [ação, ações, bolsa, cotação, cripto, bitcoin, preço da ação, dólar, mercado financeiro]
intent_examples:
  - "qual a cotação da AAPL agora"
  - "compara TSLA com MSFT pra mim"
  - "histórico da NVDA nos últimos 6 meses"
  - "preço do bitcoin hoje"
metadata:
  hermes:
    tags: [stocks, finance, market, crypto, investing]
    category: finance
---
# Cotações e mercado (stocks)

Dados de mercado read-only via Yahoo Finance. Python stdlib puro — sem API key, sem pip install.
Endpoint é não-oficial: pode ficar instável ou mudar sem aviso — se falhar, tente de novo antes de
concluir que o script está quebrado.

## Como rodar

```
python3 ${OKAMI_SKILL_DIR}/scripts/stocks_client.py quote AAPL
```

Saída é sempre JSON no stdout.

## Comandos

```
python3 $SCRIPT quote AAPL                  # cotação atual (aceita vários símbolos)
python3 $SCRIPT quote AAPL MSFT GOOGL TSLA
python3 $SCRIPT search "Tesla"              # busca por nome → top 5 tickers
python3 $SCRIPT history NVDA --range 6mo    # OHLCV diário + estatísticas (1mo/3mo/6mo/1y/5y)
python3 $SCRIPT compare AAPL MSFT GOOGL     # lado a lado: preço, variação%, desempenho 52 semanas
python3 $SCRIPT crypto BTC ETH SOL          # cripto (adiciona -USD automaticamente)
```

## Enriquecimento opcional

Definindo `ALPHA_VANTAGE_KEY` no ambiente, `quote`/`compare` preenchem `market_cap`/`pe_ratio`/
52-semanas quando o Yahoo devolve nulo (proteção de sessão). Chave gratuita em
alphavantage.co — nunca peça isso ao usuário sem necessidade, é só um fallback.

## Cuidados

- Read-only: nenhuma ordem é enviada, nenhuma conta é acessada. Nunca extrapole para execução de trade.
- Deixe um pequeno intervalo entre chamadas em lote pra não tomar rate-limit.
- `market_cap`/`pe_ratio` podem vir `null` no `quote` — normal, não é bug.
- Ao responder ao usuário, deixe claro que é cotação de mercado (pode ter atraso) e cite a fonte.
