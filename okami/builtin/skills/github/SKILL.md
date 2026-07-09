---
name: github
description: Ciclo de vida GitHub além do PR — CI/checks, auto-fix de falha, merge, issues. gh primeiro, script stdlib como plano B.
triggers: [github, ci, checks, actions, workflow, issue, merge, auto-fix, pipeline quebrado, esperar o ci]
intent_examples:
  - "verifica se o CI passou nesse PR"
  - "o pipeline quebrou, conserta e sobe de novo"
  - "espera o CI terminar e faz o merge"
  - "abre uma issue pra isso"
  - "lista minhas issues abertas nesse repo"
metadata:
  hermes:
    tags: [github, pull-requests, ci-cd, git, automation, merge, issues]
    category: devops
---
# GitHub — CI, merge e issues

Complementa a skill `criar-pull-request` (procedimento de ABRIR um PR bem-feito — branch, commits
atômicos, `gh pr create`). Esta skill cobre o resto do ciclo: checagem de CI, auto-fix de falha,
merge e o essencial de issues. Sempre prefira o CLI `gh` quando disponível — se não estiver
instalado (comum em VPS provisionada do zero), use o script `${OKAMI_SKILL_DIR}/scripts/gh_api.py`,
que fala com a API REST do GitHub direto via stdlib (sem depender de `gh`).

## Quando usar

- Verificar/esperar o CI de um PR ou branch.
- Diagnosticar e consertar falha de CI (loop de auto-fix).
- Fazer merge de um PR já aprovado.
- Abrir, listar, comentar ou fechar issues.
- Qualquer coisa de GitHub que NÃO seja "abrir o PR em si" (isso é a `criar-pull-request`).

## Credencial

Autenticação (para o `gh` ou para o script de fallback) segue esta ordem: variável já exportada no
shell → `$OKAMI_HOME/.env` (default `~/.okami/.env`, o mesmo lugar dos outros segredos globais do
Okami) → `~/.git-credentials` (o que o próprio `git` já tiver em cache). Sem credencial, as
chamadas de leitura ainda funcionam (rate limit anônimo mais baixo); operações de escrita
(merge, criar issue, comentar) exigem credencial configurada.

Essa é a lista FECHADA de onde procurar — não vá além dela. Se nenhuma das três tiver o token,
NÃO vasculhe outros arquivos do disco (perfil de browser, chaveiro do sistema, config de outra
CLI) atrás de credencial: peça ao dono um token pelo canal seguro e guarde com `store_secret`
(veja a skill `acesso-vps` para o fluxo completo). Nunca proponha `--yolo`/bypass de sandbox pra
contornar a falta de acesso.

## Checar/esperar o CI

Com `gh`:
```bash
gh pr checks               # um snapshot
gh pr checks --watch       # espera até fechar (poll a cada 10s)
gh run list --branch "$(git branch --show-current)" --limit 5
gh run view <RUN_ID> --log-failed
```

Sem `gh` (fallback):
```bash
python3 ${OKAMI_SKILL_DIR}/scripts/gh_api.py ci-status --sha "$(git rev-parse HEAD)"
```
Omitir `--owner`/`--repo` faz o script deduzir do remote `origin` do diretório atual. Devolve o
status de cada check em JSON — se algum vier `conclusion: failure`, siga pro loop de auto-fix.

## Loop de auto-fix quando o CI quebra

1. Checa o status → identifica o(s) check(s) que falhou.
2. Pega o log da falha (`gh run view <ID> --log-failed`; sem `gh`, baixe o log pelo endpoint de
   runs da API e leia o texto) → entende o erro de verdade, não adivinha.
3. Usa as ferramentas de arquivo (`read_file`/`edit`) pra corrigir a causa raiz — não silencia o teste.
4. `git add . && git commit -m "fix: ..." && git push`
5. Espera o CI de novo e reconfere.
6. Repete até 3 tentativas; se continuar quebrado, para e explica pro usuário o que já tentou — não
   fica em loop infinito adivinhando.

## Merge

Com `gh`:
```bash
gh pr merge --squash --delete-branch          # squash + apaga a branch (padrão pra feature branch)
gh pr merge --auto --squash --delete-branch   # auto-merge quando os checks fecharem verde
```

Sem `gh` (fallback):
```bash
python3 ${OKAMI_SKILL_DIR}/scripts/gh_api.py pr-merge --number <N> --method squash
git push origin --delete "$(git branch --show-current)"   # limpa a branch remota depois do merge
```

Nunca faça merge sem o usuário ter pedido — assim como a `criar-pull-request` não abre PR sozinha
sem contexto, esta skill não faz merge por conta própria a menos que peçam explicitamente.

## Issues (essencial)

Com `gh`:
```bash
gh issue create --title "título" --body "descrição"
gh issue list --state open --limit 20
gh issue comment <N> --body "comentário"
gh issue close <N>
```

Sem `gh` (fallback, mesmos verbos):
```bash
python3 ${OKAMI_SKILL_DIR}/scripts/gh_api.py issue-create --title "título" --body "descrição"
python3 ${OKAMI_SKILL_DIR}/scripts/gh_api.py issue-list --state open
python3 ${OKAMI_SKILL_DIR}/scripts/gh_api.py issue-comment --number <N> --body "comentário"
python3 ${OKAMI_SKILL_DIR}/scripts/gh_api.py issue-close --number <N>
```

## Referência rápida

| Ação | `gh` | fallback stdlib |
|---|---|---|
| Minhas PRs abertas | `gh pr list --author @me` | `gh_api.py pr-list --state open` |
| Diff do PR | `gh pr diff` | `git diff main...HEAD` (local) |
| Checkout do PR de outra pessoa | `gh pr checkout N` | `git fetch origin pull/N/head:pr-N && git checkout pr-N` |

## Cuidados

- A credencial é um segredo — nunca ecoe o valor no terminal nem cole em log/commit.
- Merge e close de issue são ações que mudam estado pro time inteiro — confirme escopo antes.
- No fallback, cheque o `http_status`/`conclusion` da resposta antes de anunciar sucesso — a
  requisição pode ter voltado com um corpo de erro (rate limit, permissão insuficiente).
