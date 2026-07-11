# Harness, providers e Telegram — fechamento de 2026-07-11

## Resultado

A rodada foi fechada contra o snapshot recente do Hermes em `3b2ef789d`, usando subagentes
`gpt-5.6-luna` com reasoning `high`. O escopo ficou restrito aos caminhos que estavam realmente
faltando: streaming estruturado, histórico nativo atômico, cancelamento/timeout, gestão básica de
providers/modelos no Telegram e limpeza do lint existente.

LiteLLM deixou de ser o centro da arquitetura, mas continua disponível como transport de
compatibilidade. Não copiamos a arquitetura inteira do Hermes nem abrimos outra reconstrução do
gateway.

## O que ficou pronto

### Harness e protocolo nativo

- `RequestContext` controla deadline total, TTFB, idle, cancelamento e aborters por request.
- Cancelamento é verificado antes da admissão, depois da geração e antes de recuperação, compaction,
  escalada ou fallback.
- Retries de Claude e Codex recebem o tempo restante do deadline, não um timeout novo completo.
- `_accepts_keyword` respeita parâmetros positional-only e doubles/mocks usados pela suíte.
- `StreamEvent`, `ToolCallDelta` e `NativeToolCallAccumulator` reconstroem tool calls recebidas em
  deltas estruturados.
- `stream_messages_events()` e `streaming_generate()` preservam texto, reasoning, usage e tool calls
  nativas sem converter a ação para JSON-em-texto.
- Mensagens `assistant.tool_calls` e seus resultados `role=tool` formam grupos atômicos no histórico.
- Resume repara tool calls órfãs como `INTERRUPTED`, sem reexecutá-las silenciosamente.
- Compaction preserva os grupos assistant/tool; não separa uma chamada do respectivo resultado.
- Um terminal rejeitado recebe exatamente um resultado `REJECTED`; um terminal aceito fecha chamadas
  pendentes do mesmo lote como não executadas, evitando IDs órfãos.
- Fallback estruturado distingue destinos com o mesmo provider e modelos diferentes.

### Providers e modelos

- `RuntimeTarget`, `TargetRef`, `BillingRoute`, `TargetResolver` e `TransportRegistry` formam a
  fronteira única entre configuração e execução.
- Aliases, override de modelo, transport, API mode, endpoint, capabilities, billing e credencial são
  resolvidos no mesmo caminho.
- Targets não carregam segredo resolvido; logs e UX mostram somente referências seguras como `env:`
  e `oauth:`.
- Todo uso executável de LiteLLM passa por `okami/llm/litellm_compat.py`, sem mutação global no import.
- Fallback legado por nome continua aceito; destinos estruturados preservam provider, modelo,
  endpoint e modo de API efetivamente usados.
- O preset de provider customizado grava `transport: litellm` explicitamente e o resumo final mostra
  endpoint, transport e referência de variável de ambiente sem exibir o segredo.

### Telegram

- `/providers` entrou no registry, menu e catálogo PT.
- O comando exibe estado seguro dos providers configurados.
- `/model` ganhou picker inline de modelos.
- Callbacks curtos (`okmodel:N`) não carregam provider/modelo arbitrário enviado pelo cliente.
- Cada índice é validado contra um catálogo em memória associado ao chat; índice inválido é ignorado.
- A seleção reutiliza o mesmo resolver e a mesma persistência de sessão do comando `/model
  provider/model`.

### Qualidade

- Os 75 achados preexistentes do Ruff foram corrigidos mecanicamente, sem refatoração funcional.
- Ruff agora passa no repositório inteiro.

## Verificação final

| Verificação | Resultado |
|---|---:|
| Matriz focada de providers/Telegram | `255 passed` |
| Regressões do fechamento de tool calls | `55 passed` |
| Correções de integração PT/streaming | `2 passed` |
| Suíte completa final | `4075 passed, 13 skipped` |
| `uv run ruff check okami tests` | `All checks passed!` |
| `git diff --check` | limpo |

A suíte completa final levou 81,09 s. A primeira execução integrada encontrou duas regressões
legítimas — tradução ausente de `/providers` e um teste acoplado ao texto da implementação antiga de
streaming. Ambas foram corrigidas por um Luna em `high`; a segunda execução ficou totalmente verde.

## O que deliberadamente não entrou

- remoção total da dependência opcional de LiteLLM; isso exige adapters nativos para todos os
  providers que o projeto pretende suportar;
- catálogo gigantesco de providers do Hermes e descoberta automática de todas as suas integrações;
- picker hierárquico/paginado para centenas de modelos; o picker atual cobre o catálogo configurado;
- paridade do Discord e reescrita dos demais gateways; esta rodada tratou Telegram;
- cópia da arquitetura assíncrona completa do Hermes.

Esses pontos são melhorias futuras, não buracos escondidos no caminho entregue. Copiá-los agora teria
voltado ao overengineering que esta rodada precisava interromper.

## Limitações reais

- Transport sem handle físico de abort só pode respeitar o timeout/cancelamento na fronteira local;
  não há como prometer que uma operação remota já enviada foi morta.
- Um callback externo de cancelamento é consultivo; o harness consulta imediatamente antes da
  execução, mas atomicidade absoluta exige que o próprio transport exponha cancelamento cooperativo.
- Catálogos muito grandes ainda pedem paginação no Telegram.

## Commits da rodada

- `3b8db16` — watchdog de cancelamento por request;
- `d2b38eb` — cancelamento atômico e propagação nos transports;
- `ded9a14` — runtime targets, registry e fronteira LiteLLM;
- `48602ba` — Ruff zerado no repositório;
- `360e2f5` — picker seguro e UX de providers no Telegram;
- `5438aad` — streaming nativo e histórico atômico;
- `feba6f3` — tradução de providers e teste do fallback atualizados.

Nenhum push foi executado.
