---
name: simplify-code
description: Limpeza paralela de mudanças recentes de código — três revisores focados (reuso, qualidade, eficiência) rodando em paralelo, achados agregados e correções aplicadas por nível de risco.
triggers: [simplifica, simplificar, revisa meu código, revisa minhas mudanças, limpa o código, limpa minhas mudanças, simplify, code cleanup]
intent_examples:
  - "simplifica essas mudanças"
  - "revisa meu código antes de eu commitar"
  - "dá uma limpada nesse diff"
  - "simplifica focando em eficiência"
  - "só reporta, não muda nada ainda"
metadata:
  hermes:
    tags: [code-review, cleanup, refactor, delegation, subagent, parallel, simplify]
    related_skills: [requesting-code-review, depuracao-sistematica]
    category: software-development
    ported_from: hermes-agent/skills/software-development/simplify-code
---

# Simplify Code — revisão e limpeza em paralelo

Revisa as mudanças de código recentes com três revisores focados rodando em paralelo, agrega os
achados e aplica as correções que valem a pena.

**Princípio central:** três revisores estreitos batem um revisor amplo. Cada um vasculha a fundo
o código em busca de UMA classe de problema — reuso, qualidade, eficiência — sem diluir a atenção
entre os três. Rodam concorrentemente, então você paga a latência de um review, não de três.

## Quando usar

Dispare esta skill quando o dono disser algo como:

- "simplifica" / "simplifica minhas mudanças" / "simplifica esse diff"
- "revisa meu código" / "revisa minhas mudanças recentes" / "limpa minhas mudanças"
- "/simplify" (hábito trazido do Claude Code)

Modificadores opcionais que o dono pode adicionar — respeite-os:

- **Foco:** "simplifica focando em eficiência" → rode só o revisor de eficiência (ou pese a
  agregação nessa direção). Focos reconhecidos: `reuso`, `qualidade`, `eficiência`.
- **Dry run:** "simplifica mas não muda nada" / "só reporta" → rode os três revisores, apresente
  os achados, aplique NADA. Pergunte antes de aplicar.
- **Escopo:** "simplifica o último commit" / "simplifica o staged" / "simplifica src/foo.py" →
  restrinja a fonte do diff de acordo (ver Fase 1).

NÃO rode isso automaticamente depois de cada edição. Custa o equivalente a três subagentes de
tokens — invoque só quando o dono pedir explicitamente.

## O processo

### Fase 1 — Identificar as mudanças

Capture o diff a revisar. Escolha a fonte pelo que o dono pediu, nesta ordem padrão:

```bash
# 1. Padrão: mudanças não commitadas na working tree (arquivos rastreados)
git diff

# 2. Se vazio, inclua mudanças staged
git diff HEAD

# 3. Variantes de escopo que o dono pode pedir:
git diff --staged                 # "mudanças staged"
git diff HEAD~1                    # "o último commit"
git diff main...HEAD              # "essa branch" / "meu PR"
git diff -- src/foo.py            # arquivo(s) específico(s)
```

Se `git diff` e `git diff HEAD` estiverem ambos vazios e não houver repo git ou mudanças, use os
arquivos que o dono nomeou explicitamente ou que foram criados/editados recentemente nesta sessão.
Se genuinamente não achar nada mudado, diga isso e pare — não há o que simplificar.

Capture o texto completo do diff. Note o tamanho: se for muito grande (>2000 linhas mudadas),
avise o dono que três subagentes carregando o diff inteiro sai caro em token, e ofereça escopar
(por diretório, por commit) antes de prosseguir.

### Fase 2 — Lança três revisores em paralelo

Use o modo batch do `Agent` (dispatching-parallel-agents) — mande as três tarefas numa única
leva para rodarem concorrentemente. Três é o fan-out certo pra esse padrão.

Dê a **cada** revisor o **diff completo** (não fragmentos — problemas cross-file se escondem nas
lacunas) mais o caminho absoluto do repo pra poder buscar no código mais amplo (Grep/Read/Bash).

