---
name: tdd
description: Test-Driven Development — escreve o teste antes do código e itera até passar.
triggers: [tdd, teste, testes, test, unit, pytest, jest, vitest, cobertura, bug, corrigir]
---
# TDD — teste primeiro

Use ao implementar feature ou corrigir bug em projeto com testes.

## Ciclo Red → Green → Refactor
1. **Red**: escreva um teste que falha descrevendo o comportamento esperado. Rode e veja falhar.
2. **Green**: escreva o MÍNIMO de código para o teste passar. Rode e veja passar.
3. **Refactor**: limpe o código mantendo os testes verdes.

## Para bug
- Primeiro escreva um teste que REPRODUZ o bug (falha). Depois conserte até passar. Isso evita regressão.

## Regras
- Não declare `task_complete` sem rodar a suíte. Use o critério de saída `shell_ok` com o comando
  de teste do projeto (ex.: `pytest -q`, `npm test`).
- Um teste por comportamento; nomes descritivos.

## Conclusão (verificável)
- [ ] Existe teste novo cobrindo a mudança.
- [ ] `shell_ok` da suíte passa.
