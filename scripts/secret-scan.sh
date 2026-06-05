#!/usr/bin/env bash
# Secret-scan — literais ÓBVIOS de chave em arquivos versionados (estilo gitleaks light).
# Fonte ÚNICA: a CI (secret-scan job) e o pytest (tests/test_secret_scan.py) chamam ESTE script,
# então gate e teste local nunca divergem.
#
# Allowlist EXPLÍCITA: uma linha marcada com `# pragma: allowlist secret` é um vetor FAKE de teste
# (redaction/lint) — visível e auditável no diff, não um segredo real. Só linhas marcadas são puladas;
# o scanner segue forte em TODO o resto (inclusive testes). Não exclui tests/ em bloco de propósito.
set -uo pipefail

fail=0
emit() { echo "::error::$1"; fail=1; }

# 1) arquivos que NUNCA devem ser versionados
git ls-files | grep -E '(^|/)\.env$'        && emit ".env está versionado"
git ls-files | grep -E 'okami\.local\.ya?ml$' && emit "okami.local.yaml está versionado"

# 2) padrões de chave em texto (ignora locks, exemplos e este próprio script)
hits=$(git grep -nIE '(sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----)' \
         -- . ':!*.lock' ':!*.example.*' ':!scripts/secret-scan.sh' \
       | grep -v 'pragma: allowlist secret' || true)
if [ -n "$hits" ]; then
  emit "possível segredo versionado (marque vetor de teste com '# pragma: allowlist secret'):"
  echo "$hits"
fi

[ "$fail" -eq 0 ] && echo "sem segredos versionados ✓"
exit "$fail"
