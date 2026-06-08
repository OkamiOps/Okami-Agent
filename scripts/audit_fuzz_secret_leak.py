"""Fuzzer 4: novos vetores — exfiltração via shell.

O `_SENSITIVE_PATH` original bloqueia paths 'conhecidos' mas tem 11 BYPASSES confirmados.
Aqui testo vetores complementares: redirecionamento, substituição de comando, expansão."""
from __future__ import annotations
import sys
from okami.core.tools.base import _SENSITIVE_PATH
from okami.core.approval import classify

# Casos que DEVERIAM ser detectados como sensíveis (esperado: retorna True do regex OU Sensitive)
LEAK_VECTORS = [
    # Printenv / env (P0 do audit 2026-06-08)
    'printenv',
    'env',
    'env | grep -i key',
    'env | grep -i secret',
    'env | grep -i token',
    # Subshell de expansão
    'echo $(printenv)',
    'echo `printenv`',
    'echo "$API_KEY"',
    'echo "${API_KEY}"',
    # Processos / env de processo
    'cat /proc/self/environ',
    'cat /proc/1/environ',
    'cat /proc/self/environ | grep -i key',
    # /proc filesystem leaks
    'cat /proc/self/cmdline',
    'ls /proc/self/fd/',
    # History files
    'cat ~/.bash_history',
    'cat ~/.zsh_history',
    'cat ~/.python_history',
    'cat ~/.node_repl_history',
    'cat ~/.psql_history',
    'cat ~/.mysql_history',
    'cat ~/.rediscli_history',
    'cat ~/.pgpass',
    'cat ~/.my.cnf',
    'cat ~/.netrc',
    'cat ~/.git-credentials',
    'cat ~/.gitconfig',
    # SSH
    'cat ~/.ssh/id_rsa',
    'cat ~/.ssh/id_ed25519',
    'cat ~/.ssh/known_hosts',
    'cat ~/.ssh/config',
    'cat ~/.ssh/authorized_keys',
    # AWS
    'cat ~/.aws/credentials',
    'cat ~/.aws/config',
    'cat ~/.boto',
    # GCP / Azure
    'cat ~/.config/gcloud/application_default_credentials.json',
    'cat ~/.azure/azureProfile.json',
    # K8s
    'cat ~/.kube/config',
    'ls /var/run/secrets/kubernetes.io/serviceaccount/',
    'cat /var/run/secrets/kubernetes.io/serviceaccount/token',
    # macOS Keychain (não é file, mas shell pode triggar)
    'security find-generic-password -s test',
]

# O _SENSITIVE_PATH só bloqueia paths; para `printenv`/`env | grep` precisamos de outra defesa.
# Aqui só relatamos o que passa vs o que é bloqueado — não esperamos tudo ser bloqueado,
# só mostramos a lacuna.

print("=== Vetores de vazamento via shell — análise do _SENSITIVE_PATH ===")
bloqueados = 0
for c in LEAK_VECTORS:
    r = bool(_SENSITIVE_PATH.search(c))
    if r:
        bloqueados += 1
        print(f"  [BLOCK]   {c}")
    else:
        print(f"  [BYPASS]  {c}")

print(f"\nBloqueados: {bloqueados}/{len(LEAK_VECTORS)}")
