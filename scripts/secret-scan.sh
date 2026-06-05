#!/usr/bin/env bash
# Secret-scan — literais ÓBVIOS de chave (estilo gitleaks light). Fonte ÚNICA: a CI (secret-scan job)
# e o pytest (tests/test_secret_scan.py) chamam ESTE script, então gate e teste nunca divergem.
#
# Allowlist EXPLÍCITA: linha com `# pragma: allowlist secret` é vetor FAKE de teste (auditável no diff);
# só ela é pulada, o resto segue forte (inclusive tests/). Não exclui tests/ em bloco de propósito.
#
# DOIS modos (#P1: não dá falso-verde fora do git): dentro de um worktree git → varre arquivos
# VERSIONADOS (rápido/preciso); FORA (sdist/tarball sem .git) → fallback de FILESYSTEM (não diz
# "limpo" sem ter conseguido listar nada).
set -uo pipefail

fail=0
emit() { echo "::error::$1"; fail=1; }
PAT='(sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----)'

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  # --- modo GIT (CI/dev): arquivos versionados ---
  git ls-files | grep -E '(^|/)\.env$'          && emit ".env está versionado"
  git ls-files | grep -E 'okami\.local\.ya?ml$' && emit "okami.local.yaml está versionado"
  hits=$(git grep -nIE "$PAT" -- . ':!*.lock' ':!*.example.*' ':!scripts/secret-scan.sh' \
         | grep -v 'pragma: allowlist secret' || true)
else
  # --- modo FILESYSTEM (sem .git): varre o disco com excludes (nunca diz "limpo" às cegas) ---
  echo "::warning::fora de um repositório git — varrendo o filesystem (fallback)"
  find . -type f -name '.env' -not -path './.git/*' 2>/dev/null | grep -q . && emit ".env presente no pacote"
  hits=$(grep -rInE "$PAT" . \
           --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=dist --exclude-dir=.venv \
           --exclude='*.lock' --exclude='*.example.*' --exclude='secret-scan.sh' 2>/dev/null \
         | grep -v 'pragma: allowlist secret' || true)
fi

if [ -n "$hits" ]; then
  emit "possível segredo (marque vetor de teste com '# pragma: allowlist secret'):"
  echo "$hits"
fi

[ "$fail" -eq 0 ] && echo "sem segredos versionados ✓"
exit "$fail"