Diga a cada revisor para:
- Buscar evidência no código existente (não raciocinar só a partir do diff).
- **Aplicar a Cerca de Chesterton:** antes de marcar algo pra remoção, rode `git blame` na linha
  pra entender por que ela existe. Se não conseguir determinar o propósito original, marque
  `confidence: low` — não chute.
- Reportar achados em formato estruturado com confiança e risco:
  ```
  arquivo:linha → problema → correção sugerida | confidence: high/medium/low | risk: SAFE/CAREFUL/RISKY
  ```
  - **SAFE** = provado que não afeta comportamento (imports não usados, código comentado,
    wrappers pass-through). Aplique automaticamente.
  - **CAREFUL** = melhora sem mudar semântica (renomear variável local, achatar ternário
    aninhado, extrair helper). Aplique com verificação por teste.
  - **RISKY** = pode mudar comportamento ou quebra contratos públicos (reestruturação de N+1,
    rename de API pública, mudança de ciclo de vida de memória). Sinalize pra revisão humana —
    NÃO aplique automaticamente.
- Pular nitpicks e churn de estilo puro. Só sinalizar coisas que melhoram materialmente o código.

Passe estes três objetivos (retire o que o foco do dono excluir):

**Revisor 1 — Reuso de código**
> Revise este diff em busca de código que duplica funcionalidade já existente no projeto. Busque
> em módulos utilitários, helpers compartilhados e arquivos vizinhos (grep/busca) por funções,
> constantes ou padrões existentes que o código novo poderia usar em vez de reimplementar.
> Sinalize: funções novas que duplicam existentes; lógica feita à mão que um utilitário já cobre
> (manipulação manual de string/path, checagem de env ad-hoc, type guard improvisado, parsing
> reimplementado). Para cada achado, nomeie a coisa existente e onde ela está.

**Revisor 2 — Qualidade de código**
> Revise este diff em busca de problemas de qualidade. Procure: estado redundante (valores que
> duplicam ou poderiam ser derivados de estado existente; caches desnecessários); explosão de
> parâmetros (parâmetros novos parafusados onde a função deveria ter sido reestruturada);
> copy-paste-com-variação (blocos quase-duplicados que deveriam compartilhar uma abstração);
> abstrações vazadas (expõe internals, quebra encapsulamento existente); código stringly-typed
> (strings cruas onde já existe constante/enum/registry canônico — confira antes de sinalizar);
> padrões de "slop" gerado por IA (comentário óbvio tipo `# incrementa contador` acima de
> `count += 1`; null-check defensivo desnecessário em input já validado; cast que furou o
> type system; padrões inconsistentes com o resto do arquivo). Para cada achado, dê o refactor
> concreto.

**Revisor 3 — Eficiência**
> Revise este diff em busca de problemas de eficiência. Procure: trabalho desnecessário (cálculo
> redundante, leitura repetida de arquivo, chamada de API duplicada, padrão N+1); concorrência
> perdida (operações independentes rodando sequencialmente); inchaço em hot-path (trabalho
> pesado/bloqueante no startup ou por-request); anti-padrão TOCTOU (checagem de existência antes
> de uma operação em vez de tentar e tratar o erro); problemas de memória (crescimento sem limite,
> falta de cleanup, listener/handle vazando); leitura ampla demais (carregar arquivo inteiro
> quando um trecho bastaria); falha silenciosa (catch vazio, erro ignorado, `except: pass`,
> `.catch(() => {})` sem tratamento — isso esconde bug e deveria pelo menos logar antes de
> engolir). Para cada achado, dê a correção concreta e por que ela é mais rápida ou mais segura.

### Fase 3 — Agregar e aplicar

Espere os três retornarem (batch retorna juntos).

1. **Mescle** os achados numa lista única, deduplicando onde os revisores se sobrepõem.
2. **Descarte falsos positivos** — você tem mais contexto; não precisa discutir com o revisor,
   só derrube sugestão fraca ou errada em silêncio.
