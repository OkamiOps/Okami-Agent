"""Fuzz: testa o regex _SENSITIVE_PATH do okami.core.tools.base contra casos de bypass.

Reproduz o achado do BUG #1 (2026-06-08): o regex bloqueia os 11 casos canônicos (okami/aws/etc/ssh/
.kube/.docker/git-credentials/codex/.pem/.key/secrets/.env) MAS deixa passar 9 vetores reais de
exfiltração em produção:

  1. Token K8s ServiceAccount (`/var/run/secrets/kubernetes.io/serviceaccount/token`)
  2. Variáveis de ambiente via /proc (`/proc/self/environ`, `/proc/1/environ`)
  3. Histórico de comandos (`.bash_history`, `.python_history`, `.zsh_history`)
  4. Git config com credencial embutida (`~/.gitconfig`)
  5. Pasta de segredos do runner (`/run/secrets/`)
  6. Dump de env (`printenv`, `env | grep -i key`)
  7. macOS: `/private/etc/…` (symlink de `/etc`)
  8. Config de ferramentas menos comuns (`~/.claude/.credentials.json` — só casa `.codex`)
  9. Hosts/gh em formato yml (`~/.config/gh/hosts.yml` — só casa `hosts` sem extensão)

Uso:
  cd .repo_compare_tmp/okami-agent
  source .venv/bin/activate
  python scripts/audit_fuzz_sensitive_path.py

Exit code 0 = todos os casos esperados passam; 1 = algum BYPASS ou FALSO+ foi encontrado.
"""
from __future__ import annotations

import sys
from pathlib import Path

# importa o regex REAL do projeto (fonte da verdade) — sem duplicar string
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from okami.core.tools.base import _SENSITIVE_PATH  # noqa: E402


# (descrição, comando, esperado: 'block' | 'pass')
CASES: list[tuple[str, str, str]] = [
    # ===== DEVEM BLOQUEAR (cobertos hoje) =====
    ("okami creds (home)",        "cat ~/.okami/credentials/openai.json",   "block"),
    ("okami creds (abs)",         "cat /home/x/.okami/credentials/k.json",  "block"),
    ("aws creds",                 "cat ~/.aws/credentials",                 "block"),
    ("etc shadow",                "cat /etc/shadow",                        "block"),
    ("ssh privkey rsa",           "cat ~/.ssh/id_rsa",                      "block"),
    ("ssh privkey ed25519",       "cat ~/.ssh/id_ed25519",                  "block"),
    ("secrets.json",              "cat secrets.json",                       "block"),
    (".env file",                 "cat .env.production",                    "block"),
    ("docker config",             "cat ~/.docker/config.json",              "block"),
    ("git-credentials",           "cat ~/.git-credentials",                 "block"),
    ("k8s config",                "cat ~/.kube/config",                     "block"),
    ("codex auth",                "cat ~/.codex/auth.json",                 "block"),
    ("pem/key file",              "cat server.pem",                         "block"),
    ("pypirc",                    "cat ~/.pypirc",                          "block"),
    ("ssh known_hosts",           "cat ~/.ssh/known_hosts",                 "block"),

    # ===== BYPASSES CONFIRMADOS (devem bloquear, mas NÃO bloqueiam) =====
    ("BYPASS: k8s SA token",      "cat /var/run/secrets/kubernetes.io/serviceaccount/token", "block"),
    ("BYPASS: proc self environ", "cat /proc/self/environ",                 "block"),
    ("BYPASS: proc 1 environ",    "cat /proc/1/environ",                    "block"),
    ("BYPASS: bash history",      "cat ~/.bash_history",                    "block"),
    ("BYPASS: python history",    "cat ~/.python_history",                  "block"),
    ("BYPASS: zsh history",       "cat ~/.zsh_history",                     "block"),
    ("BYPASS: gitconfig w/ cred", "cat ~/.gitconfig",                       "block"),
    ("BYPASS: k8s SA dir list",   "ls /run/secrets/",                       "block"),
    ("BYPASS: env dump (printenv)", "printenv",                             "block"),
    ("BYPASS: env pipe",          "env | grep -i key",                      "block"),
    ("BYPASS: macOS /private/etc","sed -i s/x/y/ /private/etc/sudoers",     "block"),
    ("BYPASS: claude credentials","cat ~/.claude/.credentials.json",        "block"),
    ("BYPASS: gh hosts.yml",      "cat ~/.config/gh/hosts.yml",             "block"),

    # ===== DEVEM PASSAR (legítimos, sem falso-positivo) =====
    ("ok: ls normal",             "ls -la /tmp",                            "pass"),
    ("ok: cat código-fonte",      "cat src/main.py",                        "pass"),
    ("ok: pwd",                   "pwd",                                    "pass"),
    ("ok: env set",               "FOO=bar echo hi",                        "pass"),
    ("ok: settings.json de app",  "cat ~/.vscode/settings.json",            "pass"),
]


def main() -> int:
    fails: list[str] = []
    print(f"testando {len(CASES)} casos contra _SENSITIVE_PATH\n")
    for desc, cmd, want in CASES:
        got_block = bool(_SENSITIVE_PATH.search(cmd))
        got = "BLOQUEADO" if got_block else "PASSA   "
        if want == "block" and not got_block:
            tag = "✗ BYPASS"
            fails.append(f"  {tag}: {desc}  →  {cmd!r}")
            print(f"  {tag} {got}  {desc}: {cmd}")
        elif want == "pass" and got_block:
            tag = "✗ FALSO+"
            fails.append(f"  {tag}: {desc}  →  {cmd!r}")
            print(f"  {tag} {got}  {desc}: {cmd}")
        else:
            print(f"  ✓ {got}  {desc}: {cmd}")

    print(f"\n{len(fails)} falhas de {len(CASES)} casos")
    if fails:
        print("\nDETALHES:")
        for f in fails:
            print(f)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
