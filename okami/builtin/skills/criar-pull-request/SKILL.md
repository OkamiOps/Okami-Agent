---
name: criar-pull-request
description: Abrir um Pull Request bem-feito — branch, commits atômicos, descrição clara e gh pr create.
triggers: [pull request, pr, abrir pr, criar pr, mandar pra revisão, subir as mudanças, open pr]
intent_examples:
  - "abre um PR com essas mudanças"
  - "manda isso pra revisão"
  - "cria o pull request"
---
# Abrir um Pull Request

Procedimento para transformar mudanças locais num PR limpo e revisável.

## Antes de abrir
- Confirme o que mudou: revise o diff inteiro (`git diff` e `git status`), não confie de memória.
- Garanta verde: rode os testes e o lint relevantes. PR que quebra o CI volta — verifique antes.
- Nunca trabalhe direto na branch padrão. Crie uma branch com nome curto e descritivo
  (ex.: `fix/telegram-typing`, `feat/native-skills`).

## Commits
- Commits atômicos: cada commit é uma mudança coerente que compila/passa sozinha.
- Mensagem no imperativo, explicando o PORQUÊ, não só o quê. Assunto curto; corpo se precisar.

## O PR em si
- Use `gh pr create` com título claro e um corpo que diga: o problema, a abordagem, e como testar.
- Liste o que NÃO foi feito de propósito (escopo) para o revisor não procurar pelo que falta.
- Se há decisão de design não óbvia, explique a alternativa descartada e por quê.

## Depois
- Releia o próprio PR como se fosse o revisor: ruído, código morto, TODO esquecido.
- Responda o link do PR pra pessoa. Não faça merge sem pedido explícito.
