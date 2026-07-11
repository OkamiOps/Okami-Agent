# Harness e providers — modernização de 2026-07-11

## Resultado

Esta rodada entregou a fundação que estava faltando para tornar o harness cancelável e tirar o
LiteLLM do centro da arquitetura de providers. O gateway e o Telegram não fizeram parte desta
entrega.

O escopo foi encerrado após quatro blocos funcionais:

1. watchdog e cancelamento por request;
2. runtime targets imutáveis e resolver único;
3. registry de transports e fronteira explícita para LiteLLM;
4. fallback retrocompatível com destinos estruturados.

Streaming nativo de tool calls e histórico nativo atômico foram deliberadamente adiados. Isso
evitou transformar uma correção do núcleo em outra reconstrução interminável do projeto.

## O que mudou

### Harness

- `RequestContext` controla deadline total, TTFB, idle, cancelamento e aborters.
- O primeiro evento terminal vence a corrida e preserva tipo e motivo.
- Cada geração/escalada cria um contexto novo; retry e fallback internos compartilham o contexto
  da chamada atual.
- Cancelamento interrompe backoff e bloqueia classificação, compaction, escalada e fallback depois
  do terminal conhecido.
- Streaming observa progresso real, respeita o orçamento restante e fecha streams que expõem
  `close()`.
- Claude CLI, Codex OAuth, Copilot CLI, MiniMax OAuth, Google Code Assist, Bedrock e Gemini recebem
  limites compatíveis com seus transports.
- Adapters que não oferecem um handle físico de abort continuam limitados pelo timeout do
  transporte e expõem essa limitação; não fingem que mataram a operação remota.

### Providers e modelos

- `RuntimeTarget`, `TargetRef` e `BillingRoute` são imutáveis e seguros para retry, logs e
  metadados.
- `TargetResolver` centraliza aliases, override de modelo, transport, API mode, endpoint,
  capabilities, billing e referência de credencial.
- Segredos resolvidos não entram em `repr` de targets; apenas refs `env:`, `oauth:`, `pool:` ou
  identidade hash de uma chave literal.
- `ProviderConfig` preserva knobs futuros/desconhecidos em `params`, avisa uma vez por chave e
  rejeita colisões ambíguas.
- `TransportRegistry` conhece os transports existentes: `litellm`, `claude_cli`, `codex_oauth`,
  `minimax_oauth`, `gemini_native`, `bedrock_native`, `gemini_cloudcode` e `copilot_cli`.
- Todo uso executável de LiteLLM passa por `okami/llm/litellm_compat.py`; imports de providers não
  alteram `drop_params` nem `suppress_debug_info` globais.
- A política de parâmetros incompatíveis é local ao request: `warn` remove e registra os nomes;
  `error` falha explicitamente.
- Fallback legado continua válido. O formato estruturado preserva modelo, endpoint e API mode, e
  o `Completion` informa o provider/modelo efetivamente usado.

## Compatibilidade preservada

- YAML legado de providers e fallback por nome;
- aliases e IDs qualificados de modelos;
- transports CLI/OAuth e seus stores atuais;
- seam legado `transports.dispatch()` e callables injetados nos testes;
- retry, rotação de chaves, rate guard, replay de reasoning e aprovação de tools;
- comportamento de stream parcial: depois de emitir conteúdo, uma falha não reinicia silenciosamente
  a resposta e não duplica texto.

## Verificação

| Verificação | Resultado |
|---|---:|
| Testes novos de provider | `23 passed` |
| Matriz diretamente afetada do worker | `147 passed` |
| Reprodução order-dependent de logging | `3 passed` |
| Suíte completa final | `4059 passed, 13 skipped` |
| Ruff nos arquivos alterados | `All checks passed!` |
| `git diff --check` | limpo |
| Source gate de uso direto de LiteLLM | zero ocorrências |

A execução final da suíte completa levou 83,45 s. O Ruff do repositório inteiro ainda reporta 75
achados em arquivos não tocados por esta rodada; o conjunto alterado está limpo. Esse débito global
de lint não foi misturado com a modernização de providers.

## O que ainda falta

### Próxima prioridade funcional

1. gateway/Telegram: formatação, slash commands, troca de modelo e picker de provider/modelo;
2. onboarding e gestão de providers/credenciais inspirados no Hermes;
3. streaming estruturado de tool calls nativas;
4. histórico/compaction/resume com grupos nativos atômicos;
5. tornar LiteLLM opcional depois que todos os providers necessários tiverem adapters próprios.

### Resíduos técnicos conhecidos

- `_accepts_keyword` ainda merece endurecimento para parâmetros positional-only e alguns mocks com
  `side_effect` legado.
- Há uma janela estreita entre admissão do worker e invocação da função quando cancelamento externo
  é apenas consultado por callback.
- Uma segunda tentativa interna de Claude/Codex ainda pode receber o timeout numérico original em
  vez do deadline restante.
- Cancelamento que chega junto de uma geração inválida ou de `steer` precisa de uma regressão
  dedicada para provar que nenhuma recuperação extra é emitida.
- O bookkeeping legado de `_tried` ainda é por provider; múltiplos destinos estruturados distintos
  sob o mesmo provider não têm cobertura de execução sequencial nesta rodada.

Esses itens são reais, mas não invalidaram a suíte nem o caminho comum entregue. Devem entrar em
uma onda curta e orientada por regressão, não em outra auditoria aberta.

## Commits da rodada

- `3b8db16` — request-scoped cancellation watchdog;
- `d2b38eb` — cancelamento atômico e propagação pelos transports;
- `ded9a14` — runtime targets, transport registry, LiteLLM boundary e fallback estruturado.

Nenhum push foi executado.
