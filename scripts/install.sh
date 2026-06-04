#!/usr/bin/env bash
# Okami Agent — instalador (Linux / macOS / WSL). Único pré-requisito: git.
#   curl -fsSL https://raw.githubusercontent.com/OkamiOps/Okami-Agent/main/scripts/install.sh | bash
#
# O `uv` é o motor: instala o próprio Python, cria o venv isolado e as deps numa tacada.
# Você NÃO precisa de Python instalado. Sem dor de long-path (o uv usa um diretório curto).
set -euo pipefail

REPO_URL="${OKAMI_REPO:-https://github.com/OkamiOps/Okami-Agent.git}"
say()  { printf '\033[1;36m› %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# 1) uv — instala se faltar (cuida de Python + venv + deps)
if ! command -v uv >/dev/null 2>&1; then
  say "instalando o uv (gerencia Python + venv)…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi
command -v uv >/dev/null 2>&1 || die "uv não entrou no PATH — reabra o terminal e rode de novo."
ok "uv $(uv --version | awk '{print $2}')"

# 2) código — repo local (se rodando de dentro dele) OU clona
SDIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -n "$SDIR" ] && [ -f "$SDIR/../pyproject.toml" ]; then
  SRC="$(cd "$SDIR/.." && pwd)"; say "usando o repo local: $SRC"
elif [ -d "${OKAMI_HOME:-$HOME/.okami-agent}/.git" ]; then
  SRC="${OKAMI_HOME:-$HOME/.okami-agent}"; say "atualizando $SRC"; git -C "$SRC" pull --ff-only || true
else
  command -v git >/dev/null 2>&1 || die "git é necessário para clonar."
  SRC="${OKAMI_HOME:-$HOME/.okami-agent}"; say "clonando em $SRC"; git clone --depth 1 "$REPO_URL" "$SRC"
fi

# 3) instala o `okami` como ferramenta GLOBAL isolada (uv baixa um Python compatível se faltar)
say "instalando o okami…"
uv tool install --force "$SRC"
uv tool update-shell >/dev/null 2>&1 || true     # garante o bin do uv no PATH

ok "pronto!"
printf '\n  Agora rode:  \033[1mokami setup\033[0m   (e depois  okami chat)\n'
printf '  Se "okami" não for encontrado, reabra o terminal.\n'