3. **Resolva conflitos.** Revisores podem discordar (Revisor 1: "usa o util X existente";
   Revisor 3: "X é lento, faz inline"). Ordem de resolução padrão: **correção > foco declarado
   pelo dono > legibilidade/reuso > micro-perf.** Não aplique uma "correção" de perf que piora
   clareza a menos que o path seja de fato quente. Quando duas sugestões se excluem e ambas fazem
   sentido, escolha a que mexe em menos código e anote a alternativa.
4. **Aplique em ordem de nível de risco:**
   - **SAFE primeiro** (auto-aplica): imports não usados, código comentado, wrappers
     pass-through, asserções de tipo redundantes. Rode os testes depois.
   - **CAREFUL em seguida** (aplica com verificação, um arquivo por vez): renomear locais,
     achatar ternários, extrair helpers, consolidar duplicatas. Rode os testes depois de cada
     arquivo. Reverta o que quebrar.
   - **RISKY por último** (sinaliza pra revisão — NÃO auto-aplica): reestruturação N+1, mudança
     de API pública, correção de concorrência, mudança de tratamento de erro. Apresente cada um
     com descrição de risco e status de cobertura de teste.
   Se o dono pediu dry run, apresente as três camadas e não aplique nada.
5. **Verifique** que nada quebrou: rode os testes do projeto voltados aos arquivos tocados (não a
   suíte inteira), e rode de novo qualquer linter/type check que o repo usa. Se uma correção
   quebrar um teste, reverta só ela e reporte.
6. **Resuma** o que mudou: lista curta das correções aplicadas agrupadas por categoria de revisor
   e nível de risco, mais os achados que você deliberadamente pulou e por quê.

## Armadilhas

- **Não amplie o fan-out além de ~3.** Mais revisores é mais custo e mais conflito pra
  reconciliar, não mais cobertura. Três categorias cobrem o espaço.
- **Dê o diff INTEIRO pra cada revisor.** Dividir o diff entre revisores derrota o desenho —
  duplicação cross-file e N+1 só aparecem com o quadro completo.
- **Revisores buscam, não chutam.** Um achado de reuso sem apontar pro utilitário existente
  ("provavelmente tem um helper pra isso") é ruído. Exija evidência `arquivo:linha`; descarte
  achados sem ela.
- **Aplicar ≠ reescrever.** Isto é limpeza das mudanças recentes do dono, não licença pra
  refatorar o módulo inteiro. Mantenha as edições no que o diff tocou mais o mínimo de mudança ao
  redor que uma correção exige.
- **Respeite as convenções do projeto.** Se o repo tem AGENTS.md / CLAUDE.md / OKAMI.md ou config
  de linter, incorpore essas regras nos prompts dos revisores pra sugestão bater com o estilo da
  casa em vez de brigar com ele.
- **Diff enorme estoura contexto.** Se o diff for gigante, escope antes de delegar — três
  subagentes carregando um diff de 5000 linhas cada é caro e pode truncar.
- **Confiar demais em ferramenta de dead-code.** `knip`, `ts-prune`, `depcheck` sinalizam exports
  que SÃO usados dinamicamente (import por string, reflection). Sempre faça grep do nome do
  símbolo antes de remover — relatório limpo da ferramenta não é prova.
- **Renomear sem checar contrato público.** Nome de export, rota de API, nome de coluna de banco,
  chave de config são contratos — mesmo que o nome seja ruim, renomear quebra consumidor. Marque
  mudança de contrato público como RISKY; nunca auto-renomeie.
- **Remover tratamento de erro "desnecessário".** Um catch vazio ou erro ignorado pode ser
  intencional — o erro é esperado e benigno naquele contexto. Sinalize, não remova; deixe o
  humano decidir.

## Relacionado

Use `requesting-code-review` para o gate de segurança/qualidade pré-commit — esta skill é a
limpeza *depois do fato*, aquela é a verificação *antes de commitar*. Para achar a causa-raiz de
um bug antes de qualquer correção, veja `depuracao-sistematica`.
