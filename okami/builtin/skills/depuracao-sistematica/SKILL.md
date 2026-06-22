---
name: depuracao-sistematica
description: Achar a causa-raiz ANTES de corrigir — reproduzir, rastrear o dado, testar uma hipótese por vez.
triggers: [bug, erro, não funciona, quebrou, falha, depurar, debug, investigar erro, stack trace]
intent_examples:
  - "tá dando erro aqui, vê o que é"
  - "isso não funciona, descobre o porquê"
  - "o teste quebrou, conserta"
---
# Depuração sistemática

Correção no chute desperdiça tempo e cria bug novo. Ache a causa-raiz primeiro.

## 1. Entender antes de mexer
- Leia a mensagem de erro INTEIRA, incluindo o stack trace — ela costuma conter a resposta.
- Reproduza de forma confiável. Se não reproduz, junte mais dados; não adivinhe.
- O que mudou? Olhe o diff/commits recentes, dependências novas, diferença de ambiente.

## 2. Rastrear o dado até a origem
- De onde vem o valor errado? Quem chamou com ele? Suba a pilha até a fonte.
- Em sistema multicamada, instrumente cada fronteira (o que entra, o que sai) e rode UMA vez
  para ver ONDE quebra, antes de propor conserto.

## 3. Uma hipótese por vez
- Escreva a hipótese: "acho que X é a causa porque Y".
- Faça a MENOR mudança que testa a hipótese. Não conserte cinco coisas de uma vez.
- Não funcionou? Nova hipótese — não empilhe correções por cima.

## 4. Corrigir a raiz, não o sintoma
- Antes de corrigir, escreva um teste que FALHA reproduzindo o bug. Depois conserte até passar.
- Se 3+ tentativas falharam, o problema provavelmente é a arquitetura, não a hipótese — pare e repense.
